# 采集策略控制面 · 架构审视与设计（r1063）

> 状态：**待你点头**。拍板记录见 §0；我自己的判断在 §12 单列，你可逐条否决。
> 轮次号从 r1063 起（当前最高 r1062）。
> 目标原话：「务必保证在每个渠道每个维度每个链路的数据爬取的过程中的，
> 主动/被动/自动化调整策略均在配置页面/渠道健康/节点干预等等中可以进行调整，
> 一切可配置，一切可视化，一切可干预，一切可调整，一切可开启，一切可中断，
> 一切可区分，一切可识别，一切可建议，一切可独立。」

## 0. 拍板记录（2026-11-06）

1. **路线 A：契约驱动 + 控制面**。但**不是打补丁，也不是另开一路**——
   要把此前几轮提过的相关设计要求一并融入，先做架构审视，再动代码。
2. **自动化默认按策略各自定**：量大且可逆的（降频、TTL、错峰、冷却）默认自动；
   不可逆或贵的（换身份、重登、弹验证窗、跳挑战、改设备参数）默认**只建议**，
   要人一键执行。
3. **承载面：直接重构「配置 › 渠道节流」分区**，不新增第 5 个导航项。
4. **（2026-11-06 追加）一切尽量热**：参数热配置、干预热生效、不靠重启。
   具体要求见 §8.1「热链路」——保存后下一轮即用；`PolicyEngine` 不许再拿启动时的
   config 快照（这也顺手解决 builder check 指出的「热重载到不了策略层」）。
   确属启动级的键（端口/路径/内核）单列并显式标「需重启」，不许混进热链路谎称生效。
5. **（2026-11-06 追加）维度/链路级一次到位**：原 B6 并入本目标，
   `main.py` 闸门、`ChannelBreaker` 键、`special_radar` 预算、10 个 crawler 的通路闸门
   全部在本次范围内，矩阵里链路粒度不再以「下一轮」搪塞。
6. **（2026-11-06 追加·目标扩句）十句变十四句**：新增「一切可清晰 / 一切可意图理解 /
   一切可统计 / 一切可观测」。落到可证伪的判据见 §4.1；`AXES` 由 10 条扩到 **15 条**
   （原 10 条 + 可可视化 / 可调整 / 可清晰 / 可意图理解 / 可统计，另保留语义清晰）。
7. **（2026-11-06 追加·界面铁律）必须遵守本项目既有的「微信级扁平化」体验**：
   白卡分组、无描边、无卡中卡、圆角 12~14px；文案中文短句（≤20 字）不许露裸 id；
   控件尺寸沿用既有节奏（按钮 ≥28px、chip 32px）；390/320 零横向溢出、零
   `pageerror`、半像素字号为 0。策略行与芯片不是新发明一套视觉，而是**长在既有
   `#paceBox` / `#panel-pacing` 的骨架里**（见 `webui.py` 的 r977 微信扁平段）。

## 1. 架构判断：为什么这一轮不能打补丁

今天这套东西把四件事混在同一层：

| 职责 | 现在住在哪 |
|---|---|
| 事实（发生了什么） | `core/yield_stats.py`、`core/riskscore.py::LoginLedger`、`core/pacing.py` 的熔断/令牌桶内部态、`core/health.py` 日志解析、干预台账（`core/storage.py`） |
| 参数（可以怎么调） | 一半在 `config.yaml` → `/api/config` 的 `glb` 扁平字典；**另一半硬编码在模块常量里** |
| 决策（这一轮怎么做） | `pacing.allow/trip/plan_query`、`policy.decide`、`crawlers/base.py` 里零散的 `if` |
| 暴露（能不能看见/关掉） | `/api/pacing`（只读 pacing 快照 + `advise()`）、配置页四个分区、健康卡 `paceBox` |

由此有三个**结构性**错位，补丁只会把它们固化：

**E1 参数没有一等身份。** 配置页的链路是「控件 id → `GLB.xxx` → `/api/config` 的
`glb` 字典 → 逐项手写钳制 → 写回 yaml」（见 `webui.py:36480-36900`）。而真正决定
「采不采/多快/要不要预热/换不换身份」的数值——`_PACE`、`_BLOCK_S`、`_STICKY_S`、
产量阈值 `0.40/0.90/8`、`_THRESHOLD`(80/65/45/25)、`LOGIN_BACKOFF`——**根本不在这条链上**，
它们是 `core/policy.py:67-82`、`core/riskscore.py:55-75` 里的常量。
所以「一切可配置」今天无法度量，也无法被门禁证伪。

**E2 粒度断在「渠道」。** 维度（`core/channels.py::DIMENSIONS` 7 个）与端面/链路
（`core/channel_links.py::SURFACES` pc/h5、API、App，以及产量账里的 path 名）
**已经是有名字的实体**，但参数模型里只有两个特例：`crawler.cadence[渠道]`、
`crawler.proxy_map[渠道]`。没有任何机制能表达「飞猪**国际 H5 日历**单独降频」。
所以「每个维度每个链路」「一切可独立」无处落地。

**E3 暴露面按「量」组织，不按「策略」组织。** 「渠道节流」只放 TTL/限速/熔断/
成功率保护/预热/节奏；身份、挑战、通路回退、预算、静默窗散在「全局参数」；
干预按钮只在健康卡；`/api/pacing` 只出 pacing 口径，**不含 `PolicyEngine` 的
`state/pace_factor/need_warmup/rotate`**（`webui.py:35582` 起只读 `_State.pacing`）。
所以用户在界面上看不到「这家渠道此刻的策略、为什么、哪一层说了算」。

结论：把 `core/policy.py` 文件头自己写的那句话反过来读——四个部件各自判会打架；
现在**界面层也在各自判**。正确做法是让「策略」成为一等公民，并给既有模块**归位**。

## 2. 目标架构：六层与依赖铁律

```
L5 门禁层    strategy_contract --strict · 行为等价 · 负控 · UI 几何门禁
                 ↑ 证伪
L4 暴露层    /api/strategy（目录+生效值+来源+矩阵） · 配置页「策略控制」
             健康卡「策略条」 · 干预台账写入
                 ↑ 只读 L1/L2，只写干预台账
L1 目录与参数  strategy_contract（策略目录）  strategy_params（三级继承+来源）
L2 决策层    policy.decide → ChannelPolicy + decisions[strategy_id]
L3 执行层    crawlers/base.py · app_base.py 只执行 L2，不再自判阈值
L0 事实层    yield_stats · LoginLedger · 熔断/令牌桶观测 · health 解析 · 干预台账
```

**依赖铁律**（写进模块 docstring，反向 import 即缺陷）：
`L0 ← L1 ← L2 ← L3`；`L4` 只读 `L1/L2` 并写台账；`L4` 不得被 `L2/L3` import；
`L1` 不得 import `crawlers`。

## 2.1 迁移不变量：策略化不许碰的既有铁律

`docs/YIELD_AND_SESSION_STRATEGY.md` 里已经用血的代价定下的规矩，
本轮**一条都不许因为「可配置」而放开**。下表是要写进门禁的硬约束：

| # | 铁律 | 出处 | 本设计怎么守 |
|---|---|---|---|
| I1 | 产量只能调速度，不能调开关（真无票/冷门航线会让成功率掉） | `YIELD…:130-134` | 产量族策略的 `scope` 只许 `speed`，不许暴露 `enabled`；矩阵里给它 `可开启=na` |
| I2 | 登录退避永不关闸：登录墙必须如实记 `login` 并继续跑 | `YIELD…:130-134` | 登录退避不是「可开可关」策略，只允许调阶梯与冷却；关闸只能靠人工 halt（入台账、有上限） |
| I3 | 抢不到自家锁（`SessionBusyError`）不计渠道失败 | `YIELD…:558-559` | 预算/锁族策略单独成条，审计里禁止进成功率分母 |
| I4 | 短时冷却归 `ChannelBreaker`（拿得到 `Retry-After`），长期姿态归策略层；两层都拦会过度降温 | `YIELD…:125-128` | 目录里把「熔断族」与「风险姿态族」分列，并在一处声明谁先谁后；`pause` 档仍只压速度 |
| I5 | `blocked` 在 pacing 里一律归 `captcha`（300s 冷却） | `YIELD…:749-751` | 分类映射作为「通路族」的一条策略，改动必须过门禁 |
| I6 | 任何 `sleep` 都要有累计上限；退避必须递增+清零+封顶 | `YIELD…:1592-1596`、`:2377-2394` | 冷却族参数的钳制上限写进 L1，配置页可填范围与后端钳制同源 |
| I7 | `android.fetch_budget_s` 必须 < 路由级 900s | `YIELD…:719-720` | 跨键约束在 L1 一处校验（`glbClamp` 先例），界面当场回写说明 |
| I8 | 我方主动不发必须记 `paced`，不许写成 `soft_reject`/`blocked` | `YIELD…:2178` | halt/暂停也只写 `paced` 类语义，不污染 blocked 统计 |
| I9 | 自动机制关掉后不得留下「等着它执行」的标记 | `SPEC:1624-1639` | 每策略的关闭动作必须同时清自己的 strikes/标记，并在策略行显示「已关闭·残留已清」 |
| I10 | 只有 `rows>0` 才算成功；`empty` 是无票结论、必须有无票证据 | `YIELD…:556-561`、`:3802-3803` | 事实层口径不动；策略条展示直接消费 L0，不另算百分比 |
| I11 | 并发不超 2，不许 5 家同秒齐发（重试风暴能把「限你」升级成「封你」） | `YIELD…:582`、`:4556` | 并发/错峰族参数的钳制上限写死，配置页给「为什么不能更高」的说明 |
| I12 | 配置纪律：一次只改一个，48h 后复测 | `YIELD…:569`、`:590-591` | 策略变更入台账时记「变更前后值 + 时刻」，为复测提供依据 |
| I13 | 读侧必须与写侧同一工厂（`default_ledger` / `user_data_root`），否则整块报表是瞎的 | `YIELD…:3434-3443`、`SPEC:1664` | `strategy_params` 与 `/api/strategy` 读 L1/L0 的既有工厂，不另开路径 |

**推论**：控制面能「开/关/停」的是**处置**，不是**记账**。任何一条策略被关掉，
它的观测与台账必须继续跑（`SPEC:825-831` 同样要求「关掉后账头写『已关闭』而不是『无』」）。

## 3. 归位表（谁进哪层、谁改造、谁降格、谁不动）

| 现有 | 归位 | 处置 |
|---|---|---|
| `core/pacing.py` | L1 参数 + L2 决策材料 | 保留「节奏域」职责：tier/stagger/令牌桶/`ChannelBreaker` 的算法不动，**取参数的来源**改为 L1；`advise()` 升级为 L4 建议生成器（按策略 id 出建议+动作码），不再自己拼中文 |
| `core/riskscore.py` | L0 台账 + L1 参数 + L2 打分 | `evaluate()` 的权重与阈值搬进 L1；`LoginLedger` 留在 L0；退避阶梯 `LOGIN_BACKOFF` 搬进 L1 |
| `core/policy.py` | L2 决策 | 常量搬走；`decide()` 增加 `decisions[{id,value,applied,source,why}]`；新增**人工停手最高优先级**（`halt` 覆盖状态机，见 §6） |
| `core/yield_stats.py` | L0 | 不改统计口径；「建议间隔」从账本里挪到 L4 建议器（账本只出事实） |
| `core/channel_contract.py` | L5 交叉引用 | **不动**。它管「渠道是不是一等公民」（10×11=0 缺口），本设计管「策略是不是一等公民」，两者交叉引用而不是合并 |
| `crawlers/base.py`、`app_base.py` | L3 | 保留既有的 policy gate 调用；把重复的阈值判断逐个核对后交给 L2（**行为必须逐位不变**，有等价门禁） |
| `webui.py` 配置页 `panel-pacing`「渠道节流」 | L4 | **重构**为「策略控制」：按族组织、触发类型 chip、粒度选择、生效值与来源、开关、立即停、建议+一键执行。分区 id 仍是 `pacing`（深链/门禁/`cfgGoThrottle()` 全部保留） |
| 健康卡 `#paceBox` | L4 | 新增「策略条」：每渠道一行 chips（熔断/限速/预热/身份/通路），每颗 chip 可开/关/停 + 建议；保留既有 `pace-row` 四列结构与 trace |
| `/api/pacing` | L4 | **保留**为兼容入口，内部改为「`/api/strategy` 的只读视图」，不新增第二套口径 |
| `crawler.policy_gate` | L1 | 从「一个总开关」变成「闸门」策略族的一员（默认全开），语义不变 |

## 4. 策略目录（`core/strategy_contract.py`）

一条策略的字段，以及**十轴各自的判据**（每一轴都必须能读真实登记点，
不许写第二份声明 —— 这是 `channel_contract` 已经验证过的做法）：

| 字段 | 含义 | 审计怎么核（读源码/真实读点） |
|---|---|---|
| `id` / `cn` | 可识别 | id 唯一；中文名出现在界面文案 |
| `family` | 族：节奏/熔断/风险/预热/身份/挑战/通路/预算/调度 | — |
| `trigger` | `proactive` 主动 / `reactive` 被动 / `auto` 自动化 | 决策点里确实存在对应分支 |
| `scope` | `global`/`channel`/`dimension`/`path` | 参数解析器真的支持该粒度覆盖 |
| `cfg` | config 键路径（真键） | 该键被**生产代码**读到 |
| `decide` | `module:func` | 函数存在且引用该键 |
| `api` | 干预路由列表 | `webui.py` 里有该路由 + 处理函数 |
| `ui` | 落点（分区 id / chip 选择器） | 源码里真有该控件 id |
| `advice` | 建议生成点 | 返回中文建议 + 动作码 |
| `auto_default` | 默认自动还是默认只建议 | 与 §0.2 的档位表一致 |
| `gate` | 门禁文件 | 文件存在且提到该 id |

十轴判据（对每条策略 × 每个渠道/维度/链路求值，取值 `y/n/na`+说明）：

`可配置`=cfg 被生产代码读；`可视化`=`/api/strategy` 有生效值+来源+状态，且 UI 有落点；
`可干预`=api 列表里有真实路由；`可调整`=支持 set；`可开启`=支持 enabled 开关；
`可中断`=有 halt/resume（或 cancel）；`可区分`=界面能区分自动/人工与「谁说了算」；
`可识别`=id+中文名+族；`可建议`=建议器返回动作码；`可独立`=支持渠道/维度/链路覆盖。

### 4.1 目标扩句后新增的五轴（每条都要可证伪，不许当形容词）

| 轴 | 中文 | 判据（读真实登记点） |
|---|---|---|
| `visualizable` | 可可视化 | 该策略在界面上**真有渲染落点**：`webui.py` 的渲染器对该 `data-strategy` 出节点，且 `uitest` 能点到它（渲染级证据，不接受「代码里有这行」） |
| `adjustable` | 可调整 | 该策略至少一个参数可在界面上改并回读：`/api/config` 的 `glb` 里有对应键、`GLB_RANGES` 有边界、保存后 `GET /api/strategy` 的 `value` 变化 |
| `clear` | 可清晰 | `/api/strategy` 每条策略返回 `label`：**≤20 字的中文短句**说清「它现在是什么状态」（例：`正常·按全局节奏`）；裸 id/英文/空 → `n` |
| `intent` | 可意图理解 | 每条策略返回 `intent`（一句话：它在防什么/图什么）与 `effect`（改了会发生什么），且两者在策略行的说明位真渲染；缺任一 → `n` |
| `stats` | 可统计 | 该策略在台账里可被计数：`intervention_success_rate` 或产量账能按 `strategy:<id>` 聚出「干预 N 次 / 生效 M 次 / 样本 K」，`/api/strategy` 返回 `stats`；无 → `n`（`na` 只允许「只建议、从不执行」类，且写明理由） |

`可观测` 与 `可可视化` 的区别写死在这里：**可可视化**是「界面上有这个位置」，
**可观测**是「这个位置上有带时间戳的实时读数」——两者不许互相顶替。


**首批登记 = 28 条**（确切 id 表见**附录 B**；此处按族归纳）。
不追求一次写满：Android 真机族（identity/tuning/bootprops/vendor/abi_canary）
与特价雷达族下一轮补。

- 调度族：扫描周期、随机扰动、静默窗（`scan_quiet_start/end`）、启动即扫、中断本轮
- 节奏族：快/慢 TTL、邻近比例/天数、错峰 seconds、渠道节奏 cadence、并发上限与平台锁
- 限速族：`min_gap_s`、`per_minute`、日期循环节流、单次预算（网页 900s / App 540s）
- 熔断族：开关、起步、封顶、登录墙冷却、硬风控冷却、解除（reset）
- 风险族：`riskscore` 阈值档、登录退避阶梯、换身份建议（**只建议**）、策略闸门
- 预热族：预热开关、预热渠道集、预热成功阈值
- 身份族：指纹一致性 stealth、拟人化开关/轮数、UA、移动 UA、TLS 指纹、代理（全局+每渠道）、会话最长天数、设备身份轮换（**只建议**）
- 挑战族：滑块自动档、每日上限、连败拉黑、单发、算数/文字验证码、OCR 放大、自动开窗、跳挑战
- 通路族：PC→H5→API 回退顺序（按渠道）、退役通路不再拖低健康度、单渠道停手

## 5. 参数模型：三级继承 + 来源，复用既有 `glb` 单通道

解析顺序（后者覆盖前者）：**代码内默认 → config 全局 → 渠道覆盖 → 维度/链路覆盖**。
产出 `{strategy_id, value, source}`，`source ∈ {default, global, channel, dimension, path}`，
界面直接标「生效值来自：渠道覆盖」。

```yaml
crawler:
  policy:                       # 常量搬家：默认值 = 今天的硬编码值，逐位相等
    pace: {healthy: 1.0, rehab: 1.5, watch: 1.5, degraded: 2.5, blocked: 3.0}
    block_s: {human: 3600, rotate: 3600}
    sticky_s: {watch: 1800, degraded: 3600, rehab: 1800}
    yield: {min_samples: 8, ok_low: 0.40, ok_high: 0.90}
  risk:
    levels: {watch: 25, slow: 45, pause: 65, human: 80}
    login_backoff_s: [0, 90, 300, 900, 1800, 3600, 7200]
  strategy_overrides:           # 粒度覆盖（平坦字符串键；覆盖字典的键是 Param.pid）
    "fliggy": {"pace_factor.watch": 1.2}
    "app_qunar": {"block_window.human": 1800}
    "tongcheng/intl/PC": {"rate_per_minute.value": 6}
    "fliggy/round_trip/日历": {"rate_min_gap.value": 8}
```

**粒度三段必须用真实 id，不许自造名字**：
段一 ∈ `core/channels.py` 的 10 家渠道；段二 ∈ `DIMENSIONS`
（`domestic/intl/calendar/detail/round_trip/multi_city/low_fare`）；
段三 ∈ `core/channels.py::PATH_CN` 的键（`PC`/`H5`/`H5/API`/`日历`/`往返`/`多程`/
`API`/`QUERY`/`TRIP`/`app-list`/`app-calendar` …，共 30+ 个真通路 id）。
**切分方式是「最多切两刀」**（`key.split("/", 2)`），因为通路 id 本身含 `/`
（`H5/API`）；`*` 只允许出现在段一。**未知任一段一律拒绝保存并报错**——
静默丢弃等于「配了不生效」（`SPEC:1664`）。覆盖字典的键是 `Param.pid`
（如 `rate_per_minute.value`），不是配置短键——T1/T2 已按此落地，写在 yaml 里
写错一个键名会在装载时抛 `ValueError`。
不是所有策略都支持三段：`scope` 字段声明的粒度之外记 `na`（例如熔断器按渠道记账，
链路段对它恒为 `na` 并写明理由），这是「可独立」的诚实边界，而不是缺口。

**不新开一路**的硬约束：读写仍然走 `/api/config` 的 `glb` 字典
（GET 直出顶层扁平值 + `cadence`/`proxy_map` 那样的结构化覆盖字典；
POST 在一处集中钳制后写回 yaml），页面保存 → 热重载 → 下一轮生效，与今天同一条路。
**只有「干预动作」（停/恢复/解除/中断）走接口，不走配置**——这是正确分层，不是分叉。

## 6. 暴露面

**(a) 配置 › 策略控制（重构 `panel-pacing`）**
按族分组；每行 = 中文名 + 触发类型 chip（主动/被动/自动）+ 粒度选择（全局/渠道/维度/链路）
+ 当前生效值 + 来源 + 开/关 + 「立即停 N 分钟」+ 建议（带一键执行）+ 该策略干预记录数。
沿用 r523 规矩：**任何一条都不允许只读展示**（能调就必须有控件）。

**(b) 健康卡「策略条」**
每渠道一行 chips（熔断/限速/预热/身份/通路 ∪ 当前生效中的策略），
每颗 chip：状态 + 单击开/关/停；右侧一句与 `advise()` 同源的建议；
点击跳配置页对应策略行（`cfgGoStrategy(id)`，与既有 `cfgGoThrottle()` 同构）。
`paceBox` 既有的 `pace-row` 四列与 trace 结构保留，策略条插在其后，
遵守 r977「两行节奏固定」的几何约束。

**(c) 接口（写路径只有一个，见 §7.3-Q8）**

- `GET  /api/strategy`：目录 + 生效值 + 来源 + 十轴矩阵（CLI 与 UI 同源，只读）
- **参数编辑一律走既有 `POST /api/config`**（`glb` 整表 + `strategy_overrides`），
  进配置页脏状态与 savebar，不与 `/api/config` 抢写 yaml
- `POST /api/strategy/halt` `{plat, minutes, note}` / `POST /api/strategy/resume`：
  **可中断**（运行期干预，不写配置；与 `/api/pacing/reset`「清零」语义分开）
- `POST /api/round/abort`：中断本轮扫描（探针侧已有 `/api/probe/cancel`）
- 干预/变更台账 `action` 三族：`auto_*`（系统自动）、`strategy_*`（策略参数变更与停手）、
  其余（人工动作）。**`strategy_*` 与 `auto_*` 都从「人工干预成效 / 干预成功率」
  里排除**，否则调一次参就把该渠道的前后对比与成功率冲掉（见 §7.3-Q4）

## 7. 历轮要求的承载（融入，不是并存）

**做法**：把 `docs/EXECUTION_SPEC_LATEST.md`、`docs/RATE_LIMIT_PLAYBOOK.md`、
`docs/HANDOFF_CAPABILITY_MATRIX.md`、`docs/HANDOFF_FULL_SESSION.md`、`HANDOFF.md`、
`docs/YIELD_AND_SESSION_STRATEGY.md` 里**此前提过的相关要求逐条挖出来**（共 86 条，
按 A–H 分组，全文见**附录 A**），逐条指到「哪一层 + 哪个判据 + 哪个门禁」。
本设计不新增要求口径，只宣布它们由谁承载。

### 7.1 八组要求 → 承载层

| 组 | 要求组名（条数） | 承载层 | 判据 / 门禁 |
|---|---|---|---|
| A | 配置页必须可配置、不许只读展示、范围校验、回读（13） | L1 参数 + L4 控件 | 十轴 `可配置`：cfg 键必须被生产代码读；`GLB_RANGES`/`GLB_RANGES_DYN` 登记；负控 |
| B | 热生效、不许假装生效、隐式夹取必须回写（10） | L1 + L4 | 策略行显示「实际生效值 + 来源」；启动级键单独标；`test_r1063_strategy_params` |
| C | 可视化：多维、来源、谁说了算、自动 vs 人工（15） | L4 | 策略条 chip 带「来源 / 自动处置生效中」；`/api/strategy` 出 `source` |
| D | 可干预：一键动作、可开可中断可恢复、幂等、在途可见（11） | L2 + L4 | `api` 字段必解析到真路由；halt/resume/abort；`test_r1063_strategy_interrupt` |
| E | 可建议：建议必须有真按钮、异常处就地给入口（7） | L4 建议器 | 十轴 `可建议`：建议返回动作码且 UI 真渲染按钮（`test_r905` 先例） |
| F | 独立性/粒度：按渠道、按域、按通路、按会话（10） | L1 三级继承 | 十轴 `可独立`；`strategy_overrides` 支持 `渠道/维度/链路` |
| G | 审计/溯源：变更与干预留痕、可回放、不污染分界（10） | L4 台账 | `strategy_*` 入账 + `auto_*` 分界；写失败必须上抛（`SPEC:1674`） |
| H | 单一声明源 / 不许编造 / 不许静默 / 真渲染证据（10） | L5 | `--strict` 矩阵 + 负控；禁止「代码里有这行」当作可见（`SPEC:2148`） |

### 7.2 七组旧要求的张力，本轮怎么裁

这七组是既有文档里就存在的矛盾，新的控制面必须给**唯一裁决**，否则实现时必然二选一各写一半。

| # | 张力 | 裁决 |
|---|---|---|
| C1 | 「只读说明」vs「不许有无法配置的项」 | 一律给编辑控件；**启动级键**在策略行显式标 `启动级·需重启`，保存后按 `RESTART.required` 提示（`HO:204`），绝不谎称已生效 |
| C2 | 干预幂等（在途禁用）vs 超时后入口要能再点（`SPEC:902-907`） | 在途**改文案 + 不禁用长动作按钮**（验证窗/探针），短动作（解除/预热）走幂等锁；两者都在策略行显示进行中状态 |
| C3 | 阈值可填任意值 vs 解析处必然钳制 | 保留钳制，但**当场回写并说明原因**（`glbClamp` 既有先例），策略行同时显示「你填的」与「实际生效」 |
| C4 | 演示态不露合成数 vs 两面板必须同数 | 沿用 `_maskSynth` 收窄；策略条在演示态显示「演示」而不显示合成百分比 |
| C5 | 渠道级必须同数 vs 通路级允许不同口径 | 渠道级单一口径；通路级各用各的，并在策略行附一句口径说明（`SPEC:361-384`） |
| C6 | 「唯一执行口径文件」vs 文件内 3000 行历轮台账 | 本设计**不新增台账文件**：设计与计划进 `docs/superpowers/`，执行口径仍只写 `EXECUTION_SPEC_LATEST.md` |
| C7 | 自动机制关掉要真停 vs 已有 strikes/标记仍在生效期 | 关闭动作同时清该策略自己的 strikes/标记（`r626` 先例），策略行显示「已关闭 · 残留已清」；观测与台账继续跑 |

## 7.3 Builder check：八个问题与本轮裁决

写完稿后另派了一个「不知情的实现者」做可计划性审查。它提了 8 个问题，
其中 7 个我按仓库证据当场裁决（下面每条都给依据），**只有 Q1 必须你定**
（它让工作量差一个数量级）。

| # | 问题 | 裁决 |
|---|---|---|
| Q1 | 维度/链路覆盖这一轮**真生效**还是只做解析与展示？ | ⚠ **待你定**（见末节）。事实背景：真正的闸门不在 `crawlers/*`，而在 `main.py` 的 `pac.plan_query(c.name, …)`（只拿 plat+航线+日期）与 `pac.observe(c.name, [...])`（把一次查询里所有失败通路**聚合成一次渠道级熔断**）；日历源走 `core/special_radar.py`，**完全不经过 Pacing**；`ChannelBreaker` 的键是 `plat`。所以「链路级真生效」= 改 `main.py` 闸门、把熔断键扩成 `(plat,path)`、给 `special_radar` 接预算、并在 `main.reload_config` 加 PolicyEngine 刷新钩子（现在只 `pac.refresh`，`PolicyEngine` 是 crawler 构造时的 config 快照，热重载到不了它）。 |
| Q2 | 三段键的取值域是哪套实体？`dimension` 与 `surface` 混了；非法键怎么办？ | 段一 = 10 家渠道；段二 = `channels.DIMENSIONS`（7 项）；段三 = `channels.PATH_CN` 的键——**端面不是独立一段**，因为 `PC`/`H5` 本身就是账本通路 id。`*` 只允许出现在段一。**未知任一段一律拒绝保存并标红**（不回退静默，避免重演 `cadence` 白名单「能填不生效」的坑，`webui.py:37087`）。不支持四段。 |
| Q3 | 「24 条」与 §4 枚举的 ~47 项对不上 | 定死 **28 条**，id 表见**附录 B**。合并规则：`fast/slow TTL` 合为 `ttl_tier`；`near_ratio/near_days` 合为 `near_window`；`UA / 移动 UA / TLS` 合为 `identity_headers`；`slider` 的 auto/single_shot 与 daily_cap/max_fails 拆成 `slider_attempt`、`slider_guard` 两条（语义不同：试不试 vs 试几次）。验收数字随之改为「10 家 × 28 条」。 |
| Q4 | `strategy_*` 入台账会顶掉 `intervention_effect` 的「最近一次人工干预」分界，并污染干预成功率 | 采用**第三类前缀**：`auto_*`（系统自动）/ `strategy_*`（策略变更与停手）/ 其余（人工动作）。`intervention_effect` 与 `intervention_success_rate` 的 SQL 分界同时排除 `substr(action,1,5)='auto_'` 与 `substr(action,1,9)='strategy_'`。`scope` 继续只用既有渠道/分域词表（**不用** `strategy:<id>`：`test_r654_every_scope_has_a_label` 用 `[a-z_]+` 扫 `scope` 字面量并要求 `_ivScope` 中文标签，冒号会被静默漏过）；策略 id 写 `note` 前缀 `[<id>]`，前端据此显示「策略变更」。新增门禁 `test_r1063_strategy_ledger_class.py`（含负控：把 `strategy_` 从排除里去掉 → 红）。 |
| Q5 | `halt` 存哪、优先级多高、会不会与 `policy_state.json` / `reset` 打架 | 独立文件 `user_data/<profile>/strategy_halt.json`，**不动** `policy_state.json` 结构（§8.3 仍成立）。`decide()` **最前**读 halt → `state="blocked"`、`allow=False`、`reasons=["人工停手 N 分钟：…"]`；到期自动失效（有上限，符合 I6 与「可中断但不可永久判死」）。`/api/pacing/reset` **不碰** halt，界面文案分别写清「解除自动熔断」与「恢复人工停手」。本轮 halt 只支持**渠道级**；维度/链路级停手在矩阵记 `na` 并写明「待 B6」。 |
| Q6 | 「换身份 / 重登」的一键执行本轮做不做？ | **不做**。§10 非目标已定「不动设备身份」（`SESSION_EXPERIENCE_GUIDE_2026-11-06.md` §4：改动会让阿里系与携程会话全失效）。身份族在矩阵里 `可干预=na`，理由写「只建议、不执行」；策略行给「建议换身份」+ 指向 `docs/DEVICE_IDENTITY_PLAYBOOK.md` 的链接，**不给假按钮**（撞反目标）。重登仍走既有 `srxGoLogin()`，不新增执行路由。 |
| Q7 | 数据驱动渲染下「删一个控件 → 报 n」的负控怎么成立？ | 三层判据：(a) 登记表 id 必须被**生产代码读**（静态：扫 `glb` 读点/参数解析器）；(b) 每条**数值型**策略必须在 `GLB_RANGES` 或 `GLB_RANGES_DYN` 有边界登记；(c) **渲染级**证据：`uitest` 断言 28 条策略行在页面上真的存在、可改、保存后回读（`SPEC:2148` 明确禁止「代码里有这行」当作可见）。负控两处：删后端读点 → 静态 audit 报 `n`；删渲染器 `data-strategy` 输出 → uitest 红。前端**不写 28 条字面量**：渲染器从 `GET /api/strategy` 目录驱动、模板统一输出 `data-strategy="<id>"`——既不写第二份声明，也保留可证伪。 |
| Q8 | 参数编辑走哪条写路径？（`/api/strategy/set` 与 `/api/strategy/toggle` （建议名·未实现，已取消，改走 /api/config）） 与整表 `POST /api/config` 会不会互相覆盖？ | **参数编辑只走既有 `POST /api/config`**（`glb` 整表 + `strategy_overrides`，进脏状态与 savebar，r649 的保存互斥继续有效）。`/api/strategy/*` 只做**运行期干预**（halt/resume）与只读。由此语义定死：**「开/关」= 配置（savebar，可回读）；「停/恢复」= 干预（即时，不写 yaml）**。取消原稿的 `/api/strategy/set`、`/api/strategy/toggle`。 |

> 上表提到的 `/api/strategy/set` 与 `/api/strategy/toggle` **均未按此名实现**：参数编辑统一走 `/api/config`，运行期干预走 `/api/strategy/halt`、`/api/strategy/resume`、`/api/round/abort`。

## 8. 行为等价与迁移（这一轮不许改行为）

### 8.1 热链路（你追加的硬要求）

现状事实：`main.reload_config()`（`main.py:3486`）已经在热更新 pacing（`_pac.refresh`）
与调度周期；但 **`PolicyEngine` 是爬虫构造时用 `self.config` 建的快照**
（`crawlers/base.py:1283`、`crawlers/app_base.py:636`），而 `crawler_cache`
（`main.py:1905`）只在 headless/proxy/android 变化时才清——**改策略参数到不了策略层**。

本设计的热链路（三条独立通路，都不重启）：

| 变更 | 生效路径 | 延迟 |
|---|---|---|
| 参数（任何 `crawler.policy.*` / `crawler.risk.*` / `strategy_overrides` / 既有节流键） | `POST /api/config` → `reload_config()` → **`strategy_params.set_config(cfg)`**（全局唯一提供者）→ 下一轮 `decide()`/`gate_path()` 直接读到新值 | 下一轮 |
| 停手/恢复（`halt`/`resume`） | 内存广播 + `strategy_halt.json` 落盘；`decide()` 每调用按 mtime 缓存读 → **立即**拦截下一次闸门判定 | 毫秒–秒 |
| 中断本轮（`/api/round/abort`） | 复用既有 `rt["_round_gen"]` 世代号：递增即让所有 worker 在下一个检查点让位 | 下一个检查点 |

**硬约束**：`strategy_params` 必须是**全局提供者**（模块级单例，`set_config` 可重入），
不许任何模块把参数抄进实例属性——否则又出现「改了没生效」的灰区（`SPEC:588`）。
`PolicyEngine` 保留 `refresh(cfg)` 仅为兼容，内部应直接委托给 `strategy_params`。

### 8.2 行为等价与迁移

1. **常量搬家逐位相等**：`_PACE/_BLOCK_S/_STICKY_S/0.40/0.90/8`、
   `_THRESHOLD/LOGIN_BACKOFF` 的默认值在新配置缺省时必须与今天字面相同；
   门禁 `test_r1063_policy_params_equivalent` 直接断言取值相等。
2. **旧键全部保留**：`pacing.DEFAULTS`、`crawler.breaker.*`、`crawler.rate.*`、
   `crawler.cadence`、`crawler.proxy_map` 的键名与钳制范围不变；新键缺省=旧值。
3. **状态文件兼容**：`user_data/<profile>/policy_state.json` 的 `state/until/at`
   结构不变，旧文件可直接读。
4. **前端深链不变**：`CFGPANEL='pacing'`、`cfgGoThrottle()`、`showMonTab('health')`
   全部保留；只改分区内的组织方式与文案。

## 9. 门禁（TDD，先红后绿）

- `tests/test_r1063_strategy_contract.py`：目录完整性 + 十轴矩阵无 `n`
  + **负控**（删一个控件 / 改一个 cfg 键名 → 必须报 `n`）。
- `tests/test_r1063_strategy_params.py`：三级继承、来源标注、渠道 A 覆盖 vs 渠道 B 未覆盖取值不同。
- `tests/test_r1063_policy_params_equivalent.py`：搬家前后取值逐位相等（行为不变硬证据）。
- `tests/test_r1063_strategy_interrupt.py`：halt 后 `decide().allow is False`，到期自动恢复；
  `auto_*` 不污染人工干预成功率。
- `tests/test_r1063_strategy_matrix_channels.py`（未创建：矩阵渠道展开已由 `tests/test_r1063_strategy_contract.py` 与 `tests/test_r1063_strategy_axes15.py` 覆盖）：10 家渠道 × **28 条**策略无 `n`
  （App 渠道结构与浏览器不同，允许 `na` 但必须写明理由）。
- `tests/test_r1063_strategy_ledger_class.py`：`strategy_*` 与 `auto_*` 两类都不进入
  「人工干预成效 / 干预成功率」；负控：从 SQL 分界里去掉 `strategy_` → 红。
- UI：`docs/uitest.py` 增补（新分区渲染、chip 点击、停/恢复即时反馈、
  390/320 无横向溢出、按钮 ≥28px、半像素字号 0）。

## 10. 非目标 / 反目标 / 风险

**非目标**：不做策略自学习或自动调参；不新增渠道/维度；不改推送与报表口径；
不动设备身份（`SESSION_EXPERIENCE_GUIDE_2026-11-06.md` §4 已判定「不要再动」）。

**反目标**（做到也不算成）：造第二份声明（目录与真实控件各写一份）；
为凑矩阵塞没人读的假控件；借搬家顺手「调优」数值（会让回归无法归因）；
把自动处置默认打开到「换身份/重登」这类不可逆动作。

**风险**：前端一次改动面大（配置分区 + 健康卡）→ 用批次 B5 单独收口，
先跑通既有几何门禁再加元素；`base.py` 去重阈值判断时有行为漂移风险 →
等价门禁 + 逐处核对，宁可保留旧分支也不猜。

## 11. 实施批次（每批可独立验收）

| 批 | 内容 | 验收 |
|---|---|---|
| B0 | 把 §7.2 的七条裁决写进 `EXECUTION_SPEC_LATEST.md`（只增小节，不改历史台账段），并在 §4 策略目录里逐条挂判据 | 七条裁决各有一句可执行口径 + 对应门禁 id |
| B1 | `core/strategy_contract.py` + 首批 24 条 + CLI 矩阵（**先不碰 UI**） | 矩阵出表、`--strict` 可用、负控有效 |
| B2 | `core/strategy_params.py` + policy/riskscore 常量搬家 + `glb` 读写 | 行为等价门禁绿；配置页能改到新参数 |
| B3 | `decide()` 出 `decisions` 明细 + `GET /api/strategy` + 来源标注 | 接口实测含 source；`/api/pacing` 兼容不变 |
| B4 | halt/resume/abort + 台账 + 建议器统一 | 中断行为测试绿；台账可查 |
| B5 | 控制面收口：矩阵扩到 **15 轴**（+可可视化/可调整/可清晰/可意图理解/可统计）→ 配置分区重构 → 健康卡策略条（微信扁平） | 既有 7200+ 项 + 新增项全绿，uitest 零 pageerror |
| **B6** | **（已拍板：本目标内做）维度/链路级真生效**：`main.py` 闸门接受 `(plat,dim,path)`、`ChannelBreaker` 键扩张、`special_radar` 接预算、`reload_config` 加 `strategy_params.set_config` 热链路 | 链路级限速/回退真生效的行为测试；熔断仍按渠道 → 记 `na` 并写明 |

## 12. 我的判断（可逐条否决）

1. **粒度键用平坦字符串** `"渠道/维度/链路"`（三段都取真实 id，见 §5），
   不用嵌套 dict——嵌套会让配置页搜索（`cfgSearch`）命中率掉，且 yaml 手改易错。
2. **策略条做成一行 chips**，装不下就折进「更多」，不新增第二行——
   r977 已把健康卡定成「两行节奏固定」。
3. **首批 24 条**，Android 真机族（tuning/identity/bootprops/vendor）与特价雷达族
   下一轮补；`--strict` 在补齐前只对已登记项负责（诚实）。
4. **台账复用** `save_intervention(platform, action, ok, rows, scope, before, after, note, ms, at)`
   （`core/storage.py:258`，已有 `before/after` 两列正好装「变更前后值」），
   新 `scope` 取值 `strategy:<id>`，不新建表。
5. `test_goal_requirements::test_goal_c` 允许改断言（分区标题从「渠道节流」
   改为「策略控制」），但**不允许删**——它是「节流不能散落」的历史约束。

---

## 附录 A：历轮相关要求逐条（86 条）

> 摘录自既有文档，行号指向当时版本；实现前用 `grep` 复核。末列是本设计的承载点。
> `SPEC`=`docs/EXECUTION_SPEC_LATEST.md`、`RLP`=`docs/RATE_LIMIT_PLAYBOOK.md`、
> `HCM`=`docs/HANDOFF_CAPABILITY_MATRIX.md`、`HFS`=`docs/HANDOFF_FULL_SESSION.md`、
> `HO`=`HANDOFF.md`、`YIELD`=`docs/YIELD_AND_SESSION_STRATEGY.md`。

### A 配置页必须可配置 / 不许只读展示 / 范围校验 / 回读（13）

1. `SPEC:1371` 配置页不允许存在无法配置的项；只读说明被整体撤掉改成编辑控件 → L4 可配置判据
2. `SPEC:1399` 「没有无法配置的项」要做成不变式，从 `config.example.yaml` 枚举 83 个叶子键逐个要求落点 → L5 矩阵（穷举而非名单）
3. `SPEC:1388` `crawler.proxy_map` 必须能在配置页配，一家被限流不牵连另一家 → L1 渠道覆盖
4. `SPEC:943` 新配置项必须回读，不能只写 → L4 `GET /api/strategy` + `/api/config`
5. `SPEC:950` 配置页每个 `GLB.xxx` 键都必须被 `/api/config` 回读 → L4 全量规则
6. `SPEC:923` 成功率保护阈值必须可配置（需求点名「可配置成功率」）→ L1 健康惩罚族
7. `SPEC:1483` 每个数字输入都要有范围校验，查不到不许静默放行 → L4 `GLB_RANGES`/`_DYN`
8. `SPEC:1443` 控件范围必须与后端钳制逐项一致 → L1 单一钳制点 + `test_r1063_strategy_params`
9. `SPEC:1448` 配了却没被扫的渠道不能整行消失 → L4 策略条「未扫描」态
10. `SPEC:2407` 节流参数须独立分区（22 个控件）→ §0.3 重构 `panel-pacing`
11. `RLP:285` 六项节流能力都要「可配置 + 可观测」，缺省保持旧行为 → L1+L4
12. `HFS:163` 配置页不允许任何无法配置的项；需重启就重启，能热更新就热更新 → C1 裁决
13. `HO:44` 所有监控信息可在配置页独立配置 → L1 粒度

### B 热生效 / 不许假装生效 / 夹取回写（10）

14. `SPEC:569` 「立即生效」还是「要重启」必须写代码时归类 → L1 `hot|boot` 标记
15. `SPEC:588` 两类都不许悄悄落在中间状态 → L4 保存后提示
16. `SPEC:1379` 这些键非启动级，保存即热生效 → L1 默认热载
17. `SPEC:931` 降频说明改为读配置，不再写死 70%/40% → L4 说明读生效值
18. `SPEC:605` 隐式夹取必须当场回写并说明 → C3 裁决
19. `SPEC:1315` 手写 YAML 的字符串假值不能让开关静默失效 → L1 类型归一
20. `SPEC:1607` 关掉熔断就不能还宣称「已熔断」 → C7 裁决
21. `SPEC:1624` 关掉的动件不能留下「等着它执行」的标记 → I9
22. `SPEC:1640` 「已弹出」必须是事实，不是「线程起来了」→ D 组判据（到达可观测状态）
23. `HO:204` toast 按 `RESTART.required` 说「N 项需重启生效」→ C1

### C 可视化：多维 / 来源 / 谁说了算 / 自动 vs 人工（15）

24. `SPEC:715` 健康度四维，不能只报厂商一个数 → L4 策略条按域/通路
25. `RLP:719` 可观测出口：节流状态条、`/api/pacing`、`/api/paths`、`/api/trace` → L4
26. `RLP:723` 可区分：PC/H5×国内/国际、明细 vs 日历、ip/captcha/login/busy → L4
27. `SPEC:856` 自动干预留痕，前端不得把 `auto_*` 的 ok=0 染红 → L4 台账 + `/^auto_/`
28. `SPEC:1744` 每个非 ok 状态都要自述，兜底不许凭空断言 → L4
29. `SPEC:1750` 「数据陈旧」要说清停了多久并标右半为历史口径 → L4
30. `SPEC:1293` 同一屏不能一句等人、一句说停了 → L4 同源
31. `SPEC:993` 会话失效必须在任何页面都看得见 → L4 常驻提示（既有 `#hauthact`）
32. `SPEC:1141` 颜色必须与同一枚徽标的文字同义 → L4 视觉
33. `SPEC:760` 演示态不显示可被引用的合成百分比 → C4 裁决
34. `SPEC:1418` 分通路必须能定位「为什么掉」→ L4 归因列
35. `SPEC:810` 路径劣化要点名「域×通路×有效率×样本」→ L4
36. `SPEC:1004` 溯源必须显示真实请求地址 → L4 trace
37. `SPEC:1169` 两条「自检」必须能分出是哪一域 → L4 动作带作用域
38. `SPEC:2750` 拦截态必须在登录卡/健康卡被识别、反馈并形成流转 → L2 状态机 + L4

### D 可干预：一键动作 / 可开可中断可恢复 / 幂等 / 在途可见（11）

39. `RLP:365` 可干预三动作（解除熔断/手动预热/出口自检），都持同一把渠道锁 → L4 `api`
40. `SPEC:799` 干预四性各有归属（自动化/可配置/可执行/可生效）→ §4 十轴
41. `SPEC:815` 干预必须幂等，完成后解锁（连点 3 次预热＝3 个真实请求）→ C2 裁决
42. `SPEC:825` 自动机制都要能关（成功率保护曾无开关）→ 十轴 `可开启`
43. `SPEC:1325` 干预在途必须换文案，不能只置灰 → C2
44. `SPEC:891` 验证窗口打开期间必须可见 → L4 进行中态
45. `SPEC:838` 登录墙占多数时必须给「重登」，不能让人干等 → 建议器规则
46. `RLP:877` 批量干预（全部自检/全部预热），顺序执行不许抢会话 → L4 + 并发钳制
47. `RLP:428` 验证闭环：关窗即复位 + 单查探测 → L4
48. `RLP:1343` 静默窗内保留手动扫描 + 补窗口说明 → 调度族
49. `HFS:161` 干预要及时、要能生效（每个 `advice.action` 在界面有落点）→ 十轴 `可建议`+`可干预`

### E 可建议：建议必须有真按钮 / 异常处就地给入口（7）

50. `HCM:324` `advise()` 的 hint 写「可点自检」时行内必须有自检按钮 → 十轴 `可建议`
51. `HCM:527` 可指导轴：hint 承诺的 action 必须在行内真渲染（`test_r905`）→ 门禁
52. `SPEC:785` 干预成效必须出现在决定行上，不藏二级页 → L4
53. `SPEC:910` 干预成功率是真指标（答「这类干预 12 次几次救回来」）→ 既有 `iv_rate`
54. `SPEC:1186` 干预成功率要按作用域分开说 → L2 `decisions.scope` + L4 台账 `scope`
55. `SPEC:687` 「去配置 / 去登录」入口在异常处就地给出 → L4 `cfgGoStrategy()`
56. `SPEC:550` 空态必须说明原因并给可执行入口 → L4

### F 独立性 / 粒度：渠道、域、通路、会话（10）

57. `SPEC:98` 健康加「厂商×域」维度（同程 12% 实为国内 100%＋国际 13%）→ L1 `dimension` 覆盖
58. `SPEC:99` 健康载荷与界面都要露出分通路 → L1 `path` 覆盖
59. `SPEC:722` 分会话 slots 逐端列出，单会话厂商不显示该行 → L1 `path`+会话
60. `SPEC:751` 两张通道表必须同序（`SRX_PLAT_ORDER`）→ L4
61. `SPEC:757` 退役通路不得静默消失，也不得再算一次成功率 → 通路族
62. `RLP:646` 国内 H5 被登录墙拦不代表国际 PC 坏；判断与处置落到域×通路 → L1 三级继承
63. `RLP:463` 每渠道独立节奏是硬地板（全局 TTL 未到也跳过）→ 既有 `cadence`
64. `RLP:491` `proxy_map[渠道]` 优先于全局 `proxy` → 既有
65. `SPEC:1546` 分域成功率的分子分母必须真是那个域 → L2 不许假拆分
66. `SPEC:1697` 新渠道要同步 REGISTRY / 健康告警映射 / 配置页可勾选 → L5 矩阵跨渠道

### G 审计 / 溯源：留痕、可回放、不污染分界（10）

67. `RLP:833` 干预账本持久化（at/platform/action/ok/rows/scope/before/after/note/ms）→ L4
68. `SPEC:856` 自动干预留痕但不能污染手动成效分界 → 既有 `auto_` 规则
69. `SPEC:1674` 干预账写不进去不许装没事 → L4 上抛 + 日志
70. `SPEC:317` 每条账同时记 http 状态码与 url → L0（不改）
71. `SPEC:1732` 网页重登必须入干预账 → L4 覆盖新动作
72. `SPEC:1014` 重登入账要幂等（不并排两条一样的）→ L4 去重
73. `SPEC:1520` 干预前后必须用同样长的窗口比 → 既有
74. `SPEC:1531` 「治好」判定必须封顶 → 既有
75. `SPEC:1055` 自动熔断入账要行为级验证 → L5 行为测试
76. `RLP:2066` 把「账本必须满足什么」写成常驻不变式 → L5

### H 单一声明 / 不许编造 / 不许静默 / 真渲染证据（10）

77. `SPEC:9` 唯一执行口径的完整版，不是补丁也不是增量说明 → C6 裁决（本设计不改该文件结构）
78. `SPEC:59` 唯一声明源 `core/channels.py`；hint 承诺的按钮必须真渲染 → L1 只解析不声明
79. `HCM:514` 每一格读真实登记点，不是第二份声明 → §4 判据总纲
80. `SPEC:766` 不可用也是状态，给 disabled + `aria-disabled` + 原因 → L4 `na` 格
81. `SPEC:1664` 文档里写的配置键必须真的存在 → L5 文档-代码对账
82. `RLP:801` 路径偏好先跑影子，不擅自改成自动改序 → 通路族默认只读
83. `HFS:172` 数据诚实 > 功能多，宁可「—」也不编造 → L4 `na`/「无样本」文案
84. `HCM:556` 静默吞参数、未验证写成支持、文案写死数量，都比少一个功能更严重 → L5 静默类定级
85. `SPEC:2148` 禁止用空集合断言当通过、禁止「代码里有这行」当作可见 → 门禁必须是行为/渲染级
86. `SPEC:1650` 「异步启动+立刻回报成功」一律改判「到达可观测状态」→ L4 动作回执

---

## 附录 B：首批 28 条策略 id 表（B1 落地的确切清单）

> `scope` 列是**允许覆盖的粒度上限**（`g`=全局、`c`=渠道、`d`=维度、`p`=链路）；
> `默认档` 按 §0.2 的裁决。`互斥/继承` 说明与既有键的关系。

| # | id | 中文名 | 族 | trigger | scope | cfg 键（真键） | 干预/动作 | 默认档 |
|---|---|---|---|---|---|---|---|---|
| 1 | `ttl_tier` | 分层 TTL | 节奏 | 主动 | g/c/d | `schedule.fast_ttl_min`、`slow_ttl_min` | — | 自动 |
| 2 | `near_window` | 邻近比价窗口 | 节奏 | 主动 | g/c | `schedule.near_ratio`、`near_days` | — | 自动 |
| 3 | `cadence` | 渠道最小间隔 | 节奏 | 主动 | g/c | `crawler.cadence[plat]` | — | 自动 |
| 4 | `schedule_clock` | 周期/扰动/错峰 | 节奏 | 主动 | g | `schedule.interval_minutes`、`jitter_minutes`、`stagger_seconds` | `/api/run` 立即扫 | 自动 |
| 5 | `quiet_window` | 静默窗 | 节奏 | 主动 | g | `schedule.scan_quiet_start/end` | 立即扫穿透 | 自动 |
| 6 | `rate_min_gap` | 最小请求间隔 | 限速 | 被动 | g/c/p | `crawler.rate.min_gap_s` | — | 自动 |
| 7 | `rate_per_minute` | 每分钟上限 | 限速 | 被动 | g/c/p | `crawler.rate.per_minute` | — | 自动 |
| 8 | `concurrency` | 并发上限/平台锁 | 限速 | 主动 | g | `crawler.max_concurrency`、`profile_wait_s` | — | 自动 |
| 9 | `budget` | 单次采集预算 | 限速 | 被动 | c | `android.fetch_budget_s`、路由级 900s | `/api/probe/cancel` | 自动（可中断） |
| 10 | `breaker_switch` | 熔断总开关 | 熔断 | 被动 | g | `crawler.breaker.enabled` | — | 自动 |
| 11 | `breaker_ladder` | 冷却阶梯 | 熔断 | 被动 | g | `crawler.breaker.base_s`、`cap_s` | `/api/pacing/reset` 解除 | 自动 |
| 12 | `login_cooldown` | 登录墙冷却 | 熔断 | 被动 | g | `crawler.breaker.login_cooldown_s` | 重登 | 自动 |
| 13 | `challenge_cooldown` | 硬风控冷却 | 熔断 | 被动 | g | `crawler.breaker.challenge_cooldown_s` | 去验证 | 自动 |
| 14 | `health_penalty` | 成功率保护（含五档阈值） | 健康 | 被动 | g/c | `crawler.health_penalty_enabled`、`health_ok_ratio`、`health_slow_ratio`、`health_slow_factor`、`health_slowest_factor`、`health_min_samples` | — | 自动 |
| 15 | `policy_gate` | 策略闸门 | 风险 | 自动 | g | `crawler.policy_gate` | — | 自动 |
| 16 | `pace_factor` | 间隔倍率五档 | 风险 | 自动 | g/c/d/p | **新** `crawler.policy.pace` | — | 自动 |
| 17 | `block_window` | 停手窗口 | 风险 | 自动 | g/c | **新** `crawler.policy.block_s` | halt/resume | 自动 |
| 18 | `risk_bands` | 风险分档 + 登录退避阶梯 | 风险 | 被动 | g/c | **新** `crawler.risk.levels`、`login_backoff_s` | 重登 | 自动 |
| 19 | `warmup` | 首页预热 | 预热 | 主动 | g/c | `crawler.warmup.enabled`、`platforms` | `/api/channel/warmup` | 自动 |
| 20 | `stealth_humanize` | 指纹一致性 + 拟人化 | 身份 | 主动 | g | `crawler.stealth`、`humanize`、`humanize_rounds` | — | 自动 |
| 21 | `identity_headers` | UA / 移动 UA / TLS 指纹 | 身份 | 主动 | g/c | `crawler.user_agent`、`mobile_user_agent`、`tls_impersonate` | 出口自检 | 自动 |
| 22 | `proxy_route` | 出口/代理选择 | 身份 | 主动 | g/c | `crawler.proxy`、`proxy_map[plat]` | `/api/channel/selfcheck` | 自动 |
| 23 | `rotate_advice` | 换身份建议 | 身份 | 主动 | c | （无参数：只建议） | 链接 playbook | **只建议** |
| 24 | `slider_attempt` | 滑块自动尝试 | 挑战 | 被动 | g/c | `crawler.slider.auto`、`single_shot` | 去验证 | 自动（有每日上限） |
| 25 | `slider_guard` | 滑块失败拉黑 | 挑战 | 被动 | g/c | `crawler.slider.daily_cap`、`max_fails` | — | 自动 |
| 26 | `captcha_solve` | 验证码识别 | 挑战 | 被动 | g | `crawler.captcha.arithmetic`、`text`、`ocr_scale`、`auto_verify` | `/api/challenge/open` | 自动 |
| 27 | `path_fallback` | 通路回退顺序 | 通路 | 主动 | c/p | （由 crawler 内 `_h5_fallback` 等实现，见 B6） | `/api/channel/probe` | 只读（先跑影子，`RLP:801`） |
| 28 | `retired_path` | 退役通路口径 | 通路 | 被动 | c/p | `path_stats` 在用/退役判定（L0 既有） | — | 自动 |

**边界说明**：`rotate_advice` 无执行动作（Q6 裁决）；`path_fallback` 默认只读影子、
不擅自动改序（`RLP:801`）；`budget` 的中断走既有探针取消，不新建路由。

---

## 需要你定的一件事（Q1）

**维度/链路级覆盖，这一轮做到「真生效」还是「先可配可见、下一轮真生效」？**

- **选项一（推荐·分两步）**：B1–B5 先把控制面立起来，其中**维度/链路粒度对
  「能定位到粒度」的策略真生效**（`rate_min_gap`、`rate_per_minute`、`pace_factor`、
  `ttl_tier`），对**记账只有渠道级**的策略（熔断/健康/停手）记 `na` 并写明原因；
  然后 **B6** 才去动 `main.py` 闸门、把 `ChannelBreaker` 键从 `plat` 扩成
  `(plat,path)`、给 `special_radar` 接预算、并在 `reload_config` 补 PolicyEngine
  刷新钩子。好处：每批可独立验收，风险可控；代价：第一版里「熔断按链路」还做不到，
  界面上会明写「熔断器按渠道记账」。
- **选项二（一次到位）**：B1–B6 合成一批，直接改闸门与熔断键。好处：一步达标，
  矩阵里 `na` 最少；代价：要同时改 `main.py`、10 个 crawler、`special_radar`、
  `ChannelBreaker` 与 reload 链，回归面最大，一旦行为漂移很难归因到哪一层。

我建议**选项一**：先把「可配置/可视化/可干预/可中断」这四句做实并出门禁，
再把粒度推到链路级——因为粒度扩张改的是**闸门与账本的键**，那是整个采集链最贵的一处。
