# JMeter 性能测试

测试 Flarum 论坛读接口性能。**不压写接口**——发帖接口限流极严（第2帖即429，BUG-003），写接口压测会触发限流而非测出真实性能。

## 测试场景

| 场景 | 接口 | 说明 |
|---|---|---|
| 登录（每线程仅一次） | POST /api/token | 取 Token，后续循环复用 |
| 浏览首页 | GET /api/discussions | 帖子列表（首页主链路） |
| 浏览帖详情 | GET /api/discussions/${__P(discussion_id,1)} | 进入单个帖子 |
| 搜索 | GET /api/discussions?filter[q]=${__P(keyword,123)} | 关键词搜索 |
| 标签页 | GET /api/tags | 板块标签 |

## 测试配置

- **并发用户**：5 / 10 / 20（3档）
- **循环次数**：50次（每用户）
- **Think Time**：无（最坏情况，测峰值吞吐）
- **Ramp-up**：5秒（`-Jrampup` 可覆盖）

## 脚本结构

```
TestPlan
└── ThreadGroup（${__P(users,10)} 线程 × ${__P(loops,50)} 循环，ramp-up ${__P(rampup,5)}s）
    ├── HTTP请求默认值              protocol/domain 只声明一次
    ├── OnceOnlyController          1-登录获取Token（每线程仅一次，不在循环内）
    ├── SimpleController            读接口（共用Token头）
    │   ├── HeaderManager           Authorization: Token ${TOKEN} / Accept
    │   └── 2~5 四个读接口           各带「响应码=200」+「JSON含 $.data」两条断言
    └── 聚合报告
```

### 设计要点（面试可展开）

- **登录用 Once Only Controller 包裹**：10 用户 × 50 循环若每轮都登录，会打出 500 次登录请求，
  把"读接口性能"混成"登录+读接口"，且每轮重新取 Token 也浪费时间。现在每线程只登录一次。
- **公共 Token 头的作用域**：Token 头**不能**放在 ThreadGroup 层——ThreadGroup 级的配置元件对该组内
  **所有**采样器生效，登录会被带上空的 `Authorization: Token `，可能被认证中间件直接拒掉。
  故用 SimpleController 把 4 个读接口圈起来，Token 头只在其作用域内声明。
  **已实测验证**：同一个受保护接口 `/api/notifications` 放在作用域内返回 200（带 Token）、
  放在作用域外返回 401（无 Token）。
- **补响应断言**：每个请求都断言「响应码 = 200」，4 个读接口额外断言 JSON 含 `$.data`、
  登录额外断言含 `$.token`。作用是拦住"HTTP 200 但内容是 HTML 错误页"这类假成功。
  > 注：JMeter 对「响应码 ≥ 400」本来就会记为失败（已实测：不打任何断言时 404 也被记为
  > `success=false`），所以断言补的是"200 但内容不对"这一段，不是"错误率为 0 靠不靠得住"。
- **不加 Think Time**：本工程测的是**峰值吞吐**（最坏情况）。加 1~3s 思考时间会让 TPS 从 ~15 掉到 <1，
  且与已交付数据不可比。若要模拟真实用户行为，应另造一份带 Timer 的计划，而不是改这一份。
- **详情靶点与搜索关键词可参数化**：默认 `/api/discussions/1`、关键词 `123`，
  跨并发档位保持一致；换实例时用 `-Jdiscussion_id` / `-Jkeyword` 指定。
  默认值只是本地演示值，不保证在任意实例存在。

## 运行方式

```bash
# 先 cd 到本工程目录（jmx 与输出文件均以此处为基准）
cd 03_接口测试/JMeter工程

# 非GUI模式运行（示例：10并发，ramp-up 5s）
# 必须显式指定 domain / user / pwd；protocol 默认 http，HTTPS 实例用 -Jprotocol=https
jmeter -n -t forum_load_test.jmx \
  -Jdomain=localhost -Jprotocol=http -Juser=testuser -Jpwd='your-password' \
  -Jdiscussion_id=1 -Jkeyword=123 \
  -Jusers=10 -Jloops=50 -Jrampup=5 -l results_10.jtl

# 跑完直接生成 HTML Dashboard 报告（输出目录需不存在或为空）
jmeter -n -t forum_load_test.jmx \
  -Jdomain=localhost -Jprotocol=http -Juser=testuser -Jpwd='your-password' \
  -Jdiscussion_id=1 -Jkeyword=123 \
  -Jusers=10 -Jloops=50 -Jrampup=5 -l results_10.jtl -e -o report_10

# 已有 jtl 可事后生成报告（本仓库不提交 jtl / report，需本地运行后生成）
jmeter -g results_10.jtl -o report_10
```

> HTML 报告是自包含静态站点，**入口是各目录下的 `index.html`**，
> 双击即可用浏览器打开（响应时间曲线、TPS 曲线、错误率、各采样器统计）。
> 公开仓库只保留性能摘要，不提交 `results_*.jtl` 与 `report_*/`（原始数据与报告体积较大，
> 且可能包含运行环境信息）。

> `jmeter` 需已在 PATH 中（本工程用 5.6.3 验证）；若未配置，用其安装目录下 `bin/jmeter` 的绝对路径调用即可。
> 参数：`-Jdomain` 站点域名、`-Jprotocol` http/https、`-Juser` / `-Jpwd` 测试账号、
> `-Jdiscussion_id` 详情靶点、`-Jkeyword` 搜索词、`-Jusers` 并发数、`-Jloops` 每用户循环次数、
> `-Jrampup` 加压时间(秒)、`-Jresultfile` 结果文件名。
> **ramp-up 经验值 ≈ 线程数 / 2**（20 并发用 10s、50 并发用 25s），避免用户瞬间涌入打爆。

## 结果记录与复核

每次运行后把关键指标（平均/90%/95%响应时间、错误率、TPS）记录到 `性能结果.md`。
原始数据用 `analyze_jtl.py` 复核通过/失败与各采样器响应时间：

```bash
python analyze_jtl.py results_10.jtl
```

## 脚本版本与已交付数据的关系

`forum_load_test.jmx` 于 **2026-09-15** 按性能评审意见优化（登录移出循环、补响应断言、
公共配置抽为默认值+作用域内全局头、ramp-up 参数化）。
**`性能结果.md` 里的数据是优化前那版脚本在 2026-09-02 跑出来的，未重跑**
（原始 `.jtl` 与 `report_*/` 仅保留在本地，公开仓库不提交）——
两者的差异与影响见 `性能结果.md` 顶部说明。
