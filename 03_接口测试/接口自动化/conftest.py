# -*- coding: utf-8 -*-
"""conftest.py —— pytest 接口自动化公共配置
- 会话级登录取 Token（避免登录限流/重复登录）
- 登录后做一次「受保护接口鉴权自检」，Token 未生效立即终止会话（防止假通过）
- 提供 API 请求封装（统一 Header）
- 已知缺陷标记：pytest.ini 中已配置 xfail_strict
- Allure 集成：用例内每个 HTTP 响应都会被登记，**用例失败时自动附加**
  请求 URL / 请求参数 / 响应状态码 / 响应体，无需在每个用例里手写 attach
- 日志：核心步骤按 0~4 编号输出到控制台与 logs/（配置见下方「核心步骤日志」）

可用环境变量覆盖默认配置（详见仓库根目录 .env.example）：
    FORUM_BASE / FORUM_USER / FORUM_PWD
    FORUM_ALLOW_REMOTE_TESTS=1 仅在已获授权的远程测试环境使用
"""
import logging
import os
import random
import re
import string
import sys
from datetime import datetime
from urllib.parse import urlparse, unquote

import allure
import pytest
import requests

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))

# 可选：从仓库根目录 .env 读取配置（未安装 python-dotenv 时忽略，仍可用系统环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, "..", "..", ".env"), encoding="utf-8")
except ImportError:
    pass

BASE = os.environ.get("FORUM_BASE", "http://localhost:8080")
USER = os.environ.get("FORUM_USER", "testuser")
PWD = os.environ.get("FORUM_PWD", "")


def _is_local_base(base):
    """本地实例不需要额外授权；远程实例必须显式确认。"""
    host = (urlparse(base).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}

# 当前用例内发生过的全部响应，供失败时自动附加到 Allure 报告
_HTTP_LOG = []


# --------------------------------------------------------------------------- #
# Allure severity —— 对齐《01_测试计划》§8 缺陷等级定义
#
# severity 标的是「**该用例失败时**，对应缺陷按项目口径应判定的等级」，
# 不是「当前已发现的缺陷等级」。本项目已确认的缺陷等级见各 xfail 用例：
# BUG-001/BUG-002 = P1，BUG-003 = P2（测试计划 §8 实例列）。
# 因此报告中出现 blocker 标签 ≠ 存在 P0 缺陷，只表示该用例若失败即为致命级。
#
#   | 项目等级 | 定义（测试计划 §8）                    | Allure 等级 |
#   |---------|--------------------------------------|-------------|
#   | P0 致命  | 系统崩溃、核心功能完全不可用、数据丢失      | BLOCKER     |
#   | P1 严重  | 核心功能异常、安全风险、无绕过方式        | CRITICAL    |
#   | P2 一般  | 非核心功能异常、有绕过方式、体验问题       | NORMAL      |
#   | P3 轻微  | UI 样式、文案、兼容性小问题              | MINOR       |
# --------------------------------------------------------------------------- #
P0 = allure.severity_level.BLOCKER
P1 = allure.severity_level.CRITICAL
P2 = allure.severity_level.NORMAL
P3 = allure.severity_level.MINOR


# --------------------------------------------------------------------------- #
# 核心步骤日志
#
# 沿用接口自动化通用的 0~4 编号，每个用例输出一组：
#   0.测试用例的描述信息   用例 id / 模块 / 场景 / 标题
#   1.数据解析信息         本次请求要发什么（方式 / URL / 请求头 / 参数或请求体）
#   2.请求发送情况         发出去的结果（状态码 / 耗时 / 响应体大小 / 响应内容）
#   3.断言情况             本用例断言的整体结论（通过 / 失败 / 预期失败 / 跳过）
#   4.提取有关信息         从响应中提取出来、供后续复用的变量（接口关联）
#
# 落点：0 由 _log_case_desc（autouse fixture）在用例开始时打印；
#       1/2 由 record() 对**每个 HTTP 请求**打印；
#       3 由 pytest_runtest_makereport 在用例结束时打印；
#       4 由 log_extract() 在真实的提取处打印。
#
# ⚠️ 一个用例发多个请求时，1/2 会成对重复出现；4 出现在真正提取的位置，
#    因此同一用例内的编号可能不是严格递增（例如先 4.提取 id、再发下一个请求）。
#    这是按「步骤实际发生的位置」输出，不做重排。
# --------------------------------------------------------------------------- #
LOG_DIR = os.path.join(HERE, "logs")
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

# 日志里必须脱敏的头：Flarum 的 Token 等同口令，落盘不得明文
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization"}

# 日志里必须脱敏的 JSON 字段：
#   password —— 登录请求体里是明文口令
#   token    —— 登录响应体里是会话凭证（请求头脱敏了，响应体不脱敏照样泄漏）
_SENSITIVE_BODY_KEYS = ("password", "token")

_HEADER_CLIP = 300
_BODY_CLIP = 300


def _clip(value, limit):
    """转成单行文本并截断，避免大响应体把日志刷爆"""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + f"...(共 {len(text)} 字符)"


def _mask_headers(headers):
    """请求头脱敏：Authorization / Cookie 之类只保留「头存在」这一事实"""
    return {k: ("***（已脱敏）" if k.lower() in _SENSITIVE_HEADERS else v)
            for k, v in (headers or {}).items()}


def _mask_body(text):
    """请求体/响应体脱敏：抹掉 password / token 的取值，只留字段名"""
    for key in _SENSITIVE_BODY_KEYS:
        text = re.sub(rf'"{key}"\s*:\s*"[^"]*"', f'"{key}":"***（已脱敏）"', text)
    return text


def _request_param_text(req):
    """请求参数的可读形式：有请求体就用请求体，否则用 URL 查询串（解码后）。

    log_http（写「1.数据解析信息」）与 attach_response（写 Allure 附件）都要用，
    抽出成一个函数，避免两处各维护一份同样的解码逻辑、日后改漏一处。
    """
    body = req.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if body:
        return body
    # GET 的参数编码在 URL 查询串里，解码后单独列出更易读
    query = urlparse(req.url or "").query
    return unquote(query) if query else "(无请求参数)"


def log_http(r):
    """1.数据解析信息 + 2.请求发送情况 —— 登记一次请求/响应到日志。

    只写日志、不碰 Allure 的请求清单，故 auth 这类不参与用例失败归因的请求也能安全调用。
    """
    req = r.request
    logging.info("1.数据解析信息: 请求方式:%s 请求URL:%s 请求头:%s 请求参数:%s",
                 req.method, req.url, _clip(_mask_headers(req.headers), _HEADER_CLIP),
                 _clip(_mask_body(_request_param_text(req)), _BODY_CLIP))

    logging.info("2.请求发送情况: 响应状态码:%s 耗时:%.2fs 响应体长度:%s 响应内容:%s",
                 r.status_code, r.elapsed.total_seconds(), len(r.content or b""),
                 _clip(_mask_body(r.text or ""), _BODY_CLIP))


def log_extract(name, value, sensitive=False):
    """4.提取有关信息 —— 从响应中提取变量供后续复用（接口关联）。

    返回 value 本身，便于就地赋值：did = log_extract("discussion_id", ...)
    sensitive=True 时只记录变量名，不落盘取值（如 token）。
    """
    logging.info("4.提取有关信息: %s = %s", name,
                 "***（已脱敏）" if sensitive else _clip(value, _BODY_CLIP))
    return value


# 失败断言的位置（test_xxx.py:78）—— 从 pytest 的短回溯里取最后一条
_LOC_RE = re.compile(r"^([^\s:]+\.py):(\d+): ")


def _failure_brief(rep):
    """从用例报告里取一行失败摘要：失败断言所在位置 + 异常消息"""
    text = str(rep.longrepr or "").strip()
    if not text:
        return "(无回溯信息)"

    lines = text.splitlines()
    locs = [_LOC_RE.match(ln.strip()) for ln in lines]
    locs = [m for m in locs if m]
    loc = f"{locs[-1].group(1)}:{locs[-1].group(2)}" if locs else "位置未知"

    # pytest 的短回溯里 E 行可能有多条，顺序是「异常消息 → 断言表达式 → 变量取值」，
    # 取 errs[0] 才是有信息量的那条（errs[-1] 往往只是 `assert 0 > 0`）
    errs = [ln.strip()[2:].strip() for ln in lines if ln.strip().startswith("E ")]
    detail = errs[0] if errs else lines[-1].strip()
    return f"{loc} → {_clip(detail, _BODY_CLIP)}"


def _log_assert_result(item, call):
    """3.断言情况 —— 用例结束时汇总本用例的断言结论。

    ⚠️ 本函数由 trylast 的 hook 调用，拿到的 rep_call 是 _pytest/skipping.py 把
    「xfail 失败 → outcome=skipped + wasxfail」转换**之前**的原始报告，
    rep.wasxfail 此时还是空的。所以预期失败必须自己判，否则「成功复现已知缺陷」
    会被误报成「失败」，日志反而把 7 条 xfail 全说成 bug。
      - @pytest.mark.xfail 标记 → 显式标记的已知缺陷用例
      - call 抛的是 XFailed    → 用例内主动调 pytest.xfail()（见 _assert_not_rate_limited）
    """
    rep = getattr(item, "rep_call", None)
    if rep is None:
        # setup 阶段就失败（如 fixture 异常），根本没有 call 阶段报告
        setup_rep = getattr(item, "rep_setup", None)
        if setup_rep is not None and setup_rep.failed:
            logging.error("3.断言情况: 未执行到断言 —— 用例前置(setup)失败: %s",
                          _failure_brief(setup_rep))
        return

    mark = item.get_closest_marker("xfail")
    runtime_xfail = (call is not None and call.excinfo is not None
                     and isinstance(call.excinfo.value, pytest.xfail.Exception))

    if rep.skipped:
        logging.warning("3.断言情况: 跳过 —— %s", _clip(rep.longrepr, _BODY_CLIP))
    elif (mark or runtime_xfail) and rep.failed:
        reason = (mark.kwargs.get("reason") if mark else None) or \
            (str(call.excinfo.value) if runtime_xfail else "") or "未填写原因"
        logging.warning("3.断言情况: 预期失败(XFAIL) —— 成功复现已知缺陷: %s",
                        _clip(reason, _BODY_CLIP))
    elif mark or runtime_xfail:
        reason = (mark.kwargs.get("reason") if mark else None) or "用例内 pytest.xfail()"
        logging.error("3.断言情况: 意外通过(XPASS) —— 本应失败的用例通过了，"
                      "已知缺陷可能已修复，需复核: %s", _clip(reason, _BODY_CLIP))
    elif rep.failed:
        logging.error("3.断言情况: 失败 —— %s", _failure_brief(rep))
    else:
        logging.info("3.断言情况: 全部断言通过")


def pytest_configure(config):
    """初始化日志：文件处理器；控制台实时输出由 pytest.ini 的 log_cli 负责。"""
    if getattr(config, "_forum_logging_ready", False):
        return
    config._forum_logging_ready = True

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"api_run_{datetime.now():%Y%m%d_%H%M%S}.log")

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))
    handler.setLevel(logging.INFO)

    root = logging.getLogger()
    # pytest 默认不改 root 的级别（logging 原生默认 WARNING），
    # 不显式降到 INFO 的话 logging.info 会在「logger 级别检查」这一步就被丢弃。
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    logging.info("=" * 72)
    logging.info("接口自动化执行开始 · %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("被测站点:%s 账号:%s 日志文件:%s", BASE, USER, log_path)
    logging.info("=" * 72)


class _ConsoleOnlyCaseTitle(logging.Filter):
    """控制台只放行「0.测试用例的描述信息」，1~4 步只写日志文件。

    一个用例会产出 6 条以上日志，其中 1/2 还带着完整请求头与响应体，直接铺在控制台上
    会把终端的进度输出冲得没法看；跑的时候真正需要一眼扫到的是「正在跑哪条用例」。
    完整步骤仍一条不少地留在 logs/api_run_*.log 与 Allure 报告里。

    顺带压掉 pytest 的 "live log setup" 分隔条：它是 _LiveLoggingStreamHandler 在
    首个记录到来时打的相位标题，控制台既然只剩标题一行，这条分隔就纯属噪声。
    为此要碰 pytest 的私有属性 _section_name_shown —— 属有意的取舍：
    万一将来 pytest 改版改名，后果只是分隔条重新冒出来（多一行），
    日志内容与用例结果都不受影响。
    """

    def __init__(self, handler):
        super().__init__()
        self._handler = handler

    def filter(self, record):
        if not getattr(record, "to_console", False):
            return False
        self._handler._section_name_shown = True   # 抑制 "live log xxx" 分隔条
        return True


def pytest_sessionstart(session):
    """给 pytest 的实时输出处理器装一道滤网（pytest.ini 开了 log_cli 才有它），
    使控制台只打「0.测试用例的描述信息」；文件处理器不加滤网，完整步骤照旧全部落盘。

    必须放在 sessionstart、不能放在 pytest_configure：conftest 的 pytest_configure
    跑在 _pytest.logging 之前，那时 "logging-plugin" 尚未注册，get_plugin 返回 None，
    滤网会**静默挂空**——控制台照样被请求头刷屏，且看不出哪里错了。
    """
    plugin = session.config.pluginmanager.get_plugin("logging-plugin")
    handler = getattr(plugin, "log_cli_handler", None)
    if handler is None:
        # 不静默：这条警告会打到控制台，一眼能看出滤网没生效
        logging.warning("未能挂上控制台滤网（pytest 的 log_cli 处理器不可达），"
                        "控制台将输出全部 0~4 步骤日志。")
        return
    handler.addFilter(_ConsoleOnlyCaseTitle(handler))


# --------------------------------------------------------------------------- #
# Allure：请求/响应采集与附加
# --------------------------------------------------------------------------- #
def record(r, **kwargs):
    """登记一次响应到本用例的请求日志，并原样返回该响应。

    用例失败时，日志里的每个响应都会被自动附加到 Allure 报告
    （见 _attach_http_log_on_failure）；同时打印「1.数据解析信息 / 2.请求发送情况」。

    两种用法共用一个函数：
      - 挂到 Session.hooks['response']，自动登记该会话发出的每个响应；
      - 显式套一层 record(...) 包装裸 requests.post/get —— 它们不经过 Session，
        不包装就不会被登记。requests 调 hook 时会多传 kwargs，故此处接收并忽略。
    """
    _HTTP_LOG.append(r)
    log_http(r)
    return r


def attach_response(r, prefix="HTTP"):
    """把一次请求的 URL / 参数 / 状态码 / 响应体写入 Allure 报告"""
    req = r.request
    allure.attach(req.url or "(未知)", f"{prefix} - 请求URL", allure.attachment_type.TEXT)
    allure.attach(_request_param_text(req), f"{prefix} - 请求参数", allure.attachment_type.TEXT)
    allure.attach(str(r.status_code), f"{prefix} - 响应状态码", allure.attachment_type.TEXT)
    allure.attach((r.text or "")[:5000], f"{prefix} - 响应体", allure.attachment_type.TEXT)


def _attach_http_log_on_failure(item):
    """用例失败时，把本次用例发出的所有请求详情附加到 Allure 报告的**用例本体**下。

    只在**失败**时附加 —— 断言 4xx 的用例（401/403/404/422 等）属预期结果，
    若不加区分地附加，报告会被预期内的错误响应淹没。
    """
    failed = any(getattr(item, "rep_" + phase, None) is not None
                 and getattr(item, "rep_" + phase).failed
                 for phase in ("setup", "call"))
    if not failed:
        return

    if not _HTTP_LOG:
        allure.attach("本用例未记录到 HTTP 响应（可能请求前即失败，或抛出了连接异常）。",
                      "无请求记录", allure.attachment_type.TEXT)
        return

    for i, r in enumerate(_HTTP_LOG, 1):
        attach_response(r, f"#{i} {r.request.method}")


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item, call):
    """记录各阶段结果；并在 teardown 阶段把失败用例的请求详情附加到报告。

    附加放在这里而非 fixture teardown：fixture 内调 allure.attach 会挂到
    fixture 自己的节点下、在报告中折叠进 "Tear down"，不显眼。teardown 阶段
    的 makereport 执行时用例对象尚未关闭（allure 在 pytest_runtest_protocol 才
    关闭它），因此此处附加会正确挂在用例本体下。

    「3.断言情况」也在这里打印：call 阶段的报告刚生成、rep_call 已挂到 item 上，
    正好是断言结论唯一可得的时点。
    """
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)

    if rep.when == "call":
        _log_assert_result(item, call)
    elif rep.when == "teardown":
        _attach_http_log_on_failure(item)


@pytest.fixture(autouse=True)
def _reset_http_log():
    """每个用例开始前清空请求日志，避免继承上一个用例的响应"""
    del _HTTP_LOG[:]


@pytest.fixture(scope="session", autouse=True)
def _guard_target():
    """默认只允许本地实例，避免把测试脚本误指向未授权站点。"""
    if not _is_local_base(BASE) and os.environ.get("FORUM_ALLOW_REMOTE_TESTS") != "1":
        pytest.exit(
            f"FORUM_BASE={BASE} 不是本地地址。为避免误测未授权站点，远程运行请设置 "
            "FORUM_ALLOW_REMOTE_TESTS=1（仅限已获授权的环境）。",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def _log_case_desc(request):
    """0.测试用例的描述信息 —— 每个用例开始时打印一行用例身份。

    用例 id / 模块 / 场景 / 标题都不是手写常量，而是从用例自身取：
      - id    ：pytest 的 nodeid（文件::函数名），天然唯一，不会与用例重命名脱节
      - 模块/场景：@allure.feature / @allure.story —— allure 在 pytest 下会把它们
                  注册成名为 allure_label 的 marker，此处按 label_type 读回
      - 标题   ：@allure.title —— allure 写在函数对象的 __allure_display_name__ 上

    这样 26 条用例零改动即可全覆盖，标注改一处、日志跟着变，不会两边不一致。
    取不到时留「（未标注）」而不是静默留空——空值会让日志看着"正常"却什么也没说。
    """
    item = request.node

    def _label(label_type):
        for mark in item.iter_markers(name="allure_label"):
            if mark.kwargs.get("label_type") == label_type and mark.args:
                return mark.args[0]
        return "（未标注）"

    title = getattr(getattr(item, "obj", None), "__allure_display_name__", None)

    # to_console=True 是全场唯一会打到控制台的标记，见 _ConsoleOnlyCaseTitle
    logging.info("0.用例id:%s 模块:%s 场景:%s 标题:%s",
                 item.nodeid, _label("feature"), _label("story"), title or "（未标注）",
                 extra={"to_console": True})


# marker 声明统一在 pytest.ini（唯一出处），此处不再重复 addinivalue_line。


# --------------------------------------------------------------------------- #
# 登录与鉴权
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def auth():
    """会话级登录一次，返回 {"token", "user_id"}，并完成鉴权自检。

    user_id 由登录响应自举 —— Flarum 的 /api/token 同时返回 token 与 userId，
    用例里不应再硬编码账号 id。
    """
    if not USER or not PWD:
        pytest.exit("请设置 FORUM_USER / FORUM_PWD 环境变量（参考仓库根目录 .env.example）。",
                    returncode=1)
    logging.info("【会话级前置】登录并做鉴权自检（只执行一次）")
    r = requests.post(BASE + "/api/token",
                      json={"identification": USER, "password": PWD}, timeout=20)
    # 这两个请求不参与「用例失败归因」，故只用 log_http 写日志，不进 _HTTP_LOG
    log_http(r)
    if r.status_code != 200:
        pytest.exit(f"登录失败：HTTP {r.status_code} {r.text[:120]}\n"
                    f"请确认 {BASE} 可访问、账号 {USER} 有效。", returncode=1)

    data = r.json()
    session = {"token": log_extract("token", data["token"], sensitive=True),
               "user_id": log_extract("userId", str(data["userId"]))}

    # 鉴权自检：受保护接口必须可访问。
    # 若认证头拼错（例如写成 Bearer），Flarum 会当作未登录 —— 此时**读接口照样返回数据**，
    # 极易被误判成"功能正常"，直到写接口报 400 csrf_token_mismatch 才暴露。故此处快速失败。
    chk = requests.get(BASE + "/api/notifications",
                       headers={"Authorization": f"Token {session['token']}"}, timeout=20)
    log_http(chk)
    if chk.status_code != 200:
        pytest.exit(f"鉴权自检失败：/api/notifications 返回 HTTP {chk.status_code}（期望 200）。\n"
                    f"Flarum 的认证头是 'Authorization: Token <token>'，不是 'Bearer'；"
                    f"请检查本文件中的 Header 拼装。", returncode=1)

    return session


@pytest.fixture(scope="session")
def user_id(auth):
    """当前账号的 userId（由登录响应自举，避免硬编码）"""
    return auth["user_id"]


@pytest.fixture(scope="session")
def client(auth):
    """带 Token 的 requests.Session（GET 只读接口）"""
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Token {auth['token']}",
        "Accept": "application/json",
    })
    s.hooks["response"].append(record)
    return s


@pytest.fixture(scope="session")
def write_client(auth):
    """带 Token 的写操作 Session（POST/PATCH/DELETE，含 Content-Type）"""
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Token {auth['token']}",
        "Accept": "application/json",
        "Content-Type": "application/vnd.api+json",
    })
    s.hooks["response"].append(record)
    return s


@pytest.fixture
def rand_suffix():
    """随机后缀，避免帖子标题冲突"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
