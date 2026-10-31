# -*- coding: utf-8 -*-
"""UI 自动化主链路回归（Playwright）

E2E-01 首页加载-帖子列表可见
E2E-02 搜索-关键词命中
E2E-03 浏览帖子详情-标题/内容可见
E2E-04 登录-正确账号密码
E2E-05 发帖-正常发布（选板块，只发 1 篇）
E2E-06 退出登录

配置（环境变量，参考仓库根目录 .env.example）：
    FORUM_BASE              默认 http://localhost:8080
    FORUM_USER / FORUM_PWD  未配置时跳过 E2E-04/05/06，只跑只读场景
    FORUM_DISCUSSION_ID     详情页靶点，默认 1
    FORUM_SEARCH_KEYWORD    搜索关键词，默认 123
    FORUM_TAG_NAME          发帖板块名，默认“测试技术类”
    FORUM_ALLOW_REMOTE_TESTS=1  仅当 BASE 不是本地地址且已获授权时设置

说明：脚本默认只允许本地实例，避免误测未授权站点。原项目在一个公开练习论坛上完成，
公开仓库不提供该站点地址与账号。
"""
import sys, os, json, time
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))          # 06_UI自动化/
SHOTS = os.path.join(HERE, "截图")                          # 运行时截图，随脚本走
OUT = os.path.join(HERE, "结果_UI自动化.json")

# 可选：从仓库根目录 .env 读取配置（未安装 python-dotenv 时忽略）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, "..", ".env"), encoding="utf-8")
except ImportError:
    pass

BASE = os.environ.get("FORUM_BASE", "http://localhost:8080").rstrip("/")
USER = os.environ.get("FORUM_USER", "testuser")
PWD = os.environ.get("FORUM_PWD", "")
DETAIL_ID = os.environ.get("FORUM_DISCUSSION_ID", "1")
SEARCH_KEYWORD = os.environ.get("FORUM_SEARCH_KEYWORD", "123")
TAG_NAME = os.environ.get("FORUM_TAG_NAME", "测试技术类")
HAS_AUTH = bool(USER and PWD)
results = []

os.makedirs(SHOTS, exist_ok=True)   # 截图目录按需创建，不进版本库


def guard_target():
    host = (urlparse(BASE).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and \
            os.environ.get("FORUM_ALLOW_REMOTE_TESTS") != "1":
        print(f"FORUM_BASE={BASE} 不是本地地址。为避免误测未授权站点，"
              "远程运行请设置 FORUM_ALLOW_REMOTE_TESTS=1（仅限已获授权的环境）。")
        sys.exit(1)


def rec(no, title, ok, actual):
    results.append({"用例": no, "标题": title, "结果": "通过" if ok else "失败", "实际": actual})
    print(f"[{'通过' if ok else '失败'}] {no} {title}  → {actual[:100]}")


def skip(no, title, reason):
    results.append({"用例": no, "标题": title, "结果": "跳过", "实际": reason})
    print(f"[跳过] {no} {title}  → {reason}")


def goto_retry(pg, url, retry=3):
    """goto 重试包装（网络偶有抖动时重试）"""
    for i in range(retry):
        try:
            pg.goto(url, wait_until="load")
            pg.wait_for_timeout(800)
            return
        except Exception:
            if i == retry - 1:
                raise
            pg.wait_for_timeout(2000)


guard_target()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(20000)

    # ---------- E2E-01 首页加载-帖子列表可见 ----------
    try:
        goto_retry(pg, BASE)
        cards = pg.query_selector_all(".DiscussionListItem, .discussion-list .DiscussionListItem, .IndexGrid .DiscussionListItem")
        ok = len(cards) >= 1
        rec("E2E-01", "首页加载-帖子列表可见", ok, f"帖子卡片数={len(cards)}")
    except Exception as e:
        rec("E2E-01", "首页加载-帖子列表可见", False, f"异常:{repr(e)[:90]}")

    # ---------- E2E-02 搜索-关键词命中 ----------
    try:
        sb = pg.query_selector("input[placeholder='搜索']")
        if not sb:
            raise Exception("未找到搜索框")
        sb.fill(SEARCH_KEYWORD)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(3000)
        hit = SEARCH_KEYWORD in pg.evaluate("document.body.innerText")[:2000]
        hit_any = len(pg.query_selector_all(".DiscussionListItem")) > 0
        rec("E2E-02", "搜索-关键词命中", hit_any and hit,
            f"结果列表有帖:{hit_any} 页面含关键词:{hit}")
        pg.screenshot(path=os.path.join(SHOTS, "e2e_search.png"))
    except Exception as e:
        rec("E2E-02", "搜索-关键词命中", False, f"异常:{repr(e)[:90]}")

    # ---------- E2E-03 浏览帖子详情 ----------
    try:
        goto_retry(pg, f"{BASE}/d/{DETAIL_ID}")
        t = pg.evaluate("document.title")
        body = pg.evaluate("document.body.innerText")
        ok = f"/d/{DETAIL_ID}" in pg.url and len(body) > 100
        rec("E2E-03", "浏览帖子详情-标题/内容可见", ok,
            f"页面标题:{t[:50]} 正文长度:{len(body)}")
    except Exception as e:
        rec("E2E-03", "浏览帖子详情-标题/内容可见", False, f"异常:{repr(e)[:90]}")

    if not HAS_AUTH:
        skip("E2E-04", "登录-正确账号密码", "未配置 FORUM_USER / FORUM_PWD")
        skip("E2E-05", "发帖-正常发布(选板块)", "未配置 FORUM_USER / FORUM_PWD")
        skip("E2E-06", "退出登录", "未配置 FORUM_USER / FORUM_PWD")
    else:
        # ---------- E2E-04 登录 ----------
        try:
            goto_retry(pg, BASE)
            pg.click("button:has-text('登录')")
            pg.wait_for_timeout(1200)
            pg.fill("input[name=identification]", USER)
            pg.fill("input[name=password]", PWD)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(3000)
            top = pg.eval_on_selector_all(
                "header a, header button, .Header-primary a, .Header-controls a",
                "els=>els.map(e=>(e.innerText||'').trim()).filter(Boolean)")
            logged = any(USER in t for t in top)
            rec("E2E-04", "登录-正确账号密码", logged, f"顶部显示:{top[:6]}")
        except Exception as e:
            rec("E2E-04", "登录-正确账号密码", False, f"异常:{repr(e)[:90]}")

        # ---------- E2E-05 发帖-正常发布（选板块，1篇控频） ----------
        try:
            goto_retry(pg, BASE)
            pg.click("a:has-text('发布主题'), button:has-text('发布主题')")
            pg.wait_for_timeout(1500)
            title = f"【UI自动化】主链路 {time.strftime('%H%M%S')}"
            pg.fill("input[placeholder='标题']", title)
            pg.fill("textarea[placeholder*='说点什么']",
                    "Playwright UI 自动化主链路回归发帖，验证完整发布流程可用。")
            pg.wait_for_timeout(500)

            # 选板块：点“选择标签”→ 弹窗选目标板块 → 点确定
            tag_ok = False
            change_btn = pg.query_selector(".DiscussionComposer-changeTags, a:has-text('选择标签')")
            if change_btn:
                change_btn.click()
                pg.wait_for_timeout(1200)
                opt = pg.query_selector(
                    f".SelectTagList li:has-text('{TAG_NAME}'), .TagSelectionModal-list li:has-text('{TAG_NAME}')")
                if opt:
                    opt.click()
                    pg.wait_for_timeout(600)
                    confirm = pg.query_selector(
                        ".TagSelectionModal .Button--primary:not(.disabled), "
                        ".TagSelectionModal button[type=submit]:not(.disabled)")
                    if confirm:
                        confirm.click()
                        pg.wait_for_timeout(800)
                        tag_ok = pg.query_selector(
                            f".Composer .TagsLabel .TagLabel-name:has-text('{TAG_NAME}')") is not None
            print(f"  板块选择成功: {tag_ok}")

            # 点发布
            submit = pg.query_selector(".Composer .Composer-submit, .Composer button:has-text('发布')")
            if not submit:
                raise Exception("未找到发布按钮")
            submit.click()
            pg.wait_for_timeout(4000)
            posted = "/d/" in pg.url
            new_id = pg.url.split("/d/")[-1] if posted else "?"
            rec("E2E-05", "发帖-正常发布(选板块)", posted and tag_ok,
                f"发布后URL:{pg.url} 板块选中:{tag_ok}")
            pg.screenshot(path=os.path.join(SHOTS, "e2e_post.png"))
            print(f"  新帖 id={new_id} 标题={title}（UI自动化测试数据，需清理）")
        except Exception as e:
            rec("E2E-05", "发帖-正常发布(选板块)", False, f"异常:{repr(e)[:100]}")
            pg.screenshot(path=os.path.join(SHOTS, "e2e_post_fail.png"))

        # ---------- E2E-06 退出登录 ----------
        try:
            goto_retry(pg, BASE)
            user_btn = pg.query_selector(".SessionDropdown .Dropdown-toggle, header .Button--user")
            if not user_btn:
                raise Exception("未找到用户菜单")
            user_btn.click()  # 打开下拉（Flarum 下拉菜单 DOM 常驻，靠 open class 显示）
            pg.wait_for_timeout(800)
            is_open = pg.eval_on_selector(".SessionDropdown", "e=>e.classList.contains('open')")
            if not is_open:
                pg.eval_on_selector(".SessionDropdown .Dropdown-toggle", "e=>e.click()")
                pg.wait_for_timeout(500)
            logout = pg.query_selector(".item-logOut button, .SessionDropdown button:has-text('退出')")
            if not logout:
                raise Exception("未找到退出按钮")
            logout.click(force=True)  # 兜底：DOM 已存在，隐藏状态也能触发事件
            pg.wait_for_timeout(2000)
            top2 = pg.eval_on_selector_all(
                "header a, header button",
                "els=>els.map(e=>(e.innerText||'').trim()).filter(Boolean)")
            logged_out = any("登录" in t for t in top2)
            rec("E2E-06", "退出登录", logged_out, f"退出后顶部:{top2[:5]}")
        except Exception as e:
            rec("E2E-06", "退出登录", False, f"异常:{repr(e)[:90]}")

    b.close()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\n结果已存:", OUT)
