# 验证码问题调研与可落地方案

> 状态：调研 / 设计稿（2026-10-23，基于 v1.5.290 `bdce638`；P0 分支同基线）。
> 本文件不代表功能已实现；文中的接口、状态机、验收项是待评审的实施输入。
> 范围：携程、去哪儿、飞猪、同程、途牛；国内与国际。
> 硬边界：不实现自动验证码/滑块破解、第三方打码平台、指纹伪装或代理轮换规避；不伪造数据、进度或“无票”结论。
>
> 实施更新（2026-10-23）：P0 识别 + 收口已在隔离工作树 `D:\idea_project\ticket-monitoring-p0-v290`（分支 `p0-challenge-detection-v290`，基于 v1.5.290 `bdce638`）实现：
> - 共享识别器 `crawlers/challenge.py` + 六条 empty 误记路径修复；
> - 定时采集/探针共用 `CHANNEL_GATE`（全局 2）+ 每渠道锁；
> - 探针 retry 不再绕过 60s 冷却，挑战/登录渠道 900s 内过滤，登录完成清除；
> - 后端产出 `calendar_only` / `session_busy` / `parse_error`；
> - 登录窗口关窗检测 + Web 600s 超时；
> - P1 人工接管：探针任务内挑战票据卡、打开被挑战原页（同一持久档案）、人工完成后用同一会话核验、失败/跳过、通过后自动补采失败腿；
> - 38 项 P0/P1 单测；非浏览器全量 **3164 passed / 4 skipped**、`test_channel_ui_status` **16 passed**；1360/390 注入票据浏览器实测 open/window_open/passed 卡片、倒计时与操作按钮，零溢出、零 pageerror；**未提交、未发布**。
> 仍未做：官方 API、自动破解、第三方平台、完整 Playwright 套件。

## 0. 结论摘要

1. **验证码不是单点识别问题，而是会话信任问题。** 五个渠道的风控都在看浏览器档案、登录态、设备/IP、访问频率与行为，滑块只是信任不足时露出的一个面。单次把滑块“过掉”，并不等于该会话被平台信任；下一次请求仍可能继续挑战或静默降级。
2. **当前项目的主要阻塞是登录墙，不是滑块。** 2026-10-23 的运行日志里，途牛国内连续返回 `710114/needLogin`，去哪儿国际偶发 `1999/8` 未登录硬拒；近期没有滑块成功/失败记录。线上健康面同时显示途牛国内 `auth_reason=请登录`，多数其他渠道在 12:50–12:54 仍有明细取证（飞猪国际为 09:12）。
3. **可落地的路线是“官方 API/MCP + 持久会话 + 人工接管 + 诚实状态”，不是“自动破解”。**
   - 能走官方接口的渠道优先走官方接口（途牛 MCP、飞猪 FlyAI；携程商旅 / 去哪儿开放平台 / 同程商旅需合作资质）。
   - 只能走浏览器的渠道，用持久档案保持信任；被挑战时暂停该渠道，弹出**被挑战的原始页面**由人工完成验证，验证通过后只补采失败渠道/日期。
   - 无人值守时，被挑战的渠道必须如实显示 `blocked` / `login_required`，其余渠道结果保留；不能把验证页写成“无票”。
4. **预期效果要分层承诺。**
   - 人工在场：五渠道被挑战后都能恢复，恢复时间目标 < 3 分钟；这是本方案的主路径。
   - 无人值守：官方接口覆盖的渠道可稳定出数；没有官方接口又被挑战的渠道无法保证 5/5，只能低频重试并告警。
   - 途牛 MCP 官方配额为 **5 RPM / 50 RPD（所有 API Key 共享）**，只适合低频/重点航线，不能替代全量监控；飞猪 FlyAI 的配额以控制台为准。
5. **不建议继续投入反检测军备竞赛。** 现役代码里的 `AutomationControlled` / `navigator.webdriver` 处理属于历史遗留，不应扩展；代理轮换也不作为绕过限流的手段。是否移除由 owner 拍板，移除可能降低现有浏览器路径的成功率。
6. **并行审计发现必须先修的数据诚实缺陷（P0）。** 现有代码至少有 6 条路径会把验证页/登录墙落成 `empty`（§1.4）；定时采集单查询最多同时开 5 个渠道浏览器；探针“重试失败项”绕过冷却立即重跑被挑战渠道；`calendar_only`/`session_busy` 等状态后端不产出。它们会直接伪造“无票”，优先级高于接管理想化。

### 0.1 立刻可做（不依赖代码改动）

- **途牛国内**：在配置页「渠道登录」点途牛「弹窗登录」，用手机号/扫码完成登录；保存后复验 2027-01-29、01-30、02-14。原因：当前是 `710114/needLogin` 登录墙，不是滑块；影响：登录态恢复后国内明细可恢复，若随后仍被滑块挑战，再走人工接管，不要反复重开窗口。
- **其他四渠道**：当前有明细证据（见 §1.2），不要重复弹登录窗口，避免多窗口/IP 指纹叠加抬高风险。
- **不要**复制本机 Chrome 的 Cookie、不要自动过滑块、不要在挑战后连续重试；这些都会加重风控，且越过本方案的合规边界。

## 1. 现状证据

### 1.1 代码已经具备的能力

| 能力 | 现状 | 证据 |
|---|---|---|
| 逐路径状态账本 | PC/H5/API/日历每次尝试记录 path/status/rows/date/detail/ms | `crawlers/base.py:66`、`crawlers/base.py:74-92` |
| 统一浏览器档案 | 每渠道独立 `user_data/<plat>`，持久化 Chromium；登录窗口与采集共用档案 | `crawlers/base.py:113-125`、`crawlers/base.py:199-264` |
| 会话快照 | `storage_state()` 保存 cookies/localStorage/IndexedDB；重开时只补缺失 Cookie | `crawlers/base.py:250-264` |
| 登录窗口 | 有头窗口 + 桌面视口；用户点“我已登录完成”后保存会话 | `crawlers/base.py:419-464`、`webui.py:17377-17436` |
| 登录态判定 | 保存时间、采集拒绝、明细成功三类证据；区分渠道与国内/国际 scope | `webui.py:17273-17375`、`tests/test_channel_status.py` |
| 任务状态聚合 | `blocked -> challenge`、`login -> login_required`；有行但有失败路径记 `partial` | `webui.py:17887-17900` |
| 登录卡片 | 五渠道“弹窗登录/我已登录完成/等待采集验证”；失败与过期有文案 | `webui.py:11156-11215`、`webui.py:21660-21697` |
| 挑战识别（分散） | 携程 whaleguard/验证码；去哪儿**国际** code 7/8/9/10004（国内仅 1999）；飞猪 baxia/滑块（国内不检测登录）；同程验证码/登录；途牛滑块 DOM/710114 | 见 §2 各渠道 |
| 回归测试 | 认证状态不因空结果/旧失败/保存时间错乱而误判 | `tests/test_channel_status.py`、`tests/test_r338_login_state.py`、`tests/test_channel_ui_status.py` |

### 1.2 线上与日志证据（2026-10-23）

- `logs/monitor.log`：00:13–08:38 途牛国内多次 `需登录 · 渠道明确返回认证拒绝（710114/needLogin）`；00:59 去哪儿国际 `未登录硬拒（1999/8）`。
- 同一时段去哪儿仍有多次真实价格列表提取（05:07–08:37），说明“有历史明细/有会话”不等于“本次一定不被挑战”，也说明当前不是全渠道同时被滑块拦截。
- `GET /api/health`（12:52–12:54）：携程国际、去哪儿国内/国际、飞猪国内、同程（未分 scope）、途牛国际均有 `detail_at`；飞猪国际为 09:12:10；途牛国内 `auth_at=2026-10-23 12:26:36, auth_reason=请登录`。这是当前唯一明确的登录墙。
- 结论：**先修“登录墙的接管与恢复”，再谈滑块**；滑块检测仍需统一，但不是当前唯一瓶颈。

### 1.3 现有能力与缺口

| 环节 | 已有 | 缺口 |
|---|---|---|
| 识别 | 各爬虫各自用正则/错误码识别 | 正则分散、多数只在解析失败后看页面文本；缺少统一证据、置信度与 `slider/click/login/waf` 分类 |
| 记录 | `path_note` 记 blocked/login | 任务视图没有挑战票据；无法知道“哪个渠道/日期/阶段被挑战” |
| 人工处理 | 登录窗口打开渠道首页/登录页 | 不打开被挑战的具体 URL；用户完成登录后不会自动重试当前任务；窗口无超时/关闭检测，可能永久 active |
| 恢复 | 下一轮调度自然承接 | 没有“验证通过 → 只补采失败腿/日期 → 合并去重”的闭环 |
| 防触发 | 探针全局并发 2、部分渠道退避 | 定时采集无渠道闸门（单查询最多 5 个浏览器）；ctrip/fliggy/tongcheng 被 blocked 后仍继续；探针“重试失败项”绕过 60s 冷却 |
| 状态语义 | path 用 `login/blocked`，任务映射 `challenge/login_required` | `calendar_only`/`session_busy`/`parse_error` 后端不产出；仅日历的渠道状态仍是 `ok`；`SessionBusyError` 被吞成 `error` |
| 观测 | 渠道登录态、health 认证证据 | 没有挑战率、人工接管成功率、恢复耗时、补采产出 |
| 官方接口 | 无 | 途牛 MCP、飞猪 FlyAI 等官方能力未接入 |

### 1.4 必须优先修的“验证页落成 empty”路径（审计实证）

这些不是 UI 文案问题，而是数据诚实问题；P0 必须先修，否则后面的接管/补采都建立在错误的空结果上：

| 渠道/路径 | 现状 | 证据 |
|---|---|---|
| 去哪儿国内首次空结果 | 先写 `H5/API empty`，之后才置 `login_suspect`；首次风控页被记 empty | `crawlers/qunar.py:419-443`、`:342-361` |
| 去哪儿国际 `code 9` 强刷 | 只打日志；无行时落 `empty` | `crawlers/qunar.py:2002-2004`、`:2034-2039` |
| 途牛国内 `179991` | 只置内部 `blocked=True`，最终 path 写 `empty`（除非已有 login_suspect） | `crawlers/tuniu.py:492-493`、`:990-994` |
| 途牛国际 `needLogin`/token 门 | 返回 blocked，但 path 只写 `login if login_suspect else empty`，且国际不置 `login_suspect` | `crawlers/tuniu.py:656-660`、`:898-902` |
| 飞猪国内登录墙 | 无验证码关键词时只写 `empty`；国内不检测登录 | `crawlers/fliggy.py:200-207` |
| 携程国际日历登录墙 | 置了 `login_suspect`，但 path 写 `日历/empty`，探针只读 path 时判 empty | `crawlers/ctrip.py:733-751`、`webui.py:17884-17899` |

另有状态语义缺口：

- `calendar_only`、`session_busy`、`parse_error` 只出现在前端/统计字符串，后端 `_probe_result_status()` 不会返回；`SessionBusyError` 在探针里被通用 `except` 吞成 `error`（`webui.py:16342-16350`、`:18172-18178`、`crawlers/base.py:203-208`）。
- 仅日历成功的渠道，任务 channel 状态仍是 `ok`（有行、无坏 path），只靠 `cal` 计数和 UI“仅日历 N”区分（`webui.py:18146-18168`、`:16340-16342`）。建议显式落 `calendar_only`，避免上游把 `ok` 当明细成功。
- `path=login` 与类级 `login_suspect` 脱节：ctrip H5、tongcheng 国内、fliggy 全文件不置/不写类标记；UI 的 `stale` 只读类标记，可能出现“path 已判登录、卡片仍显示已有登录态”（`crawlers/ctrip.py:202-210`、`:361-380`、`crawlers/tongcheng.py:665-680`、`crawlers/fliggy.py`、`webui.py:17371`）。

## 2. 五渠道调研

> “实测/代码”指本项目代码或运行记录；“公开分析”指外部资料，未在本项目独立复验；“官方”指平台文档。表中的厂商名（whaleguard / baxia / 数美）来自代码特征、项目文档或公开技术分析；本项目只把它们当作“挑战形态线索”，不作为绕过依据，也未独立复验其全部版本行为。

| 渠道 | 挑战/登录形态 | 现有路径与证据 | 零/低验证码路径 | 方案建议 |
|---|---|---|---|---|
| 携程 | whaleguard 风控页；登录可能有滑块/点选；新档案更易触发 | `crawlers/ctrip.py:200-208`、`:365-375`、`:736`；`docs/INTL_DESIGN.md` 记录“whaleguard 只认 profile 信任度，新鲜 profile 国内同样 430” | 携程商旅开放平台（企业合作）；持久档案 + 登录态 | 持久档案为主；被挑战时原页人工接管；企业资质可接商旅 API |
| 去哪儿 | **国际 H5** JSON `code 7=滑块 / 8=跳登录 / 9=强刷 / bstatus.code 10004=点选`；`1999/2008` 未登录硬拒；**国内仅识别 1999**，7/8/9/10004 未检测 | `crawlers/qunar.py:1487`、`:1570-1600`、`:1994-1998`；`docs/INTL_DESIGN.md:99` | 去哪儿开放平台国内/国际商旅 API（需注册签约）；H5 登录态 | 优先官方 API；国内先补风险码检测；浏览器路径保持登录 + 退避；被挑战时原页接管 |
| 飞猪 | 阿里 baxia 滑块；匿名 headless 明细级 poller 必触发（历史记录）；登录走淘宝/支付宝 | `crawlers/fliggy.py:230`、`:661-662`；`docs/INTL_DESIGN.md:147` | **飞猪 FlyAI 官方开放平台**（机票搜索、直连官方价库；API Key/实名；配额以控制台为准）；商家开放平台偏订单/政策 | 优先 FlyAI；浏览器 SSR 列表为回退；被挑战时原页接管 |
| 同程 | 列表/登录页验证码；`passport` 跳转；数美滑块（公开技术分析）；国际列表明细需登录 + as-sdk | `crawlers/tongcheng.py:325-328`、`:421-428`、`:668-676`；`docs/INTL_DESIGN.md` 同程章节 | 同程商旅 MCP/Skills/CLI（企业）；日历 API 匿名但只有日历价 | 日历价只作低价信号；明细走登录会话 + 人工接管；企业资质走商旅 |
| 途牛 | 国内 `710114/needLogin` 登录墙、`179991` 风控（现未落 path）；滑块/人机验证 DOM；国际存在“受理不出数”软墙 | `crawlers/tuniu.py:418-435`、`:485-493`、`:953-954`；`docs/INTL_DESIGN.md` §2.4 | **途牛 MCP**：`flightMCP`（`searchLowestPriceFlight`、`multiCabinDetails`）、`intelFlightMCP`；官方限流 **5 RPM / 50 RPD，所有 Key 共享** | 国内登录优先；MCP 只用于重点航线/低频；国际软墙如实标 |

### 2.1 关键判断

- **登录态比滑块更重要。** 携程的新档案直接 430、去哪儿未登录 1999、途牛国内 710114、同程明细需登录，都说明“先有可信会话”是前提。
- **官方接口是唯一可规模化的零验证码路径。** 但途牛配额极低；飞猪配额需核实；携程/去哪儿/同程的商旅接口需要企业合作，不能当作短期个人方案。
- **日历价不是明细。** 同程/飞猪的日历通道不能用来宣称“航班明细成功”，也不能因为日历有价就把明细失败写成无票。

## 3. 为什么不做自动破解

- **风控看的是会话，不是单题答案。** 滑块/点选通过后，平台仍可能基于设备、IP、频率、账号历史继续挑战；自动过题不能建立长期信任。
- **合规与账号风险。** 平台用户协议/robots 对自动化访问有约束；第三方打码、轨迹合成、指纹伪装会把项目从“个人价格观察”推向对抗性采集，存在账号封禁与法律风险。
- **可靠性差。** 验证码厂商在持续升级，破解链路是长期军备竞赛；失败还会污染“空结果/无票”的语义。
- **数据诚实。** 本项目的既有原则是“宁缺勿错”。自动破解会把“没拿到”包装成“拿到了”，与项目目标冲突。
- **安全。** 第三方打码/破解脚本会接触登录态与浏览器环境，供应链风险高；Cookie/令牌不得进入日志或公开包。

因此：**开源滑块识别、ddddocr、打码平台、undetected 类指纹伪装、代理轮换，都不进入本方案。** 现役代码中的自动化标记处理只作为历史遗留记录，不扩展、不作为能力承诺；建议在后续合规清理时评估移除。

| 选项 | 能解决什么 | 主要问题 | 结论 |
|---|---|---|---|
| 官方 API/MCP | 从源头绕开网页验证码 | 配额/资质/口径差异 | **首选**（能接则接） |
| 持久会话 + 人工接管 | 在真实浏览器里恢复信任 | 需要 operator；不能无人值守 | **回退主路径** |
| 低频 + 缓存 + 退避 | 降低触发概率 | 降低时效/覆盖 | **必做** |
| 自动识别滑块/点选 | 可能过单题 | 不建立会话信任；易复发；ToS/法律风险 | 不做 |
| 第三方打码平台 | 把题交给外部 | 页面/令牌/隐私外流；供应链风险 | 不做 |
| 指纹伪装 / 代理轮换 | 短期躲识别 | 对抗升级、账号风险、合规风险 | 不做 |

## 4. 目标方案：Challenge Broker（验证挑战接管）

### 4.1 分层路由

按以下顺序为每个渠道选择路径，前一层成功就不进入下一层：

1. **官方 API/MCP**（若已配置且配额可用）：途牛 MCP、飞猪 FlyAI；企业资质下的携程商旅/去哪儿开放平台/同程商旅。
2. **可信持久会话**：已有登录态 + 持久档案 + 低并发；适用于携程、去哪儿 H5、同程、途牛国内、飞猪回退。
3. **缓存/历史数据**：只作为展示补位，标 `stale`，不冒充本轮明细。
4. **人工接管**：检测到挑战/登录墙时，打开被挑战的原始页面，由人工完成验证；验证通过后补采。
5. **诚实失败**：无人接管/超时/配额耗尽 → `blocked` / `login_required` / `quota_exhausted`，保留其他渠道结果。

### 4.2 检测契约

新增统一的 `ChallengeSignal`（建议放在 `crawlers/base.py` 或 `core/challenges.py`）：

```text
ChallengeSignal:
  plat, stage(list|detail|calendar|api), date
  kind: slider | click | login | waf | rate_limit | quota | unknown
  confidence: high | medium | low
  evidence: {http_status, url_path, api_code, dom_marker, text_marker}
  detected_at, retryable
```

检测顺序：

1. **业务错误码/HTTP**：Qunar `bstatus.code` / `code`（7/8/9/10004/1999/2008）、Tuniu `710114`、HTTP 401/403/412/429、跳转 passport/login、`whaleguard`/`baxia` 资源。
2. **DOM/iframe**：`[id*=captcha]`、`[class*=captcha|verify|slide|drag]`、`iframe[src*=verify|captcha]`、`#nc_1_wrapper`、baxia/geetest/数美等容器。
3. **页面文本**：`安全验证 / 人机验证 / 拖动滑块 / 请完成验证 / 访问验证`。
4. **空结果判定**：只有“响应成功 + 列表容器存在 + 无挑战标记 + 解析到 0 行”才是 `empty`；任何挑战标记存在时不得落 `empty`。

要求：

- 每个信号必须带**脱敏证据**：只存 URL path、HTTP 状态、业务码、命中的选择器/短文本；不存 Cookie、Header、完整 HTML、手机号。
- 解析前先过检测门；不能等解析失败后才看页面文本。
- 同一渠道同一阶段同时出现 `login` 与 `blocked` 时，按“登录优先”展示（用户可操作），但两者都保留在路径账本。
- `blocked` 与 `login_required` 永远不进 `empty` 计数，也不进“无票”文案。

**P0 修正清单（对应 §1.4）**：

- 去哪儿国内：在首次空结果前解析 `bstatus.code`/`code` 的 7/8/9/10004/1999/2008，命中即 `blocked/login`，不得先写 `empty`。
- 去哪儿国际 `code 9`：落 `blocked`（强刷）而不是 `empty`；`refresh` 可重试一次，但要计入退避。
- 途牛国内 `179991`：必须写入 path `blocked`；不得只置内部布尔后继续重试并最终写 `empty`。
- 途牛国际 `needLogin`/token 门：写入 `login/blocked` 并置会话拒绝证据；不得因“国际不置 login_suspect”而落 `empty`。
- 飞猪国内：补登录墙检测（URL/文本 `登录|扫码|passport`），登录页不得落 `empty`。
- 携程国际日历：登录墙时 path 必须落 `login`，不能落 `日历/empty`；任务聚合不得把它当 `empty`。
- `SessionBusyError` → 任务状态 `session_busy`（不是 `error`）；`calendar_only` 由后端显式产出；`parse_error` 与解析异常对齐，消灭“前端有词、后端不产”的死状态。
- 仅日历的渠道状态必须是 `calendar_only`，不能是 `ok`；`ok` 只用于“至少一条真实明细”。

### 4.3 会话信任

- **持久档案是默认**：每渠道固定 `user_data/<plat>`，不为每次任务新建上下文；登录窗口与采集共用同一档案。
- **桌面视口做验证**：沿用 `crawlers/base.py:419-420` 的结论——手机模拟下拖滑块经常失灵；登录/验证窗口统一桌面视口，Cookie 同域通用。
- **保存完整状态**：登录/验证成功后保存 `storage_state()`（cookies/localStorage/IndexedDB），更新 `last_verified_at`；但现役恢复只显式回注 cookies（`crawlers/base.py:159-186`），localStorage 依赖同一个 `user_data` 目录，目录丢失时不能只靠 `session-state.json` 恢复。档案存在不等于已登录，必须由采集结果验证（现有测试已守此语义）。
- **会话状态**：`unknown / saved / pending / available / login_required / challenge / expired`。状态由“最新认证证据 + 最新明细证据 + 保存时间”共同决定，不允许旧失败覆盖新保存，也不允许历史明细掩盖本次拒绝。**path 层的 `login/blocked` 也必须进入认证证据**，不能只读类级 `login_suspect`，否则会出现“路径已判登录、卡片仍显示可用”。
- **账号安全**：建议专用账号；不在配置、日志、票据里存密码/令牌；会话文件不进公开包（现有打包已排除 `user_data`）。
- **不要复制用户 Chrome 的 Cookie。** 新版 Chrome 有独占锁与 App-Bound Encryption，复制档案/ Cookie 会被拒绝（`docs/LESSONS.md` 已记录）；正确做法是让用户在持久档案里登录一次，或用可见窗口人工操作。
- **人工使用自己的浏览器只作为操作参考。** 本方案不把“接管用户本机浏览器”做成自动化能力；需要用户操作时，统一走持久档案的可见窗口，避免把人工操作变成新的规避链路。

### 4.4 人工接管状态机

```text
detected
  -> ticket_open        （任务暂停该渠道，其他渠道继续）
  -> window_open        （打开被挑战的原始 URL，持同一档案）
  -> verifying          （用户点“我已完成”或系统检测到挑战消失）
  -> passed             （验证请求成功；会话保存）
  -> resuming           （只补采失败渠道/日期）
  -> done               （合并去重，任务更新）
  失败分支：failed / expired / skipped -> cooldown -> 可重开
```

关键语义：

- **打开原始页面，不打开渠道首页。** 登录窗口当前只有去哪儿落到 passport 登录页（`crawlers/qunar.py:290`），其余渠道都打首页；这对挑战接管不够。必须保存被挑战的 URL/path，并在同一 profile 中打开该 URL。
- **成功判定以数据路径为准**：用户点“我已完成”后，后台用同一 profile 重新请求被挑战的列表/明细端点；挑战码消失、HTTP 200/业务成功才算通过。页面上的“验证成功”动画不能作为唯一证据。
- **验证成功但 0 行**：记为 `verified_empty`（会话已恢复、该日期确实无明细），不得写成“登录失败”，也不得写成“有票”。
- **超时/关窗**：挑战窗口默认 5 分钟，登录窗口默认 10 分钟；必须检测 `page.is_closed()`/上下文关闭，关窗或超时 → `expired`，该渠道冷却 15 分钟，不自动循环重开。现役 `_login_window()` 的 `while not done_evt.is_set()` 没有超时/关窗旁路（`crawlers/base.py:431-442`），用户直接关窗可能让会话卡片永久停在 active，P0 一并修。
- **并发**：一个渠道同时只允许一个验证窗口；窗口持 profile 锁，其他渠道继续跑；全局最多两个窗口，避免多窗口叠加触发更高风控。
- **跳过后**：`skipped` + 冷却；本轮不再请求该渠道，其他渠道结果保留。

### 4.5 恢复与补采

- 票据保存 `task_id / leg_index / plat / dates / stage / url / attempt`。
- 验证通过后创建**补采轮次**（linked `parent_task_id`），只重跑失败的渠道与日期；不修改原任务的条件快照，避免违反“提交快照不可变”的契约。
- 补采行按稳定 `rowKey` 去重后合并；已完成的渠道/日期不重复请求。
- 若补采仍被挑战：票据回到 `failed`，记录证据与冷却，不进入无限重试。
- 取消任务时保留已完成行；补采轮次同理。

### 4.6 调度与配额

- **浏览器路径**：每渠道并发 1，全局并发 2（沿用现闸门）；渠道内最小间隔 + 抖动；被挑战立即停该渠道并指数退避（15/60/180 分钟），成功一次即复位。
- **定时采集并入同一闸门**：现役定时采集在单个查询内 `ThreadPoolExecutor(max_workers=len(plats))`，最多同时 5 个渠道浏览器（`main.py:1868-1883`），是验证码叠加触发的直接来源；必须改为全局 2、每渠道 1，并把探针/定时/登录窗口一起纳入。
- **失败即熔断**：ctrip/fliggy/tongcheng 被 blocked 后不得继续换路径连打（当前仍会继续后续日期/补 PC/补日历）；tuniu `179991` 不得“标记 blocked 后继续按 max_attempts 重试并把退避加倍”；每渠道本轮最多一次替代路径。
- **重试不绕冷却**：探针“重试失败项”当前带 `retry:true` 绕过 60s 冷却并立即重跑所有 challenge/login/blocked 渠道（`webui.py:21777-21780`、`:16512-16523`）；必须按票据/渠道冷却放行，挑战渠道不在冷却内重开。
- **会话互斥要排队**：`SessionBusyError` 现在是立即失败并显示 `save_error`；应转为 `session_busy` + 短退避/排队，避免用户在采集占用时反复点登录。
- **官方接口**：独立 `QuotaManager`，按渠道/接口做 RPM/RPD 滑动窗口；配额耗尽返回 `quota_exhausted`，不回退成 `empty`。途牛按 5 RPM/50 RPD 规划，只用于重点航线；飞猪配额以控制台为准。
- **途牛配额算术**：1 条航线 × 14 天 ≈ 14 次/轮，2 条 ≈ 28，3 条 ≈ 42；50 RPD 只剩约 8 次给重试/舱位明细。因此 MCP 只能覆盖 1–2 条重点航线，不能承担全量 14 天带；全量仍需登录会话或人工按需查询。
- **优先级**：携程 > 去哪儿 > 飞猪 > 同程 > 途牛——人工接管窗口、官方配额、重试预算都按此顺序分配；价格仍按真实数据比较，不因优先级改价。
- **不做**：代理轮换、指纹随机化、并发堆量、挑战后立即重试。这些会加重风控且越过合规边界。
- **robots/ToS**：上线前逐渠道核对；H5 路径目前未被 robots 明确禁止（www.qunar.com 的 `/site/oneway_list.htm` 属已停服的 PC 路径），但 robots 不是授权，正式采集仍应走官方接口/合作。

### 4.7 官方 API/MCP 适配

| 适配器 | 能力 | 认证/配额 | 数据口径 | 备注 |
|---|---|---|---|---|
| `crawlers/tuniu_mcp.py` | `searchLowestPriceFlight`、`multiCabinDetails`；国际搜索/舱位 | API Key；5 RPM / 50 RPD 共享 | 需验收是否含航班号/时刻/舱位；只有最低价时标 `lowest_only`，不算明细 | 只用于重点航线/低频 |
| `crawlers/fliggy_flyai.py` | 机票搜索、官方价库 | API Key/实名；配额以控制台为准 | 需验收是否含航班明细；保留 `jumpUrl` 作为原页入口 | 优先于 baxia 浏览器路径 |
| 企业适配器（可选） | 携程商旅、去哪儿开放平台、同程商旅 | 企业签约/资质 | 以合同接口为准 | 不作为个人短期方案 |

适配器统一要求：

- 密钥只从本地配置/环境读取，UI 只显示掩码；不写日志、不进公开包。
- 结果标 `source="official_api"` / `"mcp"`；日历/最低价与明细分开，不混算。
- 配额耗尽、鉴权失败、接口变更分别落 `quota_exhausted` / `login_required` / `error`，不得静默切到浏览器或伪造空结果。
- **口径警示**：携程商旅、去哪儿商旅、同程商旅面向企业差旅，库存/价格口径与消费端不一定一致；必须标 `source`/`scope`，不能把商旅价冒充消费端最低价。官方接口只保证“来源真实”，不保证“与网页端同价”。

### 4.8 可观测性

新增指标（按渠道/路径/阶段）：

- `challenge_count`、`challenge_rate`（挑战次数 / 渠道请求轮次）
- `login_required_count`、`empty_verified_count`
- `takeover_opened`、`takeover_passed`、`takeover_failed`、`takeover_expired`
- `takeover_mttr`（检测 → 恢复）
- `resume_rows`（补采新增明细）、`resume_empty`
- `quota_used / quota_remaining`

告警：

- 同一渠道连续 2 次挑战/登录拒绝 → 降频并提示人工接管；
- 挑战率 > 5% 或恢复耗时 > 10 分钟 → 告警；
- 官方配额剩余 < 20% → 降级到重点航线；
- 任何“挑战被记为 empty”都是 P0 缺陷，测试和日志双门拦截。

### 4.9 UI 设计（验证票据）

**位置**：探针页“本次渠道产物”下方/右侧，新增“待人工处理 N”区；配置页“渠道登录”保留，但只负责会话，不承担挑战上下文。

**桌面线框**：

```text
待人工处理 2
┌──────────────────────────────────────────────────────────┐
│ [携程] 上海 → 北京 · 10-26 · 列表         需人工验证   │
│ 检测到安全验证 · 第 2 次尝试 · 已等待 00:42              │
│ 检测 ──●── 接管 ──○── 验证 ──○── 补采                    │
│ [打开验证窗口]  [跳过本渠道]        其他 4 个渠道继续中   │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│ [途牛] 上海 → 北京 · 10-27 · 列表         需登录         │
│ 原站返回 710114/needLogin · 历史明细不作为本次凭证        │
│ [打开登录窗口]  [本轮跳过]                               │
└──────────────────────────────────────────────────────────┘
```

**状态与文案**：

| 状态 | 主文案 | 动作 |
|---|---|---|
| `detected` | “携程要求人机验证；本轮已暂停该渠道，其他渠道继续。” | 打开验证窗口 / 跳过 |
| `window_open` | “验证窗口已打开。完成滑块后回到这里；系统会自动核验。” | 我已完成验证 |
| `verifying` | “正在用同一会话核验被挑战的列表…” | 禁用，显示真实耗时 |
| `passed` | “验证通过；正在补采 10-26 的失败渠道。” | 无 |
| `failed` | “仍未通过（仍检测到安全验证）；15 分钟后可重试。” | 重试（冷却后）/ 跳过 |
| `expired` | “验证窗口已超时关闭；本轮保留其他渠道结果。” | 重新打开 / 跳过 |
| `skipped` | “本轮已跳过携程；其余渠道结果不受影响。” | 撤销跳过（下轮） |
| `quota_exhausted` | “途牛官方接口今日配额已用完；未把配额耗尽写成无票。” | 查看配额 / 改用低频 |

**设计约束**：

- 不打断整个控制台：不弹全屏 modal；使用内联票据 + toast 回执。
- 不造假进度：四个步骤只按真实事件点亮；显示真实时间戳/计数；“补采”完成前不显示行数。
- 原生窗口不在网页内嵌：如实说明“窗口已在运行控制台的电脑上打开”；远程访问时显示“请在运行控制台的电脑完成”，并提供票据 ID。
- 移动端：不能打开桌面窗口，只显示状态与票据 ID；不提供假按钮。
- 可访问性：新增票据时焦点落到票据标题；状态变化用 `aria-live=polite`；状态不只靠颜色；按钮 ≥32px；尊重 `prefers-reduced-motion`。
- 视觉：沿用现有控制台 token 与渠道品牌图标；签名元素是四步“检测→接管→验证→补采”时间线，不再加装饰性渐变/插画。

### 4.10 接口与代码落点（建议）

| 落点 | 改动 |
|---|---|
| `crawlers/base.py` | `ChallengeSignal`、`classify_challenge()`、`open_challenge_window(url, plat)`、`verify_session(plat, probe_url)`；`path_note` 增加 `kind/evidence` |
| `crawlers/{ctrip,qunar,fliggy,tongcheng,tuniu}.py` | 用统一分类器替换分散正则；解析前检测；修复 §1.4 六条 empty 路径；记录挑战证据；删除/收敛重复的 `_last_blocked` |
| `webui.py` | `_State.challenge_tickets`；`/api/challenge/tickets`、`/api/challenge/open`、`/api/challenge/verify`、`/api/challenge/skip`；任务视图返回 `challenges`；补采轮次；`calendar_only/session_busy/parse_error` 状态落地；重试尊重冷却 |
| `main.py` | 定时采集并入全局 2/每渠道 1 闸门；被 blocked 后本轮熔断 |
| `core/health.py` | 挑战率、接管成功率、MTTR、配额指标；认证证据与挑战证据分开 |
| `crawlers/tuniu_mcp.py`、`crawlers/fliggy_flyai.py` | 官方适配器 + 配额门 + 数据口径标记 |
| `tests/test_challenge_classifier.py` | 五渠道挑战/登录/正常空页 fixture；§1.4 六条路径禁止 empty 误判 |
| `tests/test_probe_status_semantics.py` | `calendar_only/session_busy/parse_error` 后端产出与任务/leg 聚合 |
| `tests/test_challenge_resume.py` | 票据状态机、超时/关窗、跳过、补采只跑失败腿、去重、原任务快照不变 |
| `docs/uitest.py` | 票据各状态、真实时间线、移动端提示、焦点/aria、无假进度 |

## 5. 实施计划

| 阶段 | 内容 | 交付 | 估算 |
|---|---|---|---|
| P0 | 数据诚实与触发收口 | 6 条 empty 误记路径修复 + 统一检测/证据 + `calendar_only/session_busy/parse_error` 落地 + 定时采集全局闸门 2 + 探针重试尊重冷却 + 登录窗口超时/关窗 | 2–3 人日 |
| P1 | 票据与人工接管 | 票据 API/状态机 + 原 URL 窗口 + 核验 + 冷却 + UI 票据卡 | 2–3 人日 |
| P2 | 恢复与官方适配 | 补采轮次/去重 + 途牛 MCP + 飞猪 FlyAI + 配额门 | 3–5 人日 |
| P3 | 运营与商务 | 会话预热、指标/告警、携程/去哪儿/同程合作评估、runbook | 持续 |

总计 P0–P2 约 **2–2.5 人周**（不含官方合作审批与真实挑战复验）。P0 可以先单独上线，它直接消除“验证页被写成无票”的风险，不依赖任何 UI 改造。

## 6. 验收清单

- [ ] §1.4 的 6 条路径逐一有回归断言：去哪儿国内首次风控、去哪儿国际 code 9、途牛 179991、途牛国际 needLogin、飞猪国内登录墙、携程国际日历登录墙；**0 个挑战/登录被记为 empty**。
- [ ] 五渠道挑战页/登录页/正常空页 fixture 全部正确分类；Qunar 7/8/9/10004/1999/2008、Tuniu 710114、Ctrip whaleguard、Fliggy baxia、Tongcheng 验证码/登录均有独立断言。
- [ ] `calendar_only` 由后端显式产出且不再计作 `ok`；`SessionBusyError → session_busy`；不存在“前端有词、后端不产”的死状态。
- [ ] 定时采集与探针共用全局 2/每渠道 1 闸门；被 blocked 后本轮不再换路径连打；探针重试不在冷却内重开挑战渠道。
- [ ] 登录/挑战窗口关窗或超时都能结束 active，不出现永久“窗口打开”；`SessionBusyError` 不吞成 `error`。
- [ ] 票据状态机 `detected→window_open→verifying→passed/failed/expired/skipped` 全覆盖；超时不自动循环。
- [ ] 人工验证通过后，只补采失败渠道/日期；行按 `rowKey` 去重；原任务快照不被改写；取消保留已完成行。
- [ ] “验证通过但 0 行”记为 `verified_empty`，不写成登录失败/无票/有票。
- [ ] 官方适配器配额耗尽返回 `quota_exhausted`，不回退成 empty；密钥不出现在日志/HTML/公开包。
- [ ] UI：票据真实时间线、无假进度、移动端“请在运行控制台的电脑完成”、焦点/aria/32px 目标、1360/768/390 无溢出。
- [ ] 全量 pytest + uitest 通过；真实挑战只在自然出现时由人工复验，不主动触发。
- [ ] 代码中不新增自动破解、打码平台、指纹伪装、代理轮换；现有历史遗留项有明确处置结论。

## 7. 风险与待拍板

1. **人工在场是硬前提。** 没有 operator 时，被挑战渠道无法保证恢复；是否接受“官方接口覆盖 + 其他渠道 blocked”的无人值守 SLA？
2. **官方接口资质/配额。** 途牛 5 RPM/50 RPD 是否够用？飞猪 FlyAI 的实际配额/字段需登录控制台核验；携程/去哪儿/同程是否走企业合作？
3. **合规。** 各渠道用户协议/robots 对自动化访问的约束不同；正式采集应取得授权或走官方接口，不能以 robots 未禁止等同于授权。
4. **远程部署。** 原生验证窗口要求运行控制台的主机有桌面会话；若部署在无 GUI 服务器，需要 noVNC/Xvfb 或改为官方接口，二者都要额外的安全加固。
5. **检测漂移。** 验证码厂商会改 DOM/错误码；需要 fixture 回归与线上挑战率监控，不能一次写死。
6. **历史遗留的反检测处理。** 是否移除 `AutomationControlled`/webdriver 覆盖与代理“绕行”配置，需要 owner 决策；本方案不扩展它们。

## 8. 参考资料

- 项目内证据：`crawlers/base.py`、`crawlers/{ctrip,qunar,fliggy,tongcheng,tuniu}.py`、`webui.py`、`docs/LESSONS.md`、`docs/INTL_DESIGN.md`、`tests/test_channel_status.py`、`logs/monitor.log`。
- 途牛 MCP 文档：<https://open.tuniu.com/mcp/docs/>；`flightMCP`、`intelFlightMCP`、限流页 <https://open.tuniu.com/mcp/docs/guide/ratelimit.html>。
- 飞猪 FlyAI：<https://flyai.open.fliggy.com/>、<https://flyai.open.fliggy.com/docs/overview>。
- 去哪儿开放平台：<http://open.qunar.com/data/detail/open>。
- 携程商旅开发者平台：<https://openapi.ctripbiz.com/>。
- 同程商旅 MCP/Skills/CLI：<https://tmc.ly.com/zh/resources/updates/open-mcp-skills-cli>。
- Playwright 认证与持久上下文：<https://playwright.dev/docs/auth>、<https://playwright.dev/python/docs/api/class-browsercontext>。
- 携程验证码/风控公开资料：<https://sec.ctrip.com/doc/%E6%9D%A8%E5%86%8D%E4%B8%89-%E6%90%BA%E7%A8%8B%E4%B8%9A%E5%8A%A1%E5%AE%89%E5%85%A8%E9%98%B2%E8%8C%83%E4%B8%8E%E9%98%B2%E5%BE%A1%E6%9E%B6%E6%9E%84%E4%BD%93%E7%B3%BB%E5%BB%BA%E8%AE%BE.pdf>。
