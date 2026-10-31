# 接口自动化测试（pytest + requests）

测试 Flarum 论坛 REST API 的自动化回归套件。

> 本公开版把站点地址与账号改为环境变量，默认指向本地 Flarum（`http://localhost:8080`）。
> 原项目在一个公开练习论坛上完成；仓库不提供该站点地址或账号。请勿把脚本指向未授权站点。
> 写接口与限流用例只应在自己部署或已获授权的测试环境运行。

## 运行方式

```bash
cd 接口自动化
python -m pytest --no-header -q        # 全部用例
python -m pytest -m "not write" -q     # 只读接口（不受限流影响）
python -m pytest -m "write" -q         # 写操作接口（受限流影响）

# 按模块筛选（模块 marker 与 write/slow 可叠加使用）
python -m pytest -m auth -q            # 认证鉴权
python -m pytest -m post -q            # 帖子
python -m pytest -m comment -q         # 评论
python -m pytest -m search -q          # 搜索
python -m pytest -m permission -q      # 权限
```

## Allure 报告

`pytest.ini` 的 `addopts` 已内置 `--alluredir=./allure-results --clean-alluredir`，
**每次执行 pytest 都会自动重新生成结果数据**，无需额外加参数。

```bash
python -m pytest -q          # 执行用例，同时产出 allure-results/
allure serve allure-results  # 启动本地服务并自动打开浏览器查看报告
```

（`allure` 是独立的命令行工具，需另行安装：下载 Allure Commandline 解压后把 `bin` 加入 PATH，
并确保本机有 Java。仅查看报告需要它，跑用例不需要。）

### 报告内容约定

| 装饰器 | 用途 |
|---|---|
| `@allure.feature("模块名")` | 报告 Behaviors 视图的一级分组，共 4 个：认证鉴权 / 帖子与评论 / 搜索 / 权限控制 |
| `@allure.story("子功能")` | 二级分组，如「登录成功」「发帖校验」「中文关键词搜索」 |
| `@allure.title("中文用例标题")` | 替代函数名显示在报告里的中文标题 |
| `with allure.step("步骤描述")` | 把请求与断言拆成可读步骤，报告里可逐层展开 |
| `@allure.description(...)` | 已知缺陷用例标注**缺陷编号 + 现象 + 预期/实际** |
| `@allure.severity(P0–P3)` | 严重程度，对齐《01_测试计划》§8 缺陷等级定义 |

### severity 与项目 P0–P3 等级的对齐

severity 取值不直接写 Allure 原生枚举，而是用 `conftest.py` 中定义的 `P0`–`P3`
常量（唯一出处，改口径只改一处）：

| 项目等级 | 定义（测试计划 §8） | Allure 等级 | 常量 |
|---|---|---|---|
| **P0 致命** | 系统崩溃、核心功能完全不可用、数据丢失 | `BLOCKER` | `P0` |
| **P1 严重** | 核心功能异常、安全风险、无绕过方式 | `CRITICAL` | `P1` |
| **P2 一般** | 非核心功能异常、有绕过方式、体验问题 | `NORMAL` | `P2` |
| **P3 轻微** | UI 样式、文案、兼容性小问题 | `MINOR` | `P3` |

> ⚠️ **口径说明（勿误读）**：severity 标的是「**该用例失败时**，对应缺陷按项目口径
> 应判定的等级」，**不是**「当前已发现的缺陷等级」。《测试计划》§8 实例列记录本次
> **P0 未发现**——因此报告中出现 `blocker` 标签**不代表存在 P0 缺陷**，只表示该用例
> 一旦失败即为致命级（如 `test_login_success`：登录不可用 = 核心功能完全不可用）。
> 已确认缺陷的等级只看 xfail 用例：BUG-001 / BUG-002 = P1，BUG-003 = P2。

当前 26 条用例的 severity 分布：**P0 ×3 / P1 ×15 / P2 ×6 / P3 ×2**。

判定依据（按测试计划 §8 定义逐条判）：

- **P0**：登录、发帖、评论 —— 论坛三条主链路，失败即核心功能完全不可用
- **P1**：认证/授权绕过类安全用例、核心浏览（列表/详情/标签/评论列表/搜索）、
  越权删除，以及 3 条已定级 P1 的缺陷回归
- **P2**：非核心功能（通知/个人资料/改昵称）、输入校验（空标题/无标签）、BUG-003 回归
- **P3**：边界与错误处理（不存在的 id、无结果搜索）

### 失败用例自动附带请求详情

用例失败时，**本次用例发出的每一个请求**都会自动附加 4 项内容到报告：
请求 URL、请求参数、响应状态码、响应体（见 `conftest.py` 的 `attach_response` /
`_attach_http_log_on_failure`）。

- 走 `client` / `write_client` 会话的请求由 `requests` 的 response hook 自动登记；
- 裸 `requests.post/get` 的调用需套一层 `record(...)`（`conftest.py` 已导出），否则不会被登记。
- **只在失败时附加**：断言 4xx 的用例（401/403/404/422）属预期结果，若不加区分地附加，
  报告会被预期内的错误响应淹没。

## 核心步骤日志（0~4）

每个用例按 0~4 编号输出核心步骤日志，控制台实时打印、同时落盘到 `logs/`。

| 编号 | 内容 | 由谁在何时打印 |
|---|---|---|
| **0. 测试用例的描述信息** | 用例 id / 模块 / 场景 / 标题 | `_log_case_desc`（autouse fixture），用例开始时 |
| **1. 数据解析信息** | 请求方式 / 请求 URL / 请求头 / 请求参数或请求体 | `record()` → `log_http()`，**每个 HTTP 请求**各一条 |
| **2. 请求发送情况** | 响应状态码 / 耗时 / 响应体长度 / 响应内容 | 同上，紧跟在 1 之后 |
| **3. 断言情况** | 通过 / 失败 / 预期失败(XFAIL) / 意外通过(XPASS) / 跳过 | `pytest_runtest_makereport`，用例结束时汇总一条 |
| **4. 提取有关信息** | 从响应中取出、供后续复用的变量（接口关联） | `log_extract()`，在**真正做提取的那一行** |

### 输出位置：控制台只给标题，完整步骤进文件

**控制台**每跑一条用例只输出**一行**（「0.测试用例的描述信息」）+ pytest 自己的状态行：

```
test_search.py::test_search_chinese 
02:41:22 [INFO] 0.用例id:test_search.py::test_search_chinese 模块:搜索 场景:中文关键词搜索 标题:搜索-中文关键词『接口』应命中帖子但返回 0 条
XFAIL (BUG-001: 中文搜索失效——『接口』应有结果但返回0条（已知缺陷）)   [ 65%]
```

1~4 步**只进 `logs/` 下的日志文件**，一条不少：

```
02:41:22 [INFO] 0.用例id:test_search.py::test_search_chinese 模块:搜索 场景:中文关键词搜索 标题:搜索-中文关键词『接口』应命中帖子但返回 0 条
02:41:22 [INFO] 1.数据解析信息: 请求方式:GET 请求URL:https://.../api/discussions 请求头:{...} 请求参数:filter[q]=接口&page[limit]=10
02:41:22 [INFO] 2.请求发送情况: 响应状态码:200 耗时:0.08s 响应体长度:134 响应内容:{"links":{...},"data":[]}
02:41:22 [WARNING] 3.断言情况: 预期失败(XFAIL) —— 成功复现已知缺陷: BUG-001: 中文搜索失效…
```

- **控制台为什么只给标题**：一个用例会产出 6 条以上日志，1/2 还带着完整请求头与响应体，
  直接铺在终端上会把进度输出冲得没法看。跑的时候真正要一眼扫到的是「正在跑哪条用例」。
  实现见 `conftest.py` 的 `_ConsoleOnlyCaseTitle` 滤网（挂在 pytest 的 `log_cli` 处理器上）
  + `pytest.ini` 的 `--show-capture=no`（压掉报告末尾重复一遍的 Captured log 段落）。
- **`log_cli` 必须开**：pytest 默认会把日志**捕获**起来、只在用例失败时显示，
  不打开 `log_cli` 就一条都看不到（这正是"加了日志却没输出"的常见原因）。
- **日志文件**：每次执行在 `logs/` 下新建一个 `api_run_<年月日_时分秒>.log`（UTF-8），
  与 `allure-results/` 一样属运行时产物，已在 `.gitignore` 内。
  文件头会记录本次的被测站点、账号与日志路径，便于多轮执行后回溯。
- **失败细节在哪看**：控制台的失败回溯不受影响（`--show-capture=no` 只删 captured 段落）；
  再要看请求明细就翻日志文件或 Allure 报告。想临时恢复控制台全量输出，
  去掉 `pytest.ini` 里的 `--show-capture=no` 并注释掉 `pytest_sessionstart` 里的 `addFilter` 即可。

### 三点口径提醒

1. **编号不保证严格递增**。一个用例发多个请求时，1/2 会成对重复出现；「4.提取」
   打印在**真正提取的位置**，可能排在「3.断言」之前（例如先提取 id、再发下一个请求）。
   编号标的是"步骤类型"，不是"第几条日志"。
2. **口令一律脱敏**。请求头里的 `Authorization` / `Cookie`，以及请求体、响应体里的
   `password` / `token` 字段，落盘时都替换成 `***（已脱敏）`——
   登录响应体里就带着会话 token，只脱敏请求头是不够的。
   `log_extract(..., sensitive=True)` 用于提取处的同类脱敏。
3. **「3.断言情况」的预期失败是自己判的**。该日志在 `trylast` 的 hook 里打印，
   拿到的报告是 pytest 把 `xfail` 转换成 `skipped` **之前**的原始报告，
   `rep.wasxfail` 此时为空，必须按 `@pytest.mark.xfail` 标记 +
   `pytest.xfail.Exception` 自行判定；否则 7 条 xfail 会被日志误报成 7 个"失败"。

### 用例侧如何配合

只有「4.提取有关信息」需要在用例里显式调用（其余四步全自动、26 条用例零改动）：

```python
from conftest import log_extract

did = log_extract("discussion_id", r.json()["data"][0]["id"])
```

## 用例统计

- 共 26 条用例：读接口 20 条 + 写接口 6 条
- 运行结果示例：`19 passed, 7 xfailed`
  - **19 passed**：读接口 + 正常发帖 + 权限回归
  - **7 xfailed**（全部为已知缺陷或受限流影响，见下）——拆分为 **4 条显式 `@pytest.mark.xfail`**
    （BUG-001 ×2 / BUG-002 ×1 / BUG-003 ×1）+ **3 条运行时 `pytest.xfail`**（写接口被限流窗口阻断）

## 公共 fixture（conftest.py）

| fixture | 作用 |
|---|---|
| `auth` | 会话级登录**一次**，返回 `{"token", "user_id"}`，并完成鉴权自检 |
| `user_id` | 从 `auth` 派生；由登录响应**自举**，用例里不硬编码账号 id |
| `client` / `write_client` | 带 Token 的 `requests.Session`（读 / 写，后者含 `Content-Type`） |
| `rand_suffix` | 随机后缀，避免发帖标题冲突 |

> marker 声明只在 `pytest.ini`（唯一出处）；控制台 UTF-8 输出只在 `conftest.py` 设置一次
> （pytest 保证 conftest 先于任何用例模块被导入）。

**鉴权自检**：`auth` 在登录后会立即请求一次受保护接口 `/api/notifications`，非 200 则
`pytest.exit` **终止整个会话**。原因是 Flarum 的认证头必须是 `Authorization: Token <token>`
（不是 `Bearer`）——一旦写错，Flarum 会当作未登录，而此时**读接口照样返回数据**，
极易被误判成"功能正常"，直到写接口报 `400 csrf_token_mismatch` 才暴露。自检让这类问题
在第一个用例前就暴露。

## 已知缺陷（xfail 标记）

| 缺陷 | 用例 | 说明 |
|---|---|---|
| BUG-001 中文搜索失效 | `test_search_chinese` `test_search_chinese2` | 搜『接口』『测试』返回 0 条，数字/英文正常 |
| BUG-002 登录无限流 | `test_login_rate_limit_missing` | 连续 10 次错误密码不触发 429 |
| BUG-003 发帖限流过严 | `test_rate_limit_too_strict` | 第 2 帖即 429 |
| BUG-003 影响边界用例 | `test_create_post_comment` `test_create_discussion_blank_title` `test_create_discussion_no_tag` | 写接口在限流窗口内被 429 阻断，标记 xfail |

> 说明：`xfail_strict = true`，用例**实际失败**且标记 xfail 才通过——确保缺陷被真实复现，而非跳过。

## 写接口限流策略

Flarum 发帖限流极严（第 2 帖即 429，见 BUG-003）。因此：
- 写接口用例需**单独运行**，且各用例之间留出限流窗口（建议 >2 分钟）
- 正常发帖用例独立验证（第 1 帖成功即可证明发帖功能可用）
- 边界校验用例（空标题/无标签 422）在**限流窗口外**运行可验证通过：
  ```bash
  # 等待数分钟后单独跑单个边界用例
  python -m pytest test_discussions.py::test_create_discussion_blank_title -q
  ```

## 数据清理

自动化运行会产生两类测试帖与一类测试评论，`cleanup_api_test.py` 覆盖的关键词如下：

| 类型 | 关键词 | 产生自 |
|---|---|---|
| 测试帖 | `【自动化】接口发帖` | `test_create_discussion` |
| 测试帖 | `限流回归` | `test_rate_limit_too_strict` 的第 1 帖（该用例**单独运行**时第 1 帖会发成功） |
| 测试评论 | `pytest 自动化评论` | `test_create_post_comment`（评论无标题，只能按正文扫 `/api/posts`） |

运行后用 `cleanup_api_test.py` 回收（默认试运行，`--apply` 才真删）：

```bash
python cleanup_api_test.py            # 试运行：只列出将被清理的内容
python cleanup_api_test.py --apply    # 实际执行软删除
```

脚本只处理**作者为测试账号**且命中测试关键词的内容，不会碰他人内容；已在早前隐藏过的条目会自动跳过，
并落盘 `清理结果_API.json` 供复核。软删除后其他用户不可见（Flarum 的既有设计）。

## 环境变量

以下变量可覆盖默认配置。`conftest.py` 与 `cleanup_api_test.py` **共用同一组变量**，
可一并指向自己的 Flarum 实例：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `FORUM_BASE` | `http://localhost:8080` | 被测实例地址；非本地地址还需设置下一项 |
| `FORUM_USER` | `testuser` | 普通用户测试账号 |
| `FORUM_PWD` | 空 | 账号口令；运行前必须设置 |
| `FORUM_ALLOW_REMOTE_TESTS` | 未设置 | 仅当 `FORUM_BASE` 不是本地地址且已获授权时设为 `1` |

> 默认只允许本地地址，防止脚本被误指向未授权站点。登录限流用例会向配置账号连续发送
> 10 次错误口令；该用例只针对自己的测试账号，在远程环境运行前请确认已获得授权。

