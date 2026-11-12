# -*- coding: utf-8 -*-
"""策略目录与十五轴审计矩阵：策略 × 质量轴的可求值事实表。

`core/channel_contract.py` 回答「这家渠道**是不是产品里的一等公民**」；
本模块往下一层，回答「这条**采集策略**是不是可控的一等公民」。用户点名的
十条轴（沿用 channel_contract 的语言）：

    可配置 configurable   可观测 observable    可干预 intervenable
    可开启 toggleable     可中断 interruptible  可区分 distinguishable
    可识别 identifiable   可建议 advisable      可独立 independent
    语义清晰 semantics

目标扩句（2026-11-06 round 2）再加五条，判据见 Spec §4.1：

    可可视化 visualizable 可调整 adjustable   可清晰 clear
    可意图理解 intent     可统计 stats

后五条与前十条的差别要记住：**前十条读「有没有接线」，后五条读「用户能不能
用」**——渲染落点（不是「代码里提过」）、界面能改并回读（不是「有 cfg 键」）、
≤20 字中文短句（不是「有中文名」）、一句话说清防什么/改了什么、台账能按策略
数出次数。可观测与可可视化是两件事：**可可视化**是「界面上有这个位置」，
**可观测**是「这个位置上有带时间戳的实时读数」，两者不许互相顶替。

设计约束（别退化）：
1. **不写第二份声明**：每轴都去读真实登记点——cfg 键是否真被 `core/**`、
   `crawlers/**`、`main.py` 读到；干预路由是否真在 `webui.py` 的
   `self.path == "/api/…"` 里；决定点/建议器指向的函数是否真在模块里
   （AST 里找得到）；界面上是否有 `data-strategy` 落点。改一处代码，这里
   立刻量得到差异，不需要有人去同步一张表。
2. **状态只有三种**：`y` 已接入、`n` 未接入（缺陷）、`na` 结构上不适用
   （例：只全局生效的调度类没有渠道级覆盖）。`n`/`na` 一律带「缺什么、
   看哪里」的中文说明，`na` 连理由都是必填（门禁会查）。
3. **新策略的验收就是 `audit()` 无 `n`**：加一条策略时漏登记参数键、
   漏接路由、漏接界面，这里直接报，不靠人对照清单。门禁见
   `tests/test_r1063_strategy_contract.py`，负控会造一个伪 cfg 键
   （形如 `schedule.<不存在的键>`）与一个「泛化末段」伪键
   （`crawler.nowhere_xyz.enabled`）证明判据不是恒真。
4. **本模块不参与自己的审计**：生产代码扫描集必须排除
   `core/strategy_contract.py` 自身（`SELF_REL`）。目录里写着新键的名字，
   一旦被扫进来，任何登记过的键都能「被生产代码读到」，判据当场变成自证循环。

preflight 裁决（2026-11-06，两条都写进目录里）：
① `crawler.policy.*` / `crawler.risk.*` 这类**新键**的 `Param` 不在 T1 登记，
   由 T3/T4 在「加读点」的同一步补上（否则可配置轴当场为 `n`，等于开局自欺）。
   **T3 已兑现**：`pace_factor` / `block_window`（含余温窗口）/ `health_penalty`
   的 `crawler.policy.pace.*`、`crawler.policy.block_s.*`、`crawler.policy.sticky_s.*`、
   `crawler.health.*` 与 `core/policy.py` 的读点同一次提交登记。
   **T4 已兑现**：`risk_bands` 的 `crawler.risk.levels.*` 与
   `crawler.risk.login_backoff_s` 与 `core/riskscore.py` 的读点同一次提交登记
   （此前它是 `params=()` + `na_reason` 的临时形态）。
② 人工停手（halt）**不是**一条可配置策略，它是 `block_window` 的干预动作，
   登记在 `block_window.api = ("/api/strategy/halt", "/api/strategy/resume")`
   上，不单独占一条 `Strategy`。

命令行走查（会议/发版前可用）：
    python -m core.strategy_contract            # 打印矩阵
    python -m core.strategy_contract --json     # 逐格明细（给前端/排查用）
    python -m core.strategy_contract --strict   # 有 n 则退出码 1

T11b → T12a → T12b → T12c 的状态（别误判成回归）：`--strict` 到 T12c 已经
**全绿**（28 条 × 15 轴，`n 0 格`；剩下的 `na` 是结构上不适用的诚实边界）。

* `visualizable`（28 条全 n → y）：T12b 的目录驱动渲染器（`webui.py` 的
  「配置 › 策略控制」分区）到位后转绿——判据三件都成立（`data-strategy`
  行模板 + `data-family` + 从 `/api/strategy` 取 id），且模板里没有任何
  逐条写死的 `data-strategy="<sid>"`；uitest 那半（真点到行）由 T14 补。
* `adjustable`（8 条 n → y）：**T12c 裁决**把判据补齐成「目录驱动的渲染模板
  + 该参数派生出来的控件 id 在 `GLB_RANGES`/`GLB_RANGES_DYN` 登记过」。
  改的是**判据口径**（T12b 收尾时认定这 62 格是口径缺口、不是界面缺口），
  但没有放宽成恒真：登记是**逐参数**手写的（数值给上下界、布尔/文本框给
  `ctl:1` 只登记「这颗控件真有」），漏登一个就报 `n`——负控见
  `tests/test_r1063_strategy_axes_closure.py`。**没有**为了这一轴去写 62 个
  逐键 `data-pid` 字面量（那正是本模块第 1 条约束要防的第二份声明）。uitest
  那半（点一下控件、看值进 `GLB.strategy_values` 再落盘）仍由 T14 断言。
* `toggleable`（19 条 n → y）：28 条各补 `<sid>.enabled`（`crawler.strategy_enabled.<sid>`，
  默认 `True`＝今天的行为），并**在同一提交里给每个开关补真读点**——只登记
  不读就是假开关，`configurable` 轴会当场报 `n`（`_strat_on()` 一族读点见
  `core/pacing.py` / `core/policy.py` / `core/riskscore.py` /
  `core/special_radar.py` / `core/storage.py`）。
* `intervenable`（14 条 n → y）：按**真路由**声明（`/api/run`、`/api/pacing/reset`、
  `/api/strategy/{halt,resume}`、`/api/channel/{warmup,selfcheck,probe}`、
  `/api/challenge/open`、`/api/round/abort`、`/api/probe/cancel`），审计逐条核
  `webui.py` 里的 `self.path == "..."`；不存在的路由一条都没写。
* `advisable`（21 条 n → y）：`core/strategy_advice.py::advise(sid, ctx)` 按
  **策略**给动作码 + <=40 字中文短句（不是 28 条同一句），`action` 属于
  `ACTIONS`，有执行入口的动作码都对应一条真路由；`/api/strategy` 的 `tip`
  字段直出、策略行也真渲染这一句。

T12a 已经转绿的两条，改的是**事实**不是判据：

* `observable`：`/api/strategy` 真有精确路由、且该分支真调 `audit(`（旧判据是
  子串，`/api/strategy/halt` 与一个 CSS 类名就能点亮——已收紧，见 `_ax_observable`）；
* `stats`：`core/storage.py::strategy_stats` 按 note 的 `[<sid>]` 前缀归集，
  `/api/strategy` 的 `stats` 三键售出（此前 26 条 n + 2 条 na）。
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 三态：与 core/channel_contract.py 保持同一套语言
Y, N, NA = "y", "n", "na"

# 枚举：Strategy 的取值域（semantics 轴逐条核）
TRIGGERS = ("proactive", "reactive", "auto")          # 主动 / 被动 / 自动化
SCOPES = ("global", "channel", "dimension", "path")   # 全局 / 渠道 / 维度 / 链路
FAMILIES = ("节奏", "限速", "熔断", "健康", "风险", "预热",
            "身份", "挑战", "通路", "预算", "调度")
# 参数类型枚举。`map` / `list` 是**容器**：`crawler.cadence` 是 `{渠道: 分钟}`、
# `crawler.proxy_map` 是 `{渠道: 代理}`、`crawler.warmup.platforms` 是渠道列表。
# 以前它们被登记成 int/str，T12 会照 kind 画控件——字典被画成数字框就是本项目
# 最恨的「配了不生效」，所以类型必须如实登记（容器值一律原样透传，不硬转）。
KINDS = ("int", "float", "bool", "str", "map", "list")

# 十五轴：(id, 中文名)。顺序即矩阵列序。后五条是目标扩句（Spec §4.1），
# 前十条一个都不许掉——`semantics`（语义清晰）与 `clear`（可清晰）是两件事：
# 前者说「字段/枚举/决策点自洽」，后者说「用户读到的是 ≤20 字的人话」。
AXES = (
    ("configurable", "可配置"),
    ("observable", "可观测"),
    ("intervenable", "可干预"),
    ("toggleable", "可开启"),
    ("interruptible", "可中断"),
    ("distinguishable", "可区分"),
    ("identifiable", "可识别"),
    ("advisable", "可建议"),
    ("independent", "可独立"),
    ("semantics", "语义清晰"),
    ("visualizable", "可可视化"),
    ("adjustable", "可调整"),
    ("clear", "可清晰"),
    ("intent", "可意图理解"),
    ("stats", "可统计"),
)
AXIS_IDS = tuple(a[0] for a in AXES)
AXIS_CN = {a[0]: a[1] for a in AXES}

# 标签（`Strategy.label`）允许的字符：中文 + 数字 + 少数中文标点。
# 为什么这么窄：标签是**策略行上给人看的那一行字**，出现英文/裸 id 就等于
# 把内部标识漏到界面上（Spec §4.1 可清晰：裸 id/英文/空 → n）。
LABEL_CHARS = "·（）0123456789/"

# 生产代码扫描面：cfg 键必须在这里被读到（webui.py 是界面，不算「被生产读」）
PROD_GLOBS = ("core/**/*.py", "crawlers/**/*.py")
PROD_FILES = ("main.py",)

# **本模块自己绝不能进扫描集**：它的注释与 na_reason 里写着新键的名字
# （`crawler.policy.block_s` 这种附录 B 的「新」键），一旦扫进来，任何登记过的
# 键都能「被生产代码读到」——判据当场变成自证循环（复核 2026-11-06 实测：
# `crawler.policy.block_s←core/strategy_contract.py`）。
SELF_REL = "core/strategy_contract.py"

# 参数层自身也**不算**读点：它的 docstring 里写着 pid 举例
# （`"ttl_tier.fast 的上限是 1440…"`），扫进来就会出现「提供方给自己作证」。
# 与 SELF_REL 同一条理由：判据只认**消费方**。
PARAMS_REL = "core/strategy_params.py"

# 中断动作的两条既有/待建路由（人停手 / 单次采集预算）
HALT_ROUTES = ("/api/strategy/halt", "/api/strategy/resume")

# `GET /api/strategy` 的**精确**路由字面量（引号收尾，`/api/strategy/halt` 不算）。
# 可观测轴用它定位分支：旧判据用子串，停手路由一上线就把这一轴白送成 `y`。
STRATEGY_ROUTE = "/api/strategy"
_STRATEGY_ROUTE_RX = re.compile(
    r"""self\.path\s*==\s*(['"])%s\1""" % re.escape(STRATEGY_ROUTE))

# 「真把审计结果接出去」的形态：**调用** `audit()` / `matrix_text()`（后面跟左括号）。
# 只认调用不认词：界面里一个 `class="auditbox"` 或注释里提一句都不该点亮这一轴。
_MATRIX_CALL_RX = re.compile(r"\b(?:matrix_text|audit)\s*\(")

# 目录驱动控件的**渲染模板**：`webui.py::stratCellHTML` 里 `data-pid="'+pid+'"`。
# T12c 裁决（写在 `_ax_adjustable` 里）：界面是目录驱动的，源码里**没有** 60 多个
# 逐键 `data-pid` 字面量，也不会为了审计去写一份（那是第二份声明）。判据因此
# 认「模板路径 + 该参数的控件 id 在边界表里登记过」这条链——登记是**逐参数**的，
# 漏登一个就报 `n`，所以判据不是恒真（负控见
# `tests/test_r1063_strategy_axes_closure.py::test_adjustable_is_not_constant_true_for_unregistered_params`）。
_ROW_TPL_RX = re.compile(r"""data-pid\s*=\s*["']\s*['"]\s*\+\s*pid\s*\+\s*['"]""")

# 行内控件覆盖的参数类型：`map` 故意不画单框（把字典塞进一个 input 会把配置
# 毁成一句不可逆的字符串，见 `stratCellHTML` 的 map 分支只报规模）。
ROW_INPUT_KINDS = ("bool", "int", "float", "str", "list")

# 控件 id 的派生规则（与 `webui.py::stratCid` 逐字对应）：顶层段与纯分组段
# 不进名字（它们是「在哪」而不是「是什么」），`_s` 后缀去掉，剩下的段首字母大写。
# 这条规则是**界面与审计之间唯一的约定**，门禁
# `tests/test_r1063_strategy_axes_closure.py::test_control_id_derivation_matches_the_console`
# 拿真源码逐条对账，防止两边悄悄分叉。
CID_DROP = ("crawler", "schedule", "android", "policy", "levels")

GATE = "tests/test_r1063_strategy_contract.py"

# T12c：建议器只有一处（`core/strategy_advice.py`），按族给动作码 + 中文短句。
# 目录里 28 条全指向它——第二份建议文案就是「两条策略说同一句话」的源头。
ADVICE = "core.strategy_advice:advise"


@dataclass(frozen=True)
class Param:
    """一个可调参数：`pid` 是策略内标识，`cfg` 是 config.yaml 的点路径真键。

    `kind` 取值见 `KINDS`：int/float/bool/str 与两种容器（`map`=字典、
    `list`=列表）。`bool` 是「可开启」轴的唯一凭据，所以开关类参数必须用
    `kind="bool"` 登记，不要用 0/1 的 int 混过去；容器类**不许**登记成 str
    ——`str(dict)` 会把配置毁成一句不可逆的字符串，界面也会画错控件。
    """

    pid: str
    cfg: str
    kind: str
    default: object = None
    lo: object = None
    hi: object = None


@dataclass(frozen=True)
class Strategy:
    """一条采集策略的目录条目。字段语义见 Spec §4。

    `decide` = 决策点 `module:func`（函数必须在源文件里真有），
    `api` = 干预路由字面量（必须在 webui.py 里真有），
    `advice` = 建议器 `module:func`（同上），`gate` = 门禁文件。

    目标扩句（2026-11-06 round 2）新增三个人话字段——它们是**界面文案的唯一
    来源**，T12 的 `/api/strategy` 直出、T13 的策略行直接渲染，界面里不许再
    写第二份：

    * `label`（≤20 字）：**策略行上的那一行字**，说清「它现在是什么状态/它管
      什么」（例：`快慢两档抓取间隔`）。只许中文 + 数字 + `·（）/`——出现英文
      或裸 id 就等于把内部标识漏给用户（可清晰轴会报 n）。
    * `intent`（≤40 字）：一句话说清**它在防什么/图什么**（为什么存在）。
    * `effect`（≤40 字）：一句话说清**改了会发生什么**（调大调小各是什么后果）。
    """

    id: str
    cn: str
    family: str
    trigger: str
    scope: Tuple[str, ...]
    params: Tuple[Param, ...] = ()
    decide: str = ""
    api: Tuple[str, ...] = ()
    advice: str = ""
    auto_default: bool = True
    gate: str = ""
    na_reason: str = ""
    label: str = ""
    intent: str = ""
    effect: str = ""


@dataclass(frozen=True)
class Row:
    """矩阵的一格：哪条策略 / 哪个渠道（`*`=不分渠道）/ 哪条轴 / 状态 / 说明。"""

    sid: str
    plat: str
    axis: str
    state: str
    note: str = ""


def _enabled(sid: str) -> Param:
    """每条策略的 `enabled` 开关：`crawler.strategy_enabled.<sid>`，默认 `True`。

    **默认 True 是逐位等价的保证**：缺省（用户没写过这个键）时 `resolve()`
    返回目录默认值 True，决策点走今天这条分支，行为一个字节都不变；只有人
    显式关掉才改路。`kind="bool"` 是「可开启」轴的唯一凭据（用 0/1 的 int
    混过去会让界面画出数字框）。

    `cfg` 用**一族统一前缀** `crawler.strategy_enabled.*`，不为每条策略各开
    一个键：开关的语义就是「这条策略生不生效」，散成 28 个位置后没有任何
    人能一眼看出「现在关掉了哪几条」。读点写在各决策点里（见
    `core/pacing.py::_strat_on` 等，`configurable` 轴逐条核）。
    """
    return Param(sid + ".enabled", "crawler.strategy_enabled." + sid,
                 "bool", True)


# ---------------------------------------------------------------- 策略目录
#
# 逐条照 Spec 附录 B 的 28 行（id / 中文名 / 族 / trigger / scope / cfg 键），
# 一行都不许少——`test_registry_has_28_strategies_with_unique_ids` 会数。
# 详细值的来源：`schedule.*` / `crawler.*` 的真键在 config.yaml 与
# core/pacing.py 的 DEFAULTS 里各写了一遍，默认值与上下界按 pacing 的
# `_num(...)` 夹取范围填，绝不自己发明键名。
STRATEGIES: Tuple[Strategy, ...] = (
    # 1 节奏族：快/慢两档 TTL。write: core/pacing.py:parse_pacing → plan_query
    Strategy(id="ttl_tier", cn="分层 TTL", family="节奏", trigger="proactive",
             label="快慢两档抓取间隔",
             intent="价格变动快的航线要更勤抓，又不许把请求量打爆",
             effect="快档调小更灵敏但请求变多；慢档调小冷门航线也变勤",
             scope=("global", "channel", "dimension"),
             params=(_enabled("ttl_tier"),
                     Param("ttl_tier.fast", "schedule.fast_ttl_min", "int", 15, 5, 1440),
                     Param("ttl_tier.slow", "schedule.slow_ttl_min", "int", 120, 5, 1440)),
             decide="core.pacing:plan_query", api=("/api/run",), advice=ADVICE,
             gate=GATE),
    # 2 邻近比价窗口：命中阈值与「临期多少天」两键
    Strategy(id="near_window", cn="邻近比价窗口", family="节奏", trigger="proactive",
             label="邻近日期加密比价",
             intent="临近出发的日期最值钱，把抓取预算往那边挪",
             effect="比例与天数调大：更多日期进重点，请求量随之上升",
             scope=("global", "channel"),
             params=(_enabled("near_window"),
                     Param("near_window.ratio", "schedule.near_ratio", "float", 0.15, 0.0, 1.0),
                     Param("near_window.days", "schedule.near_days", "int", 3, 1, 30)),
             decide="core.pacing:plan_query", api=("/api/run",), advice=ADVICE,
             gate=GATE),
    # 3 渠道最小间隔：`cadence` 是 {plat: 分钟} 映射，所以 pid 带 per_plat。
    #   kind 必须是 `map`（登记成 int 会让界面画出「一个数字」的数字框）
    Strategy(id="cadence", cn="渠道最小间隔", family="节奏", trigger="proactive",
             label="各渠道最少间隔分钟",
             intent="给每家单设节奏，别让一家拖住全站",
             effect="把某家调大：那家变慢，其它家不受影响",
             scope=("global", "channel"),
             params=(_enabled("cadence"),
                     Param("cadence.per_plat", "crawler.cadence", "map", 0, 0, 720),),
             decide="core.pacing:plan_query", api=("/api/run",), advice=ADVICE,
             gate=GATE),
    # 4 调度时钟：周期 + 扰动 + 错峰；干预动作是「立即扫」
    Strategy(id="schedule_clock", cn="周期/扰动/错峰", family="节奏", trigger="proactive",
             label="多久跑一轮·错峰起跑",
             intent="别让整点固定抓取变成可识别的机器节奏",
             effect="周期变短更新更快但请求更多；扰动变大自然一些",
             scope=("global",),
             params=(_enabled("schedule_clock"),
                     Param("schedule_clock.interval", "schedule.interval_minutes",
                           "int", 30, 5, 1440),
                     Param("schedule_clock.jitter", "schedule.jitter_minutes",
                           "int", 8, 0, 120),
                     Param("schedule_clock.stagger", "schedule.stagger_seconds",
                           "int", 25, 0, 120)),
             decide="core.scheduler:run_scheduler", api=("/api/run",), advice=ADVICE, gate=GATE),
    # 5 静默窗：只有起止两个 HH:MM 串；「立即扫」穿透它
    Strategy(id="quiet_window", cn="静默窗", family="节奏", trigger="proactive",
             label="夜间静默不抓取",
             intent="夜间不打扰，也不在低价值时段留下痕迹",
             effect="改起止：静默期内整轮跳过，手动立即扫仍能穿透",
             scope=("global",),
             params=(_enabled("quiet_window"),
                     Param("quiet_window.start", "schedule.scan_quiet_start", "str", "01:00"),
                     Param("quiet_window.end", "schedule.scan_quiet_end", "str", "07:00")),
             decide="core.pacing:in_window", api=("/api/run",), advice=ADVICE, gate=GATE),
    # 6 限速族：最小请求间隔（可到链路级）
    Strategy(id="rate_min_gap", cn="最小请求间隔", family="限速", trigger="reactive",
             label="相邻请求至少隔几秒",
             intent="两次请求挨太近最容易触发风控",
             effect="调大更安全但更慢；调到零等于不设间隔",
             scope=("global", "channel", "path"),
             params=(_enabled("rate_min_gap"),
                     Param("rate_min_gap.value", "crawler.rate.min_gap_s",
                           "float", 3.0, 0, 300),),
             decide="core.pacing:allow", api=("/api/pacing/reset",), advice=ADVICE, gate=GATE),
    # 7 限速族：每分钟上限
    Strategy(id="rate_per_minute", cn="每分钟上限", family="限速", trigger="reactive",
             label="每分钟最多问几次",
             intent="一分钟内问太多必被限流",
             effect="调小上限更保守；零表示不按分钟限制",
             scope=("global", "channel", "path"),
             params=(_enabled("rate_per_minute"),
                     Param("rate_per_minute.value", "crawler.rate.per_minute",
                           "int", 0, 0, 600),),
             decide="core.pacing:allow", api=("/api/pacing/reset",), advice=ADVICE, gate=GATE),
    # 8 限速族：同轮并发浏览器数 + 每渠道 profile 启动等待
    Strategy(id="concurrency", cn="并发上限/平台锁", family="限速", trigger="proactive",
             label="同时开几个浏览器",
             intent="同时开太多浏览器会抢内存，也会显得异常",
             effect="调大一轮更快但更吃资源，风控面也变大",
             scope=("global",),
             params=(_enabled("concurrency"),
                     Param("concurrency.max", "crawler.max_concurrency", "int", 0, 0, 5),
                     Param("concurrency.profile_wait", "crawler.profile_wait_s",
                           "float", 20.0, 0, 120)),
             decide="crawlers.base:platform_lock", api=("/api/round/abort",), advice=ADVICE, gate=GATE),
    # 9b 限速族：**渠道内部**的限速档位（r1063 T31，原先是类属性字面量）
    #   这些不是"我方全局节流"，而是各渠道自己为防 1999/软风控留的档位：
    #   调小=更快也更容易撞限流（风控代价换速度），调大=更稳更慢。
    Strategy(id="channel_rate", cn="渠道内限速档", family="限速",
             trigger="proactive",
             label="各家自己留多宽的量",
             intent="各家接口限流窗口不同，档位写死就没法按实况取舍",
             effect="调小更快但更易撞限流；调大更稳更慢",
             scope=("global", "channel"),
             params=(_enabled("channel_rate"),
                     Param("channel_rate.qunar_min_gap_s",
                           "crawler.qunar_min_gap_s", "float", 8.0, 1.0, 60.0),
                     Param("channel_rate.qunar_wait_budget_s",
                           "crawler.qunar_round_wait_budget_s",
                           "int", 300, 0, 3600),
                     Param("channel_rate.tuniu_rate_max",
                           "crawler.tuniu_rate_max", "int", 3, 1, 20),
                     Param("channel_rate.tuniu_window_s",
                           "crawler.tuniu_rate_window_s",
                           "float", 600.0, 60.0, 3600.0)),
             decide="crawlers.tuniu:_rate_limits",
             api=("/api/pacing/reset",), advice=ADVICE, gate=GATE),
    # 9 限速族：单次采集预算（App 540s / 网页路由级 900s 字面量）；
    #   中断走既有探针取消，不新建路由
    Strategy(id="budget", cn="单次采集预算", family="限速", trigger="reactive",
             label="一次采集最多花多久",
             intent="单次采集无限拖会一直占着浏览器且越抓越险",
             effect="调小更快收工、可能缺样本；零表示不限时",
             scope=("channel",),
             params=(_enabled("budget"),
                     Param("budget.fetch_s", "android.fetch_budget_s",
                           "int", 540, 0, 3600),
                     # r1063 T28：网页端「路由级栅栏超时」。原先写死 15 分钟
                     # (`main._ROUTE_FUT_TIMEOUT`)，一次挂死白等 15 分钟；
                     # 实测单渠道耗时最大 165s，300s 足够，且可按渠道覆盖。
                     Param("budget.route_s", "crawler.route_timeout_s",
                           "int", 300, 30, 900)),
             decide="core.android.runtime:_fetch_budget_s",
             api=("/api/probe/cancel",), advice=ADVICE, gate=GATE),
    # 10 熔断族：总开关（关掉后仍分类留证，但不再宣称「已熔断」）
    Strategy(id="breaker_switch", cn="熔断总开关", family="熔断", trigger="reactive",
             label="熔断是否生效",
             intent="先要能一键停掉自动冷却，修配置时不被拦",
             effect="关掉后仍分类留证，但不再宣称已熔断、不再自动冷却",
             # scope 是**事实声明**，照读点写（波次六修正）：读点是
             # `core/pacing.py::observe` 的 `switch_on("breaker_switch.enabled",
             # plat=…, dim=…, path=…)`，`渠道` / `渠道/维度` / `渠道/维度/链路`
             # 三层覆盖都真生效。写 ("global",) 会让「配了不生效」变成
             # 「声明说它不生效」——两件事都不是界面该显示的。
             scope=("global", "channel", "dimension", "path"),
             params=(Param("breaker_switch.enabled", "crawler.breaker.enabled",
                           "bool", True),),
             decide="core.pacing:observe", api=("/api/pacing/reset",), advice=ADVICE,
             gate=GATE),
    # 11 熔断族：冷却阶梯起点与封顶；干预动作是「解除」
    Strategy(id="breaker_ladder", cn="冷却阶梯", family="熔断", trigger="reactive",
             label="冷却从几分钟起·封顶",
             intent="一次失败就长歇会浪费窗口，不歇又会被打死",
             effect="起步与封顶调大冷却更久；解除按钮不受影响",
             scope=("global",),
             params=(_enabled("breaker_ladder"),
                     Param("breaker_ladder.base", "crawler.breaker.base_s",
                           "int", 300, 60, 3600),
                     Param("breaker_ladder.cap", "crawler.breaker.cap_s",
                           "int", 3600, 300, 86400)),
             decide="core.pacing:round_backoff_minutes",
             api=("/api/pacing/reset",), advice=ADVICE, gate=GATE),
    # 12 熔断族：登录墙冷却（干预动作 = 重登）
    Strategy(id="login_cooldown", cn="登录墙冷却", family="熔断", trigger="reactive",
             label="撞登录墙后歇多久",
             intent="撞登录墙后立刻重试只会把账号送进去",
             effect="调大：登录墙之后歇更久，重登入口仍在",
             scope=("global",),
             params=(_enabled("login_cooldown"),
                     Param("login_cooldown.s", "crawler.breaker.login_cooldown_s",
                           "int", 900, 0, 86400),),
             decide="core.pacing:trip", api=("/api/login",),
             advice=ADVICE, gate=GATE),
    # 13 熔断族：硬风控冷却（config.yaml 未写该键 → pacing 用 6h 默认值）
    Strategy(id="challenge_cooldown", cn="硬风控冷却", family="熔断", trigger="reactive",
             label="被硬风控后歇多久",
             intent="硬风控不是缓存问题，硬顶必被封",
             effect="调大整家停更久；调小要自己承担风险",
             scope=("global",),
             params=(_enabled("challenge_cooldown"),
                     Param("challenge_cooldown.s",
                           "crawler.breaker.challenge_cooldown_s",
                           "int", 21600, 0, 86400),),
             decide="core.pacing:trip", api=("/api/challenge/open",), advice=ADVICE, gate=GATE),
    # 13b 熔断族：会话重建（干预动作 = 换一份干净浏览器档案）
    #   **依据**：用户实机观察——飞猪验证码过不去，清掉数据后又能看到机票。
    #   影子档案被风控"记住"了，换一份干净档案反而回到匿名可信态。
    #   代价：必然丢 cookie（可能要重登）→ 所以有阈值、冷却、每日上限，
    #   并且**只挪不删**（目录改名备份，可一键还原）。
    Strategy(id="session_reset", cn="会话重建", family="熔断", trigger="reactive",
             label="连续被拦后换一份干净档案",
             intent="档案被记住之后，继续用同一份只会一直被拦",
             effect="关掉永不重建；调大阈值更保守；冷却/上限越大越不容易反复丢登录态",
             scope=("global", "channel"),
             params=(_enabled("session_reset"),
                     Param("session_reset.after_fails",
                           "crawler.session_reset.after_fails", "int", 3, 1, 20),
                     Param("session_reset.cooldown_s",
                           "crawler.session_reset.cooldown_s", "int",
                           21600, 300, 604800),
                     Param("session_reset.daily_cap",
                           "crawler.session_reset.daily_cap", "int", 2, 1, 10),
                     Param("session_reset.keep",
                           "crawler.session_reset.keep", "int", 3, 1, 10)),
             decide="core.session_reset:should_reset",
             api=("/api/session/reset", "/api/session/restore"),
             advice=ADVICE, gate=GATE),
    # 14 健康族：成功率保护（含五档阈值）
    #   **三套「长得像但互不影响」的阈值，别当成一个旋钮**（复核 2026-11-06）：
    #     ① `crawler.health_min_samples` / `health_ok_ratio` / `health_slow_ratio`
    #        / `health_slow_factor` / `health_slowest_factor`（本策略的
    #        `health_penalty.*`）＝ **pacing 的 TTL 阶梯**，改的是**采集间隔**
    #        （读点 core/pacing.py::set_health）；
    #     ② `crawler.health.min_samples` / `ok_low` / `ok_high`
    #        （`health_bands.*`）＝ **policy 的产量分带**，改的是**风险姿态倍率**
    #        （读点 core/policy.py::decide）；
    #     ③ `pace_factor.*`（`crawler.policy.pace.*`）＝ 风险档位倍率本身。
    #   默认值 0.4 与 0.40、`health_min_samples`(5) 与 `health.min_samples`(8)、
    #   1.5/3.0 与 `pace_factor.watch|rehab|blocked` 撞值是历史原因（r485 的
    #   pacing 四档 + r1063 的 policy 分带各登记一次），不是同一份数据：
    #   改 ① 不会动 ② 的判定，反之亦然，界面上要给用户看得见的说明。
    #
    #   r1063 T15/T16（本条已从「钉死声明」升级为「真接线」）：
    #   `storage.path_stats(24)` 除渠道节点外还出 `dims`（按 `dim_of_path()`）
    #   与 `paths`（每个入口通路一条：`PC`/`H5`/`H5/API`/`API`/`日历`/`往返`…），
    #   三级都有真实样本。`main.py` 逐维度、逐链路喂 `set_health(..., dim=, path=)`；
    #   `plan_query(..., dim=)` 按维度取 TTL 倍数，`gate_path()` 按链路取限速倍数。
    #   于是「日历烂只降日历」「H5/API 烂只压 H5/API」都成立，每级样本不足
    #   自动回落上一级（链路 → 维度 → 渠道）。
    Strategy(id="health_penalty", cn="成功率保护（含五档阈值）", family="健康",
             label="成功率低就自动降频",
             intent="成功率掉下去要自己慢下来，而不是硬抓到被封",
             effect="按链路/维度独立降频：H5/API 烂只压它自己，样本不足逐级回落",
             trigger="reactive",
             scope=("global", "channel", "dimension", "path"),
             params=(Param("health_penalty.enabled", "crawler.health_penalty_enabled",
                           "bool", True),
                     Param("health_penalty.ok_ratio", "crawler.health_ok_ratio",
                           "float", 0.7, 0.05, 1.0),
                     Param("health_penalty.slow_ratio", "crawler.health_slow_ratio",
                           "float", 0.4, 0.0, 1.0),
                     Param("health_penalty.slow_factor", "crawler.health_slow_factor",
                           "float", 1.5, 1.0, 10.0),
                     Param("health_penalty.slowest_factor",
                           "crawler.health_slowest_factor", "float", 3.0, 1.0, 10.0),
                     Param("health_penalty.min_samples", "crawler.health_min_samples",
                           "int", 5, 1, 100),
                     # ---- ② policy 的产量分带（不是上面那套 pacing 阈值）------
                     Param("health_bands.min_samples", "crawler.health.min_samples",
                           "int", 8, 1, 200),
                     Param("health_bands.ok_low", "crawler.health.ok_low",
                           "float", 0.40, 0.0, 1.0),
                     Param("health_bands.ok_high", "crawler.health.ok_high",
                           "float", 0.90, 0.0, 1.0)),
             decide="core.pacing:set_health", api=("/api/channel/selfcheck",),
             advice=ADVICE, gate=GATE),
    # 15 风险族：策略闸门（从「一个总开关」变成闸门策略族的一员，语义不变）
    Strategy(id="policy_gate", cn="策略闸门", family="风险", trigger="auto",
             label="总闸门是否放行采集",
             intent="总闸门关掉必须真的不采集，而不是只改显示",
             effect="关掉后所有链路按被停用处理，账本记停用而非无票",
             # 波次六：闸门读点是两个采集器基类的 `_policy_enabled(dim=…)`
             # → `switch_on("policy_gate.enabled", plat=…, dim=…)`。**没有
             # `path=`**（闸门是采集入口，一次采集跨多条链路，路径级没有
             # 唯一答案），所以链路层不写进声明——写宽了就是这一条策略在
             # 吹牛，而这正是本项目头号缺陷的元数据形态。
             scope=("global", "channel", "dimension"),
             params=(Param("policy_gate.enabled", "crawler.policy_gate", "bool", True),),
             decide="core.policy:allow", api=("/api/strategy/halt", "/api/strategy/resume"), advice=ADVICE, gate=GATE),
    # ------------------------------------------------------------------
    # T3（2026-11-06）：`core/policy.py` 的决策常量搬进参数层，**同一提交里
    # 登记 Param**（Ruling P1：新键要跟读点一起登记，否则可配置轴当场为 n）。
    # 默认值与搬家前的字面量逐位相等，门禁
    # `tests/test_r1063_policy_params_equivalent.py` 会一个一个对。
    # ------------------------------------------------------------------
    # 16 风险族：间隔倍率五档（原 `core.policy._PACE`）
    Strategy(id="pace_factor", cn="间隔倍率五档", family="风险", trigger="auto",
             label="各风险档的放慢倍数",
             intent="风险越高下手越慢，把节奏交给同一套倍率",
             effect="调大某档：该档间隔成倍拉长，健康档不受影响",
             scope=("global", "channel", "dimension", "path"),
             params=(_enabled("pace_factor"),
                     Param("pace_factor.healthy", "crawler.policy.pace.healthy",
                           "float", 1.0, 0.1, 10.0),
                     Param("pace_factor.rehab", "crawler.policy.pace.rehab",
                           "float", 1.5, 0.1, 10.0),
                     Param("pace_factor.watch", "crawler.policy.pace.watch",
                           "float", 1.5, 0.1, 10.0),
                     Param("pace_factor.degraded", "crawler.policy.pace.degraded",
                           "float", 2.5, 0.1, 10.0),
                     Param("pace_factor.blocked", "crawler.policy.pace.blocked",
                           "float", 3.0, 0.1, 10.0)),
             decide="core.policy:decide", api=("/api/strategy/halt", "/api/strategy/resume"), advice=ADVICE, gate=GATE),
    # 17 风险族：停手窗口（原 `core.policy._BLOCK_S`）+ 余温窗口
    #   （原 `core.policy._STICKY_S`）。
    #   为什么余温窗口也挂在这条：两者都是「某个状态要持续多久」的**时间窗口**，
    #   由同一个 `decide()` 读写；而门禁断言目录恰好 28 条（不许为它新建第 29 条
    #   策略），所以按「同类归一条」挂在停手窗口上，不另开一行。
    #   人工停手不是独立策略，而是这条上的干预动作（preflight 裁决②）。
    Strategy(id="block_window", cn="停手窗口", family="风险", trigger="auto",
             label="自停多久·余温多长",
             intent="自停要有期限，别一次误判就永久停摆",
             effect="调大自停更久；余温调大：好转后仍慢一阵",
             scope=("global", "channel"),
             params=(_enabled("block_window"),
                     Param("block_window.human", "crawler.policy.block_s.human",
                           "int", 3600, 60, 86400),
                     Param("block_window.rotate", "crawler.policy.block_s.rotate",
                           "int", 3600, 60, 86400),
                     Param("residue_window.watch", "crawler.policy.sticky_s.watch",
                           "int", 1800, 0, 86400),
                     Param("residue_window.degraded",
                           "crawler.policy.sticky_s.degraded",
                           "int", 3600, 0, 86400),
                     Param("residue_window.rehab", "crawler.policy.sticky_s.rehab",
                           "int", 1800, 0, 86400)),
             decide="core.policy:decide", api=HALT_ROUTES, advice=ADVICE, gate=GATE),
    # 18 风险族：风险分档 + 登录退避阶梯
    #   T4（2026-11-06）：原 `core/riskscore.py` 的 `_THRESHOLD`（25/45/65/80）
    #   与 `LOGIN_BACKOFF`（0/90/300/900/1800/3600/7200）搬进参数层，读点是
    #   `core.riskscore.evaluate()` / `LoginLedger.backoff_s()`，门禁
    #   `tests/test_r1063_risk_params_equivalent.py` 逐位对账。四个分界的
    #   上下界 0–100 = 评分本身的值域（`evaluate()` 把分数夹在 0–100）。
    #   退避阶梯是**列表**（第 n 级 = 连击 n 次后要等的秒数），所以 kind=`list`，
    #   容器值原样透传、不夹取——超界取末元素这件事在消费方做。
    Strategy(id="risk_bands", cn="风险分档 + 登录退避阶梯", family="风险",
             label="风险分档线与退避阶梯",
             intent="风险分档决定姿态，退避阶梯决定重登节奏",
             effect="分界线调低更早降档；阶梯改长重登更慢",
             trigger="reactive", scope=("global", "channel"),
             params=(_enabled("risk_bands"),
                     Param("risk_bands.watch", "crawler.risk.levels.watch",
                           "int", 25, 0, 100),
                     Param("risk_bands.slow", "crawler.risk.levels.slow",
                           "int", 45, 0, 100),
                     Param("risk_bands.pause", "crawler.risk.levels.pause",
                           "int", 65, 0, 100),
                     Param("risk_bands.human", "crawler.risk.levels.human",
                           "int", 80, 0, 100),
                     Param("risk_bands.login_backoff_s",
                           "crawler.risk.login_backoff_s", "list",
                           [0, 90, 300, 900, 1800, 3600, 7200])),
             decide="core.riskscore:assess", api=("/api/login",), advice=ADVICE, gate=GATE),
    # 19 预热族：首页预热开关与渠道集
    #   `platforms` 是渠道 id 列表 → kind=`list`，不是 str
    #   波次六：`warmup.enabled` 的两个真消费点都吃**维度**——
    #   ① `core/pacing.py::observe` 的软拒分支 `warmup_on(plat, dim, path=…)`；
    #   ② `main.py::_warm_once` 预热首页前 `warmup_on(c.name, dim=dim)`
    #      （波次六把调用点的 `dim` 真递进来了，此前只给渠道）。
    #   链路层仍不写进声明：`_warm_once` 打的是渠道首页，没有「哪条路」的
    #   概念，只有①那条软拒分支拿得到 path——只到一半就不许说支持。
    Strategy(id="warmup", cn="首页预热", family="预热", trigger="proactive",
             label="每轮先打一次首页",
             intent="直接进深链缺来源页，是最容易被认出的入口",
             effect="关掉省一次请求但更像机器人；渠道集决定谁预热",
             scope=("global", "channel", "dimension"),
             params=(Param("warmup.enabled", "crawler.warmup.enabled", "bool", True),
                     Param("warmup.platforms", "crawler.warmup.platforms", "list", "")),
             decide="crawlers.base:warmup", api=("/api/channel/warmup",), advice=ADVICE, gate=GATE),
    # 20 身份族：指纹一致性 + 拟人化开关与轮数
    Strategy(id="stealth_humanize", cn="指纹一致性 + 拟人化", family="身份",
             label="指纹一致·动作拟人",
             intent="指纹与动作不一致比不伪装更可疑",
             effect="关掉更快但更容易被识别；轮数调大更慢更自然",
             trigger="proactive", scope=("global",),
             params=(_enabled("stealth_humanize"),
                     Param("stealth_humanize.stealth", "crawler.stealth", "bool", True),
                     Param("stealth_humanize.humanize", "crawler.humanize", "bool", True),
                     Param("stealth_humanize.rounds", "crawler.humanize_rounds",
                           "int", 2, 0, 10)),
             decide="crawlers.base:stealth_replacements", api=("/api/channel/selfcheck",), advice=ADVICE, gate=GATE),
    # 21 身份族：UA / 移动 UA / TLS 指纹；干预动作 = 出口自检
    Strategy(id="identity_headers", cn="UA / 移动 UA / TLS 指纹", family="身份",
             label="浏览器身份三件套",
             intent="身份三件套互相对不上会立刻进风控名单",
             effect="留空用内置默认；改错组合比不改更危险",
             trigger="proactive", scope=("global", "channel"),
             params=(_enabled("identity_headers"),
                     Param("identity_headers.ua", "crawler.user_agent", "str", ""),
                     Param("identity_headers.mobile_ua", "crawler.mobile_user_agent",
                           "str", ""),
                     Param("identity_headers.tls", "crawler.tls_impersonate", "str", "")),
             decide="crawlers.base:profile_headers",
             api=("/api/channel/selfcheck",), advice=ADVICE, gate=GATE),
    # 22 身份族：出口/代理选择（全局 proxy + 每渠道 proxy_map）
    #   `proxy_map` 是 {渠道: 代理串} 映射 → kind=`map`，不是 str
    Strategy(id="proxy_route", cn="出口/代理选择", family="身份", trigger="proactive",
             label="走哪个出口节点",
             intent="一家被限流不该牵连全站出口",
             effect="填单渠道出口只换那家；留空跟随全局",
             scope=("global", "channel"),
             params=(_enabled("proxy_route"),
                     Param("proxy_route.global", "crawler.proxy", "str", ""),
                     Param("proxy_route.map", "crawler.proxy_map", "map", "")),
             decide="core.net:new_client", api=("/api/channel/selfcheck",), advice=ADVICE, gate=GATE),
    # 23 身份族：换身份建议（只建议，无参数、无执行动作——Q6 裁决）
    Strategy(id="rotate_advice", cn="换身份建议", family="身份", trigger="proactive",
             label="建议换身份·只提示",
             intent="身份用久了风险会累积，但换身份要人决定",
             effect="只出建议与动作码，不动设备身份、不自动执行",
             scope=("channel",), params=(_enabled("rotate_advice"),
                     ),
             decide="core.riskscore:should_rotate", api=("/api/channel/selfcheck",), auto_default=False,
             na_reason="只建议策略，无参数可调（Q6 裁决：只给动作，不执行）",
             advice=ADVICE, gate=GATE),
    # 24 挑战族：滑块自动尝试（档位 + 单发）
    Strategy(id="slider_attempt", cn="滑块自动尝试", family="挑战", trigger="reactive",
             label="滑块自动试一次",
             intent="滑块能过就过，卡住就别硬刚",
             effect="关掉遇滑块直接放弃；单发只试一次不重试",
             scope=("global", "channel"),
             params=(_enabled("slider_attempt"),
                     Param("slider_attempt.auto", "crawler.slider.auto", "str", "auto"),
                     Param("slider_attempt.single_shot", "crawler.slider.single_shot",
                           "bool", False)),
             decide="crawlers.slider:should_attempt",
             api=("/api/challenge/open",), advice=ADVICE, gate=GATE),
    # 25 挑战族：滑块失败拉黑（每日上限 + 连败次数）
    Strategy(id="slider_guard", cn="滑块失败拉黑", family="挑战", trigger="reactive",
             label="滑块连败就停手",
             intent="反复失败会暴露自动化，也浪费每日额度",
             effect="上限调小更早收手；连败次数调小更快拉黑",
             scope=("global", "channel"),
             params=(_enabled("slider_guard"),
                     Param("slider_guard.daily_cap", "crawler.slider.daily_cap",
                           "int", 20, 0, 1000),
                     Param("slider_guard.max_fails", "crawler.slider.max_fails",
                           "int", 2, 0, 10)),
             decide="crawlers.slider:note_result", api=("/api/challenge/open",), advice=ADVICE, gate=GATE),
    # 26 挑战族：验证码识别（算数/文字/OCR 放大/自动开窗）
    Strategy(id="captcha_solve", cn="验证码识别", family="挑战", trigger="reactive",
             label="验证码自动识别",
             intent="算数、文字、点选这些机器能判的题，不该开窗打扰人",
             effect="关掉某类遇到就等人；点选需要 ddddocr 检测模型；放大倍数影响识别率",
             # r1063 T42：读点已按 `plat` 走参数层（`crawlers/captcha.py::_pval`），
             # 声明跟上——否则用户按渠道关掉某一类题会被静默忽略。
             scope=("global", "channel"),
             params=(_enabled("captcha_solve"),
                     Param("captcha_solve.arithmetic", "crawler.captcha.arithmetic",
                           "bool", True),
                     Param("captcha_solve.text", "crawler.captcha.text", "bool", True),
                     # r1063 T21：点选题（图像定位）——开关必须在目录里，
                     # 否则「配了界面看不到」＝这一族的可配置轴是假的。
                     Param("captcha_solve.click", "crawler.captcha.click",
                           "bool", True),
                     Param("captcha_solve.ocr_scale", "crawler.captcha.ocr_scale",
                           "float", 3.0, 1.0, 10.0),
                     Param("captcha_solve.auto_verify", "crawler.auto_verify",
                           "bool", False)),
             decide="crawlers.captcha:attempt",
             api=("/api/challenge/open",), advice=ADVICE, gate=GATE),
    # 28 通路族：换跑道（r1063 T22）
    #   行为型强风控（极验 v4/天御/reCAPTCHA/人脸）没有通用开源解法，硬解只会把
    #   风控分推高；但同一家渠道的 **App 通路**是另一套会话与指纹，往往还没被拦。
    #   所以这里的动作是「被拦就换跑道」，不是绕过风控。读点在
    #   `core/failover.py::plan_switch`（开关 + 每日上限 + 冷却，禁止来回横跳）。
    Strategy(id="app_fallback", cn="换跑道", family="通路",
             trigger="reactive",
             label="被拦就换条路再采",
             intent="一条通路被行为型风控拦住时，别把整家渠道判死",
             effect="开＝拦了就换 App 再采一次；上限与冷却防来回横跳",
             scope=("global", "channel", "dimension"),
             params=(_enabled("app_fallback"),
                     Param("app_fallback.daily_switches",
                           "crawler.app_fallback.daily_switches",
                           "int", 6, 0, 100),
                     Param("app_fallback.cooldown_s",
                           "crawler.app_fallback.cooldown_s",
                           "int", 1200, 0, 86400)),
             decide="core.failover:plan_switch",
             api=("/api/strategy",), advice=ADVICE, gate=GATE),
    # 27 通路族：PC→H5→API 回退顺序（各 crawler 内 _h5_fallback 实现，无回退顺序的 cfg 键）；
    #   默认只读影子，不擅自动改序（RLP:801）
    #   链路停用开关（r1063 T7 补登记，与读点同一步）：`path_fallback.enabled=false`
    #   只停被点名的 `渠道/维度/链路`，读点在 `core/pacing.py::Pacing.gate_path`
    #   （链路闸门）。它管的是「这条链路还能不能用」，**不是**「先走哪条」——
    #   回退顺序本身仍然只读影子，所以 auto_default 仍是 False。
    Strategy(id="path_fallback", cn="通路回退顺序", family="通路", trigger="proactive",
             label="先走哪条通路",
             intent="某条通路被挡时换路，而不是干等或空跑",
             effect="顺序只读影子改不动；能停被点名的通路",
             scope=("channel", "path"),
             params=(Param("path_fallback.enabled",
                           "crawler.path_fallback.enabled", "bool", True),),
             decide="crawlers.fliggy:_h5_fallback", api=("/api/channel/probe",),
             auto_default=False,
             na_reason="回退顺序由 crawler 内 _h5_fallback 等实现，没有顺序键；"
                       "默认只读影子（RLP:801）", advice=ADVICE, gate=GATE),
    # 28 通路族：退役通路不再拖低健康度（口径在 pacing.note_paced + path_stats）
    Strategy(id="retired_path", cn="退役通路口径", family="通路", trigger="reactive",
             label="退役通路不再拖累",
             intent="退役通路失败不该把健康度算坏、也不该记为无票",
             effect="口径变：退役通路计为克制，不再拖低成功率",
             scope=("channel", "path"), params=(_enabled("retired_path"),
                     ),
             decide="core.pacing:note_paced", api=("/api/channel/probe",),
             na_reason="退役口径由 core.pacing:note_paced + storage.path_stats 判定，"
                       "不是 config 键（L0 既有）", advice=ADVICE, gate=GATE),
)


# ---------------------------------------------------------------- 只读上下文

def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


class _Ctx:
    """一次审计内复用的只读上下文（core/** 1.3MB、webui.py 4.4MB，别每格重读）。"""

    def __init__(self):
        self._prod: Optional[Dict[str, str]] = None
        self._webui: Optional[str] = None
        self._storage: Optional[str] = None
        self._has: Dict[str, bool] = {}
        self._cn_loaded = False
        self._cn: Optional[Dict[str, str]] = None
        self._hits: Dict[str, Tuple[str, ...]] = {}
        self._hit_idx: Optional[Dict[str, Tuple[str, ...]]] = None
        self._pid_hits: Dict[str, Tuple[str, ...]] = {}
        self._names: Dict[str, set] = {}
        self._segs: Dict[str, "re.Pattern"] = {}
        self._routes: Optional[set] = None
        self._strat_body: Optional[str] = None
        self._hard: Optional[Tuple[str, ...]] = None
        self._rc: Dict[str, Tuple[bool, Tuple[str, ...]]] = {}
        self._switches: Optional[Dict[str, Tuple[str, ...]]] = None
        self._decl: Optional[Dict[str, Tuple[str, ...]]] = None
        self._glb: Optional[str] = None
        self._glb_keys: Optional[set] = None
        self._controls: Optional[Dict[str, str]] = None
        self._pid_ctl: Optional[Dict[str, str]] = None
        self._ranges: Optional[str] = None

    # -- 生产代码（core/**、crawlers/**、main.py，**排除本模块自身**） ------
    @property
    def prod(self) -> Dict[str, str]:
        if self._prod is None:
            src: Dict[str, str] = {}
            for pat in PROD_GLOBS:
                for f in sorted(glob.glob(os.path.join(ROOT, pat), recursive=True)):
                    if "__pycache__" in f:
                        continue
                    rel = _rel(f)
                    # `**` 会零级匹配，本模块就在 core/ 下——必须显式排除
                    if rel == SELF_REL:
                        continue
                    src[rel] = _read(f)
            for f in PROD_FILES:
                p = os.path.join(ROOT, f)
                if os.path.exists(p):
                    src[f] = _read(p)
            self._prod = src
        return self._prod

    @property
    def webui(self) -> str:
        if self._webui is None:
            self._webui = _read(os.path.join(ROOT, "webui.py"))
        return self._webui

    def read_hits(self, leaf: str) -> Tuple[str, ...]:
        """哪些生产文件以**配置读取形态**取这个末段：

        `.get("leaf")` / `.get('leaf')` / `obj["leaf"]` / `obj['leaf']`。

        为什么要挑形态而不是只查「出现过这个字符串」：`enabled`、`text`、
        `platforms` 这类词在几十个文件里都会出现（实测 `enabled` 命中 20 个
        文件），只查字面量等于判据恒真。

        r1515：旧实现每问一个末段就把 3MB 生产源码扫一遍（`/api/strategy`
        要问 100+ 个末段，实测 1.4s）。改为**一次扫描建索引**：通用正则抓
        `读取形态 + 引号里的标识符`，之后按末段查表；判据与逐段扫描等价。
        """
        if leaf not in self._hits:
            if self._hit_idx is None:
                idx: Dict[str, set] = {}
                for f, t in self.prod.items():
                    for m in _READ_HIT_RX.finditer(t):
                        idx.setdefault(m.group(1), set()).add(f)
                self._hit_idx = {k: tuple(sorted(v)) for k, v in idx.items()}
            self._hits[leaf] = self._hit_idx.get(leaf, ())
        return self._hits[leaf]

    def _seg_rx(self, seg: str, top: bool) -> "re.Pattern":
        """段的匹配式：顶层段按前缀（配置节名 `crawler` 在代码里是包名
        `crawlers`），更深层段按词边界。"""
        key = ("top:" if top else "word:") + seg
        if key not in self._segs:
            pat = (r"\b%s" % re.escape(seg) if top
                   else r"\b%s\b" % re.escape(seg))
            self._segs[key] = re.compile(pat)
        return self._segs[key]

    def _mentions(self, rel: str, segs: Tuple[str, ...]) -> bool:
        """该文件里是否提到 cfg 的这些父段（全部命中才算）。"""
        text = self.prod.get(rel, "")
        for i, seg in enumerate(segs):
            if not self._seg_rx(seg, top=(i == 0)).search(text):
                return False
        return True

    def read_by_param(self, pid: str) -> Tuple[str, ...]:
        """哪些生产文件通过**参数层**消费这个 pid（`strategy_params.resolve` 读点）。

        为什么需要这条判据：T3 之后 `core/policy.py` 不再按 cfg 点路径取值，
        只调 `strategy_params.resolve("pace_factor.healthy")`——参数层是唯一求值
        入口（继承 + 夹取 + 来源都在那里），比任何一处 `.get("leaf")` 更“真读”。
        判据：**同一个生产文件里**既有 pid 字面量、又提到 `strategy_params` 且真的
        调了 `resolve(`。三个条件缺一不可，所以
        `Param("x", "crawler.nowhere_xyz", …)` 这类伪登记仍然一个文件都不认。

        两个文件不算读点（与 `SELF_REL` 同一条理由：不许自证）：
        本模块（`SELF_REL`，目录里写着 pid）与参数层自身（`PARAMS_REL`，
        docstring 举例里写着 pid）。`tests/**` 不在扫描面里。
        """
        if pid not in self._pid_hits:
            lit = ('"%s"' % pid, "'%s'" % pid)
            self._pid_hits[pid] = tuple(
                f for f, t in self.prod.items()
                if f != PARAMS_REL
                and "strategy_params" in t
                and _RESOLVE_RX.search(t)
                and (lit[0] in t or lit[1] in t))
        return self._pid_hits[pid]

    def declared_cfgs(self, pid: str) -> Tuple[str, ...]:
        """**目录**里这个 pid 声明的 cfg 点路径（`Strategy.params` 里那一份）。

        为什么「可配置」轴的参数层读点要过这一关（复核 2026-11-06 第 6 条）：
        `read_by_param()` 证明的是「这个 pid 被求值过」，而本轴问的是「**这个
        cfg 键**被生产代码读到过」。两者只有在 pid 声明的 cfg 就是手上这个
        cfg 时才等价——参数层 `resolve(pid)` 读的正是声明里的那个路径
        （`core/strategy_params.py::resolve` 按 `p.cfg` 查全局层）。不过这一关，
        一条伪造的
        `Param("breaker_switch.enabled", "crawler.nowhere_xyz.enabled", …)`
        就能借一个**真** pid 的读点把自己点亮：判据退化成身份证检查，
        而不是在读这个键。负控钉这一格：
        `tests/test_r1063_strategy_contract.py::
        test_generic_leaf_needs_parent_corroboration`。

        索引取的是模块级 `STRATEGIES`（真目录），**不是** `audit(strategies=…)`
        传进来的那一份：`pid → cfg` 的对应关系是目录的属性，用被审计对象自己
        的声明去校验它会变成自证（伪造的 Param 自带一份"声明"就永远通过）。
        """
        if self._decl is None:
            idx: Dict[str, set] = {}
            for s in STRATEGIES:
                for p in s.params:
                    idx.setdefault(p.pid, set()).add(p.cfg)
            self._decl = {k: tuple(sorted(v)) for k, v in idx.items()}
        return self._decl.get(str(pid), ())

    def read_by_switch(self, pid: str) -> Tuple[str, ...]:
        """哪些生产文件把 `pid` **作为实参**传进了「能传递走到 `resolve(`」的调用。

        为什么要比 `read_by_param` 更严（复核 2026-11-06 第 6 条）：那个判据
        只要求「同一个文件里既有 pid 字面量、又有 `resolve(`」。于是 pid 写在
        docstring、注释或一张列表里也能点亮它——「可开启」轴因此对**只登记、
        不接线**的开关照样报 `y`（`--strict` 于是恒 0 退出，缺口的唯一证据
        就是评审员的眼睛）。这里改成 AST 判据，三条同时成立：

        ① pid 是某次调用的**实参**（`f("sid.enabled", …)` / `f(pid="…")`）：
           注释、docstring、列表里的字面量不是 `Call` 的实参，一律不算；
        ② 该调用的被调用方**传递地**走得到参数层 `resolve(`：要么就是
           `resolve` 本身，要么是调用图里能到达 `resolve(` 的函数。于是
           `_strat_on("sid.enabled", plat)`（把 pid 交给统一读法）算读点，
           而 `log("sid.enabled")` 不算；
        ③ 本模块自身（`SELF_REL`）与参数层自身（`PARAMS_REL`）不算——目录和
           提供方不许自证。

        已知边界（写下来，别当它更全能）：调用图按**函数名**连边、不跨名字
        解析导入与同名遮蔽，所以是**过近似**——同名函数会互相借力。它够用来
        杀掉「注释/列表里写过即算」这类恒真，但证明不了「传进 resolve 之后
        真的被消费」（那是行为门禁的活：`tests/test_r1063_strategy_axes_closure.py`
        里逐条关掉看行为变）。
        """
        sites = self.switch_sites()
        return sites.get(str(pid), ())

    def switch_sites(self) -> Dict[str, Tuple[str, ...]]:
        """一次算全：`pid 字面量 → 把它交给 resolve 读法的文件`（结论缓存）。

        r1515：旧实现对每个 `FunctionDef` 各跑一次 `ast.walk(node)`，嵌套函数
        被反复遍历——`webui.py` 4.4MB + core/crawlers 3MB 下实测 1.34M 次
        `ast.walk`、13s 全花在这里（`/api/strategy` 首开因此要 9~18s，
        线程被 GIL 占住时连节流溯源骨架都出不来）。改为**一次递归遍历**：
        进入函数时压栈，遇到 `ast.Call` 就把它记到栈上所有函数名下——这与
        「每个函数 walk 自己的子树」语义等价（嵌套函数里的调用同时属于内外
        两层），但每个节点只访问一次。
        """
        if self._switches is not None:
            return self._switches
        trees: Dict[str, "ast.AST"] = {}
        for rel, text in self.prod.items():
            try:
                trees[rel] = ast.parse(text)
            except SyntaxError:      # 坏文件不该让整张审计表哑掉
                continue
        # 调用图：函数名 → 它直接调到的名字（方法按裸名连边，见 docstring 的边界）
        calls_of: Dict[str, set] = {}
        # 每个文件里的调用点：[(被调用者名, 字符串实参)]——第二遍只查表，不再走树
        calls_by_file: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = {}
        for rel, tree in trees.items():
            found: List[Tuple[str, Tuple[str, ...]]] = []
            stack: List[str] = []

            def _visit(node, _rel=rel):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        calls_of.setdefault(child.name, set())
                        stack.append(child.name)
                        _visit(child, _rel)
                        stack.pop()
                        continue
                    if isinstance(child, ast.Call):
                        callee = _callee_name(child.func)
                        for nm in stack:      # 嵌套函数里的调用也属于外层函数
                            calls_of[nm].add(callee)
                        found.append((callee, _str_args(child)))
                    _visit(child, _rel)

            _visit(tree)
            calls_by_file[rel] = found
        reach = {"resolve"}         # 种子：参数层求值入口本身
        changed = True
        while changed:
            changed = False
            for name, callees in calls_of.items():
                if name in reach:
                    continue
                if callees & reach:
                    reach.add(name)
                    changed = True
        sites: Dict[str, set] = {}
        for rel, found in calls_by_file.items():
            if rel in (SELF_REL, PARAMS_REL):
                continue
            for callee, args in found:
                if callee not in reach:
                    continue
                for lit in args:
                    sites.setdefault(lit, set()).add(rel)
        self._switches = {k: tuple(sorted(v)) for k, v in sites.items()}
        return self._switches

    def read_by_code(self, cfg: str) -> Tuple[bool, Tuple[str, ...]]:
        """cfg 键是否真被生产代码读（可配置轴的唯一判据）。

        结论按 cfg 点路径缓存：同一条 cfg 会被「策略 × 渠道」的每一格重复问一次
        （28 条 × 渠道展开，可配置/可调整/语义清晰三条轴都要读它），不缓存等于
        把 3MB 源码扫上千遍——实测 `audit()` 近 10% 的时间花在这上面，而源码在
        一次运行里不会变。缓存只存**结论**，不存源码（源码仍由 `prod` 持有）。

        两条必须同时成立：
        1. **读取形态**：末段以 `.get("leaf")` 或 `["leaf"]` 出现（真读 config
           就这么写）；只作为普通字符串出现不算；
        2. **父段同文件共现**：cfg 除末段外的每一段都得出现在**同一个文件**
           里（顶层段按前缀、更深段按词边界）。于是
           `crawler.breaker.enabled` 只认「读了 `enabled` 又提到 `breaker`」的
           文件，而 `crawler.nowhere_xyz.enabled` 一个文件都不认。

        已知边界：`os.environ` / 运行时拼出来的键名读不出来（本仓库没有这种
        读法）；`grep` 得到的文件列表会写进 note 当证据。
        """
        parts = [p for p in str(cfg or "").split(".") if p]
        if not parts:
            return False, ()
        key = ".".join(parts)
        if key in self._rc:
            return self._rc[key]
        leaf, anc = parts[-1], tuple(parts[:-1])
        hits = self.read_hits(leaf)
        if not hits:
            self._rc[key] = (False, ())
            return self._rc[key]
        both = tuple(f for f in hits if self._mentions(f, anc))
        # 证据排序：文件名与 cfg 父段同名的文件优先（`crawler.captcha.text`
        # 先给 `crawlers/captcha.py`，而不是恰好也读 "text" 的 app_base.py）
        if both:
            stems = set(anc)

            def _rank(f: str) -> Tuple[int, str]:
                return (0 if os.path.basename(f)[:-3] in stems else 1, f)

            both = tuple(sorted(both, key=_rank))
        self._rc[key] = (True, both) if both else (False, hits)
        return self._rc[key]

    # -- webui 路由 ------------------------------------------------------
    def webui_has(self, needle: str) -> bool:
        """webui.py 里是否出现该字面量（4.4MB，结论按 needle 缓存）。"""
        if needle not in self._has:
            self._has[needle] = needle in self.webui
        return self._has[needle]

    def strategy_route_body(self) -> str:
        """`GET /api/strategy` **这一分支**的源码段（到下一个 `elif self.path ==` 为止）。

        为什么不用 `webui_has("/api/strategy")`：那是子串判据，`/api/strategy/halt`
        （T6 的停手路由）也含它。可观测轴要问的是「目录接口这一支里有没有真把
        审计结果接出去」，所以先按**精确字面量**定位分支，再看这一段源码。
        找不到（还没有这条路由）时返回空串。
        """
        if self._strat_body is None:
            w = self.webui
            m = _STRATEGY_ROUTE_RX.search(w)
            if not m:
                self._strat_body = ""
            else:
                j = w.find("elif self.path ==", m.end())
                self._strat_body = w[m.start():
                                      (j if j > m.start() else m.end() + 60_000)]
        return self._strat_body

    def hardcoded_ids(self) -> Tuple[str, ...]:
        """模板里**逐条写死**的 `data-strategy="<sid>"` 名单（第二份声明）。

        为什么缓存：这条判断要扫 4.4MB × 28 个 id，而它只取决于 `webui.py`——
        以前写在 `_ax_visualizable` 里，190 格各扫一遍，实测 `audit()` 87% 的
        时间耗在这一行（12.4s → 0.9s 就是把它提到这里来的）。
        """
        if self._hard is None:
            w = self.webui
            self._hard = tuple(o.id for o in STRATEGIES
                               if 'data-strategy="%s"' % o.id in w)
        return self._hard

    def cn_table(self) -> Optional[Dict[str, str]]:
        """界面中文名兜底表（只解析一次；不存在时也是结论，别再重试）。"""
        if not self._cn_loaded:
            self._cn = _ui_cn_table(self.webui)
            self._cn_loaded = True
        return self._cn

    def routes(self) -> set:
        """`webui.py` 里真实存在的 `self.path == "/api/…"` 路由集合。"""
        if self._routes is None:
            self._routes = set(re.findall(
                r"self\.path\s*==\s*['\"]([^'\"]+)['\"]", self.webui))
        return self._routes

    # -- 可调整：/api/config 的 glb 保存通路 + 页面控件 + 边界表 -----------
    def glb_payload(self) -> str:
        """`/api/config` **保存侧**读 `glb`（= `body["globals"]`）的那一段源码。

        从 `glb = body.get("globals")` 起，到下一个 `elif self.path` 为止——
        别处的 `glb` 一律不算：判据只认「这个键会不会被写回 yaml」。
        """
        if self._glb is None:
            w = self.webui
            i = w.find('glb = body.get("globals")')
            if i < 0:
                i = w.find("glb = body.get('globals')")
            if i < 0:
                self._glb = ""
            else:
                j = w.find("elif self.path ==", i)
                self._glb = w[i:(j if j > i else i + 80_000)]
        return self._glb

    def glb_saved_keys(self) -> set:
        """保存侧真的读过的 glb 键（`glb.get("k")` / `glb["k"]`）。"""
        if self._glb_keys is None:
            seg = self.glb_payload()
            keys = set(re.findall(r"glb\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]", seg))
            keys |= set(re.findall(r"glb\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]", seg))
            self._glb_keys = keys
        return self._glb_keys

    def glb_controls(self) -> Dict[str, str]:
        """页面上「键 → 控件 id」的登记表：`glcell('<中文标签>','<控件 id>','GLB.<键>=…')`。

        这就是「这个键在页面上真有一个能改的控件」的唯一证据——只认 glcell 的
        第二、第三参数同现（`GLB.<键>=` 是控件的 oninput 表达式），别处的
        `GLB.x` 读值不算。T12 的目录驱动控件换成 `data-pid` 形态，见
        `data_pid_controls()`。
        """
        if self._controls is None:
            got: Dict[str, str] = {}
            w = self.webui
            for m in re.finditer(r"glcell\(", w):
                seg = w[m.start():m.start() + 600]
                key = re.search(r"'GLB\.([A-Za-z0-9_]+)\s*=", seg)
                cid = re.search(r"'(glb[A-Za-z0-9_]*)'", seg)
                if key and cid:
                    got.setdefault(key.group(1), cid.group(1))
            self._controls = got
        return self._controls

    def data_pid_controls(self) -> Dict[str, str]:
        """目录驱动控件的登记表：`data-pid="<pid>"` → 控件窗口（含 data-min 等）。"""
        if self._pid_ctl is None:
            got: Dict[str, str] = {}
            w = self.webui
            for m in re.finditer(r"""data-pid\s*=\s*['"]([^'"]+)['"]""", w):
                got.setdefault(m.group(1), w[max(0, m.start() - 200):
                                              m.end() + 400])
            self._pid_ctl = got
        return self._pid_ctl

    def ranges_text(self) -> str:
        """`GLB_RANGES` 与 `GLB_RANGES_DYN` 两张即时校验表的源码段。"""
        if self._ranges is None:
            w = self.webui
            out = [""]
            i = w.find("const GLB_RANGES=")
            if i >= 0:
                j = w.find("function glbCheck(", i)
                out[0] = w[i:(j if j > i else i + 30_000)]
            i = w.find("const GLB_RANGES_DYN=")
            out.append(w[i:i + 4_000] if i >= 0 else "")
            self._ranges = "\n".join(out)
        return self._ranges

    def has_bound(self, cid: str, keys: Sequence[str],
                  window: str = "") -> bool:
        """该参数的控件有没有登记过边界（三种真实形态，读源码）：

        ① `GLB_RANGES` 里 `{id:'<控件 id>'…}`；
        ② `GLB_RANGES_DYN` 里 `pre:'…'` 是控件 id 的前缀（动态生成的控件）；
        ③ 控件自带 `data-min` / `data-max`（T12 目录驱动控件的形态），
           或边界表里直接写着这个参数的键名。
        """
        seg = self.ranges_text()
        if cid and re.search(r"id:\s*'%s'" % re.escape(cid), seg):
            return True
        if cid and cid.startswith("glb"):
            for pre in re.findall(r"pre:\s*'([^']+)'", seg):
                if pre and cid.startswith(pre):
                    return True
        if window and "data-min" in window and "data-max" in window:
            return True
        return any(k and re.search(re.escape(k), seg) for k in keys)

    def declared_ctl(self, cid: str) -> bool:
        """这个控件 id 有没有在**边界/控件登记表**里出现过（`GLB_RANGES` 的
        `{id:'…'}`、或 `GLB_RANGES_DYN` 的 `{pre:'…'}` / `{id:'…',ctl:1}`）。

        为什么它是「页面上真有这颗控件」的凭据：目录驱动的行内控件 id 是**拼**
        出来的（`glb` + cfg 段），源码里看不到逐键字面量；而边界表是**逐个手写**
        的（数字给上下界，布尔/文本框给 `ctl:1` 只登记「有控件」）。谁加参数
        谁登记，漏一个这条参数就报 `n`——判据因此不是恒真。
        """
        if not cid:
            return False
        seg = self.ranges_text()
        if re.search(r"id:\s*'%s'" % re.escape(cid), seg):
            return True
        for pre in re.findall(r"pre:\s*'([^']+)'", seg):
            if pre and cid.startswith(pre):
                return True
        return False

    def row_control_cid(self, p: Param) -> str:
        """目录驱动的行内控件 id（三件齐了才给，否则空串）：

        ① 渲染器真有那个**模板**（`data-pid="'+pid+'"`）——没有它，参数再多也
           只是画个 read-only 值；
        ② 有 id 派生点 `stratCid(`——控件的 DOM id 由它算出来，审计用同一条
           规则（`_row_cid`）复算，两边分叉就会被门禁抓住；
        ③ 该 `kind` 真的会被画成输入控件（`map` 不画，见 `ROW_INPUT_KINDS`）。

        返回 `glbPaceWatch` 这类 id；调用方还要问 `declared_ctl()` / `has_bound()`
        才能证明「有界面、且有界」。
        """
        w = self.webui
        if not _ROW_TPL_RX.search(w):
            return ""
        if "function stratCid(" not in w:
            return ""
        if p.kind not in ROW_INPUT_KINDS:
            return ""
        return _row_cid(p)

    # -- 可统计：台账能不能按策略归集 -------------------------------------
    @property
    def storage(self) -> str:
        """`core/storage.py` 源码（台账口径的唯一住处；只读一次）。"""
        if self._storage is None:
            self._storage = _read(os.path.join(ROOT, "core", "storage.py"))
        return self._storage

    def ledger_strategy_stats(self) -> Tuple[bool, str]:
        """台账有没有「按策略归集」的计数口径。

        两种真形态都认：
        ① 规格字面的聚合键 `strategy:<sid>`（storage.py 里拼出来的键）；
        ② T6 实际落地的账本约定（见 `webui._strategy_scope_of`）：策略 id 写在
           台账 `note` 的 `[<sid>]` 前缀里（`scope` 列是渠道词汇，不许占用），
           于是口径形态是「`strategy_*` 动作族 + `substr(note,…)` 前缀过滤」。

        没有这两种之一 → 这条策略在台账里数不出来（`stats` 轴报 n）。
        """
        txt = self.storage
        if not txt:
            return False, "core/storage.py 读不到，没法统计"
        if "strategy:" in txt:
            return True, "core/storage.py 有 `strategy:<sid>` 聚合键"
        if "strategy_" in txt and re.search(r"substr\(\s*note|LIKE\s*'\[%", txt):
            return True, "core/storage.py 按 `strategy_*` + note 的 `[sid]` 前缀归集"
        return False, ("core/storage.py 没有按策略归集的口径（既没有 `strategy:<sid>` "
                       "聚合键，也没有 `strategy_*` + note `[sid]` 前缀计数）")

    # -- AST：决定点 / 建议器指向的函数是否真存在 -------------------------
    def names(self, rel: str) -> set:
        if rel not in self._names:
            got: set = set()
            try:
                tree = ast.parse(self.prod.get(rel) or _read(os.path.join(ROOT, rel)))
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef)):
                        got.add(node.name)
            self._names[rel] = got
        return self._names[rel]

    def resolve(self, ref: str) -> Tuple[bool, str]:
        """`module:func` → (是否存在, 说明)。支持 `Class.method` 式点路径。"""
        mod, _, attr = str(ref or "").partition(":")
        if not mod or not attr:
            return False, "不是 module:func 形式：%s" % (ref,)
        rel = mod.replace(".", "/") + ".py"
        if not os.path.exists(os.path.join(ROOT, rel)):
            return False, "模块文件不存在：%s" % rel
        names = self.names(rel)
        for part in attr.split("."):
            if part not in names:
                return False, "%s 里没有 %s" % (rel, attr)
        return True, rel


_CTX: Optional[_Ctx] = None

# 参数层读点的形态：真的调了 `resolve(...)`（不是只在注释里提一句）
_RESOLVE_RX = re.compile(r"\bresolve\s*\(")
# r1515：配置读取形态的通用式（`read_hits` 一次扫描建索引）：
# `.get("leaf")` / `.get('leaf')` / `obj["leaf"]` / `obj['leaf']`。
_READ_HIT_RX = re.compile(
    r"""(?:\.get\(\s*|\w\[\s*)['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")


def _callee_name(func) -> str:
    """调用表达式的被调用方名字（`f(…)` / `obj.f(…)` → `f`；其它 → 空串）。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _str_args(call) -> Tuple[str, ...]:
    """一次调用里的字符串字面量**实参**（位置参数 + 关键字参数）。"""
    out: List[str] = []
    for arg in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
    return tuple(out)


def _ctx() -> _Ctx:
    """进程内复用一份上下文（源码在一次运行里不会变）。"""
    global _CTX
    if _CTX is None:
        _CTX = _Ctx()
    return _CTX


def _default_plats() -> Tuple[str, ...]:
    """默认按已登记渠道展开（与 channel_contract 同一口径）。"""
    try:
        from core.channels import APP_CHANNELS, BROWSER_CHANNELS
        return tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)
    except Exception:  # pragma: no cover - 依赖环境
        return ("*",)


def _ui_cn_table(webui: str) -> Optional[Dict[str, str]]:
    """`webui.py` 里的策略中文名兜底表 `STRATEGY_CN = {…}`（T12 建）。

    不存在时返回 None——可识别轴就只核目录自身；存在时逐条比对，
    漏一个 id 或中文名不一致都报 `n`（那时界面会露英文 id）。
    """
    m = re.search(r"STRATEGY_CN\s*=\s*\{", webui)
    if not m:
        return None
    i = webui.index("{", m.start())
    depth = 0
    body = ""
    for j in range(i, min(len(webui), i + 200_000)):
        ch = webui[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = webui[i:j + 1]
                break
    if not body:
        return None
    return dict(re.findall(
        r"['\"]?([a-z][a-z0-9_]*)['\"]?\s*:\s*['\"]([^'\"]*)['\"]", body))


# ---------------------------------------------------------------- 各轴探针

def _ax_configurable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """cfg 键必须被生产代码**以配置读取形态**读到——这是「能勾」与「勾了有意」
    的分界线。两种读点各算一次命中（细节见 `_Ctx.read_by_code` / `read_by_param`）：

    ① **点路径读取**：末段出现在 `.get("leaf")` / `["leaf"]` 这类表达式里，
       且 cfg 的父段出现在同一个文件（顶层段按前缀，更深段按词边界）；
    ② **参数层读取**：该 pid 被某个生产文件用 `strategy_params.resolve()` 现读
       （T3/T4 起，`core/policy.py` 只走这一条）。这一条**必须先过
       `_Ctx.declared_cfgs()`**：pid 得是目录里**以这个 cfg 声明过**的那一个
       ——否则「一个真 pid + 一个伪造的 cfg」会借读点把自己点亮，判据就从
       「读过这个键」退化成「这个 pid 存在」（复核 2026-11-06 第 6 条；负控
       `tests/test_r1063_strategy_contract.py::
       test_generic_leaf_needs_parent_corroboration`）；
    ③ 生产扫描集**不含本模块自身、也不含参数层自身**（否则目录/提供方里写过的
       pid 会自己作证，判据当场恒真）。

    没有参数 → `na` + `na_reason`（新键的登记责任交给加读点的那一批任务）。
    """
    if not s.params:
        return NA, "参数为空：%s" % (s.na_reason or "无 cfg 键可调")
    missing: List[str] = []
    seen: List[str] = []
    for p in s.params:
        ok, hits = ctx.read_by_code(p.cfg)
        if ok:
            seen.append("%s←%s" % (p.cfg, hits[0]))
            continue
        via = ctx.read_by_param(p.pid) \
            if p.cfg in ctx.declared_cfgs(p.pid) else ()
        if via:
            seen.append("%s←%s（参数层 %s）" % (p.cfg, via[0], p.pid))
            continue
        missing.append(p.cfg)
    if missing:
        return N, ("生产代码没读这些键（既没有 `.get(末段)` 的点路径读取，"
                   "也没有 `strategy_params.resolve(pid)` 的读点）：%s"
                   "——勾了也不会生效" % "、".join(missing))
    return Y, "%d 个键都在生产代码里读到（%s）" % (len(seen), "；".join(seen[:3]))


def _ax_observable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """`/api/strategy` **精确路由**存在，且**服务于它的那段源码**里真调了
    `matrix_text()` / `audit(`（不是「代码里提过这个词」）。

    两条判据都被收紧过（复核 2026-11-06 Important），原因是旧写法会白送分：
    ① 旧判据用子串 `/api/strategy`——`/api/strategy/halt`（T6 的停手路由，只写
       不读）就含这个子串，于是「能停手」被当成「能看到生效值」，两件事被混成
       一件（Spec §4.1 末尾专门写死过：可观测≠可可视化，这里同理）；
    ② 旧判据用子串 `audit`——界面里一个 `class="auditbox"`、注释里一句「audit
       一下」就能点亮。判据要的是「这条路由真把审计结果接了出去」，所以只认
       调用形态 `audit(` / `matrix_text(`。
    于是「路由不在」与「路由在但没接矩阵」是两种不同的 `n`，说明里分别点名。
    """
    if STRATEGY_ROUTE not in ctx.routes():
        return N, ("界面看不到生效值：缺**精确**路由 `self.path == \"%s\"`"
                   "（`/api/strategy/halt` 这类子串不算——那是写路径，T12 建）"
                   % STRATEGY_ROUTE)
    body = ctx.strategy_route_body()
    if not body:
        return N, ("`%s` 分支源码取不到（路由字面量不是精确相等？）："
                   "没法证明矩阵接了出去" % STRATEGY_ROUTE)
    hit = _MATRIX_CALL_RX.search(body)
    if not hit:
        return N, ("`%s` 分支里没有**真调** `audit(` / `matrix_text(`：矩阵/生效值"
                   "没接到界面上（注释里提一句、CSS 类名叫 audit 都不算）"
                   % STRATEGY_ROUTE)
    return Y, ("`%s` 精确路由 + 该分支真调 `%s(`（目录→界面同源，与 CLI 同一份）"
               % (STRATEGY_ROUTE, hit.group(0)[:-1].strip()))


def _ax_intervenable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """api 里的每个路由字面量都必须在 webui.py 真存在。"""
    if not s.api:
        return N, "没有声明干预路由——出事只能改 config 重启（T6 补入口）"
    routes = ctx.routes()
    miss = [r for r in s.api if r not in routes]
    if miss:
        return N, "webui.py 里没有这些路由：%s（T6 建）" % "、".join(miss)
    return Y, "干预路由真实存在：%s" % "、".join(s.api)


def _ax_toggleable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """有 `bool` 开关**而且它真的被参数层读到**才算「能开关」。

    旧判据只问「有没有 `kind="bool"` 的参数」，于是**任何**登记成 bool 的键
    都白送一个 `y`：`Param("<sid>.enabled", "crawler.nowhere", "bool", True)`
    这种一条线都没接的假开关照样绿，`--strict` 恒 0 退出（复核 2026-11-06
    第 6 条：判据自证）。现在每个 `<sid>.enabled` 都必须过
    `_Ctx.read_by_switch()`：pid 得**作为实参**交给某个「传递地能走到
    `strategy_params.resolve(`」的调用——也就是消费方真把它交给参数层求值，
    而不是在注释/列表里提一句。

    负控（判据不恒真）：`tests/test_r1063_strategy_axes_closure.py::
    test_toggleable_reports_n_for_a_switch_nobody_resolves` 造一条只登记、
    没有读点的开关，这一轴必须报 `n`。

    只建议档（`auto_default=False`）且本来就没有开关参数时仍按 `y`：它没有
    自动动作可关，是**结构上不适用**，不是缺口。
    """
    bools = [p.pid for p in s.params if p.kind == "bool"]
    if not bools:
        if not s.auto_default:
            return Y, "只建议档（auto_default=False）：没有自动动作，无需开关"
        return N, "缺 enabled 开关参数（只有数值/字符串参数，只能调不能关）"
    pid = s.id + ".enabled"
    if pid not in bools:
        return N, ("没有 `<策略>.enabled` 这个开关（bool 参数是 %s）：界面上的"
                   "「关掉」无处可落，只能改数值" % "、".join(bools))
    via = ctx.read_by_switch(pid)
    if not via:
        return N, ("开关只是登记了参数、**没有真读点**：生产代码里没有任何调用把 "
                   "%r 交给 `strategy_params.resolve(` 求值（注释/列表里提一句不算，"
                   "只 `.get()` 读原始键也不算——那样渠道覆盖照旧被忽略）。"
                   "勾上它也不会生效" % (pid,))
    return Y, "开关参数：%s（读点：%s）" % ("、".join(bools), via[0])


def _ax_interruptible(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """中断动作：停手窗口（halt/resume）与单次采集预算（probe/cancel）。"""
    cand = [r for r in s.api if r in HALT_ROUTES or r.endswith("/cancel")]
    if not cand:
        return NA, ("本策略没有中断语义：%s 不需要「中途叫停」"
                    % (s.cn or s.id))
    routes = ctx.routes()
    miss = [r for r in cand if r not in routes]
    if miss:
        return N, "声明了中断路由但 webui.py 里还没有：%s（T6 建）" % "、".join(miss)
    return Y, "中断路由真实存在：%s" % "、".join(cand)


def _ax_distinguishable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """界面能把「自动/人工」与「谁说了算」分开：data-strategy + 来源前缀。"""
    miss = []
    if not ctx.webui_has("data-strategy"):
        miss.append("data-strategy 落点")
    if not (ctx.webui_has("auto_") and ctx.webui_has("strategy_")):
        miss.append("auto_ / strategy_ 来源前缀")
    if miss:
        return N, "分不出谁说了算：缺 %s（T12/T13 建）" % "、".join(miss)
    return Y, "data-strategy + auto_/strategy_ 来源前缀齐全"


def _ax_identifiable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """id 唯一 + 中文名唯一且非空 + 族合法；有界面兜底表时逐条比对。"""
    miss: List[str] = []
    cn = (s.cn or "").strip()
    if not cn:
        miss.append("中文名为空")
    elif cn == s.id:
        miss.append("中文名与 id 相同（界面会露英文 id）")
    if not re.match(r"^[a-z][a-z0-9_]*$", s.id or ""):
        miss.append("id 不是小写蛇形：%r" % (s.id,))
    if s.family not in FAMILIES:
        miss.append("族不在枚举内：%s" % (s.family,))
    dups = [o.id for o in STRATEGIES if o.cn == cn and o.id != s.id]
    if dups:
        miss.append("中文名与 %s 重复" % "、".join(dups))
    table = ctx.cn_table()
    if table is None:
        tail = "（界面兜底表 STRATEGY_CN 待 T12 建）"
    elif s.id not in table:
        miss.append("界面兜底表 STRATEGY_CN 缺该 id")
        tail = ""
    elif table.get(s.id) != cn:
        miss.append("界面兜底表的中文名不一致：%s" % table.get(s.id))
        tail = ""
    else:
        tail = "（与界面兜底表一致）"
    if miss:
        return N, "；".join(miss)
    return Y, "%s · %s · %s%s" % (s.id, cn, s.family, tail)


def _ax_advisable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """建议器必须真存在（AST 里找得到），否则「可建议」是空话。"""
    if not s.advice:
        return N, "没有建议器：这条策略只出数字不出动作（T13 建）"
    ok, why = ctx.resolve(s.advice)
    if not ok:
        return N, "advice 指不到函数（%s）：%s" % (s.advice, why)
    return Y, "建议器 %s 存在（返回动作码+中文说明）" % s.advice


def _ax_independent(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """能否按渠道独立覆盖：只全局生效的调度类结构上做不到，记 na 并写明。"""
    if "channel" in s.scope:
        return Y, "支持按渠道覆盖（scope=%s）" % "/".join(s.scope)
    return NA, ("只支持全局粒度（scope=%s）：%s 按渠道拆开会让节奏互相打架"
                % ("/".join(s.scope) or "空", s.cn or s.id))


def _ax_semantics(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """枚举合法 + 参数齐备 + 决定点真实存在（Spec §4：decide 要指得到）。"""
    miss: List[str] = []
    if s.trigger not in TRIGGERS:
        miss.append("trigger 取值非法：%s" % (s.trigger,))
    if not s.scope:
        miss.append("scope 为空")
    bad_scope = [x for x in s.scope if x not in SCOPES]
    if bad_scope:
        miss.append("scope 取值非法：%s" % "、".join(bad_scope))
    if s.family not in FAMILIES:
        miss.append("族不在枚举内：%s" % (s.family,))
    for p in s.params:
        if p.kind not in KINDS:
            miss.append("%s 的 kind 非法：%s" % (p.pid, p.kind))
        if not (p.lo is None or p.hi is None) and p.lo > p.hi:
            miss.append("%s 的上下界反了" % p.pid)
    if not s.params and not (s.na_reason or "").strip():
        miss.append("params 为空却没写 na_reason（说不出为什么不登记键）")
    if not (s.decide or "").strip():
        miss.append("没有 decide 决策点")
    else:
        ok, why = ctx.resolve(s.decide)
        if not ok:
            miss.append("decide 指不到函数：%s（%s）" % (s.decide, why))
    if miss:
        return N, "；".join(miss)
    return Y, ("trigger=%s / scope=%s / %d 个参数；决定点 %s 真实存在"
               % (s.trigger, "/".join(s.scope), len(s.params), s.decide))


# ------------------------------------------------- 目标扩句新增的五轴（Spec §4.1）
#
# 前十条轴问「有没有接线」，这五条问「用户能不能用」。三条要等界面/台账真的
# 建起来才可能变 `y`（Ruling P5：十五轴全绿在 T12）：判据照旧读真实登记点，
# 缺什么就在 note 里点名，绝不因为「还没建」就把判据放宽成恒真。

def _ax_visualizable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """可可视化：界面上真有这条策略的**渲染落点**（渲染级证据，不接受「代码里
    提过这个词」）。

    判据三件（同一份 `webui.py` 里同时成立）：
    ① `data-strategy` 行模板——每行由它带出策略 id；
    ② `data-family`——行上带族，芯片/分组才挂得住；
    ③ **目录驱动**：id 来自策略目录（`/api/strategy` 或 `STRATEGIES`），
       不许逐条写死 `data-strategy="<sid>"`（那是第二份声明，加一条策略就漏）。

    **本轴的两半，谁负责写死在这里**（Spec §4.1）：
    * 前半「界面上有渲染落点」= T12b 的目录驱动渲染器（`panel-pacing` 重构为
      「策略控制」）——**已到位**，于是三件判据成立、本轴转 `y`；
    * 后半「uitest 真点得到」= T14 的界面用例。Spec §4.1 要求前者是**渲染级
      证据**（不是「代码里提过」），后者由 T14 断言 `data-strategy` 行真出现在
      渲染后的 DOM 里且可点——本轴不替它作证：「代码里有这行」与「渲染出来
      点得到」是两件事，混起来就是本项目最恨的「假装生效」。
    """
    miss: List[str] = []
    if not ctx.webui_has("data-strategy"):
        miss.append("`data-strategy` 行模板")
    if not ctx.webui_has("data-family"):
        miss.append("`data-family`（行上带族）")
    if not (ctx.webui_has("/api/strategy") or ctx.webui_has("STRATEGIES")
            or ctx.webui_has("strategy_contract")):
        miss.append("从策略目录取 id（`/api/strategy` 或 `STRATEGIES`）")
    hard = list(ctx.hardcoded_ids())
    if hard:
        miss.append("模板里写死了这些 id（第二份声明）：%s" % "、".join(hard[:3]))
    if miss:
        return N, ("界面上没有这条策略的渲染落点：缺 %s（T12b 建目录驱动渲染器，"
                   "T14 补 uitest 点击证据）" % "、".join(miss))
    return Y, ("渲染器从目录取 id：`data-strategy` 行模板 + `data-family`，"
               "策略 id %s 由目录带出（uitest 那半由 T14 断言）" % s.id)


def _row_cid(p: Param) -> str:
    """参数 → 行内控件的 DOM id（`webui.py::stratCid` 的 Python 同构）。

    `crawler.policy.pace.watch` → `glbPaceWatch`；`crawler.breaker.base_s` →
    `glbBreakerBase`；`android.fetch_budget_s` → `glbFetchBudget`。
    规则与本仓库的 JS 实现逐字对应（去掉顶层/分组段与 `_s` 后缀，其余段驼峰化），
    **两边对账的门禁**在 `tests/test_r1063_strategy_axes_closure.py`——分叉时
    面板上的 id 与边界表里的 id 会对不上，越界校验静默失效。
    """
    segs = [x for x in str(p.cfg or p.pid or "").split(".") if x]
    out: List[str] = []
    for i, seg in enumerate(segs):
        if i == 0 or seg in CID_DROP:
            continue
        if seg.endswith("_s"):
            seg = seg[:-2]
        out.append(re.sub(r"(^|_)([a-z0-9])",
                          lambda m: m.group(2).upper(), seg))
    return "glb" + "".join(out)


def _param_keys(p: Param) -> Tuple[str, ...]:
    """一个参数在界面/保存侧可能用的键名：cfg 末段（既有 glb 扁平键）与
    pid（`strategy_overrides` 覆盖字典的键，Spec §5 就这么定）。"""
    leaf = str(p.cfg or "").split(".")[-1]
    return tuple(k for k in (leaf, p.pid) if k)


def _ax_adjustable(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """可调整：界面上至少有一个参数**能改、能存回去、有边界**（Spec §4.1）。

    三件同时成立才算 `y`（都读真实登记点，少一件就是「改了不生效」）：
    ① 保存侧：`/api/config` 的 `glb` 段真读这个键（`glb.get("k")` / `glb["k"]`），
       或读**参数值表**（键就是 pid）：T12a 起是覆盖字典
       `glb.get("strategy_overrides")`（作用域串 → {pid: 值}），T12b 起
       「策略控制」面板走 `glb.get("strategy_values")`（pid → 全局值，写到
       `Param.cfg` 点路径）。两条都是**真读**：判据只认 `glb` 段里出现过的键名；
       两条都没有 → 页面改了写不回 yaml；
    ② 渲染侧：页面上有绑定这个键的控件——既有形态 `glcell(…,'GLB.<键>=…')`，
       或 `data-pid="<pid>"` 字面量，或 **T12c 裁决③的目录驱动形态**（见下）；
    ③ 边界：**数值**参数还得有边界登记（`GLB_RANGES` 按控件 id、`GLB_RANGES_DYN`
       按前缀、或控件自带 `data-min/data-max`）——没边界就会越界静默失效。
       bool/str/map/list 没有数值边界，②即可。

    **T12c 裁决（`adjustable` 的判据口径缺口，不是界面缺口）**：配置页是**目录
    驱动**的（`data-pid` 由 `/api/strategy` 载荷拼出来），源码里没有 60 多个逐键
    字面量；为了让这一轴变绿去手写 60 份 `data-pid="<pid>"` 正好是最恨的「第二份
    声明」。所以本轴认可第三条证据链（`_Ctx.row_control_cid`）：

        渲染模板 `data-pid="'+pid+'"` + 派生点 `stratCid(` + kind 画得出控件
        + 该参数**派生出来的控件 id 在 `GLB_RANGES`/`GLB_RANGES_DYN` 登记过**

    为什么不是恒真：登记是**逐参数**手写的（数值给上下界，布尔/文本框给
    `ctl:1` 只声明「这颗控件存在」），谁加参数谁登记，漏一个就是 `n`；负控见
    `tests/test_r1063_strategy_axes_closure.py`。**uitest 那半**（真点一下控件、
    看值进 `GLB.strategy_values` 再落盘）仍由 T14 断言，本轴不替它作证。

    参数为空的策略记 `na` + `na_reason`（只建议类、口径类）。
    """
    if not s.params:
        return NA, "没有可改的参数：%s" % (s.na_reason or "无 cfg 键可调")
    if "/api/config" not in ctx.routes():
        return N, "webui.py 里没有 `/api/config` 保存路由：改了存不回去"
    saved = ctx.glb_saved_keys()
    if not saved:
        return N, ("`/api/config` 的 glb 侧没有保存通路（缺 `glb = body.get("
                   "\"globals\")` 那一段），界面上的数改不进 yaml")
    ctrls = ctx.glb_controls()
    pids = ctx.data_pid_controls()
    # 保存侧认三条真实通道（Spec §5「不新开一路」）：
    #   ① 扁平键：`glb.get("min_gap_s")`——今天绝大多数参数就这么存；
    #   ② 覆盖字典：`glb.get("strategy_overrides")`——作用域串 → {pid: 值}；
    #   ③ 参数值表：`glb.get("strategy_values")`——pid → 全局值（T12b 的
    #      「策略控制」面板把行内控件写进这里，后端落到 `Param.cfg` 点路径）。
    # ②③ 的键都是 `Param.pid`，所以只要是登记过的 pid，都能从这两条路写回 yaml。
    via_overrides = ("strategy_overrides" in saved
                     or "strategy_values" in saved)
    miss: List[str] = []
    for p in s.params:
        keys = _param_keys(p)
        hit = next((k for k in keys if k in saved), "")
        if not hit and via_overrides:
            hit = p.pid
        if not hit:
            miss.append("%s（保存侧的 glb 没读 %s）" % (p.cfg, "/".join(keys)))
            continue
        cid, window = "", ""
        for k in keys:
            if k in ctrls:
                cid = ctrls[k]
                break
        if not cid:
            for k in keys:
                if k in pids:
                    cid, window = "data-pid:" + k, pids[k]
                    break
        driven = False
        if not cid:
            # 目录驱动形态（T12c 裁决）：id 现算，**必须**在边界/控件登记表
            # 里出现过才算「页面上真有这颗控件」。
            cid = ctx.row_control_cid(p)
            driven = bool(cid)
            if cid and not ctx.declared_ctl(cid):
                miss.append("%s（目录驱动控件的 id %s 没在 GLB_RANGES/"
                            "GLB_RANGES_DYN 登记，等于没有边界）" % (p.cfg, cid))
                continue
        if not cid:
            miss.append("%s（页面上没有绑定 %s 的控件）" % (p.cfg, hit))
            continue
        if p.kind in ("int", "float") and not ctx.has_bound(cid, keys, window):
            miss.append("%s（数值控件 %s 没有登记边界，越界会静默失效）"
                        % (p.cfg, cid))
            continue
        tail = ("边界已登记" if p.kind in ("int", "float")
                else "非数值参数，无边界")
        how = "目录驱动行内控件" if driven else "控件"
        return Y, ("界面可改且能回读：%s 存进 glb.%s，%s %s，%s"
                   % (p.cfg, hit, how, cid, tail))
    return N, ("界面上改不了这条策略的参数：%s（T12c：要么按目录出控件并把"
               "控件 id 登记进 GLB_RANGES/GLB_RANGES_DYN）" % "；".join(miss[:3]))


def _ax_clear(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """可清晰：`label` 是策略行上给人看的那一行字（Spec §4.1）。

    判据：非空、≤20 字、**中文短句**（只许中文 + 数字 + `·（）/`）、不含裸 id、
    不照抄中文名。出现英文就等于把内部标识漏给用户。
    """
    label = (s.label or "").strip()
    if not label:
        return N, ("没有标签（label）：策略行只能显示 id 或中文名，用户看不出"
                   "它现在是什么状态")
    miss: List[str] = []
    if len(label) > 20:
        miss.append("标签 %d 字，超过 20 字：%s" % (len(label), label))
    if s.id and s.id in label:
        miss.append("标签里露了裸 id（%s）" % s.id)
    bad = sorted({ch for ch in label
                  if not ("\u4e00" <= ch <= "\u9fff" or ch in LABEL_CHARS)})
    if bad:
        miss.append("标签里有英文/半角标点/空格：%s" % " ".join(bad[:6]))
    if (s.cn or "").strip() and label == s.cn.strip():
        miss.append("标签照抄了中文名（换句人话说「它是什么状态」）")
    if miss:
        return N, "；".join(miss)
    return Y, "标签 %d 字：%s" % (len(label), label)


def _ax_intent(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """可意图理解：`intent`（它在防什么/图什么）+ `effect`（改了会发生什么），
    各 ≤40 字（Spec §4.1）。

    本轴只核**内容在不在、够不够短**——这两句是目录直出的唯一来源，界面里不许
    再写第二份；「两者在策略行的说明位真渲染」由 T13 的界面断言接管。
    """
    it = (s.intent or "").strip()
    ef = (s.effect or "").strip()
    miss: List[str] = []
    if not it:
        miss.append("缺 intent（它在防什么/图什么）")
    elif len(it) > 40:
        miss.append("intent %d 字，超过 40 字" % len(it))
    if not ef:
        miss.append("缺 effect（改了会发生什么）")
    elif len(ef) > 40:
        miss.append("effect %d 字，超过 40 字" % len(ef))
    if miss:
        return N, "；".join(miss)
    return Y, "intent %d 字 / effect %d 字：%s｜%s" % (len(it), len(ef), it, ef)


def _ax_stats(s: Strategy, plat: str, ctx: _Ctx) -> Tuple[str, str]:
    """可统计：台账能按策略聚出「干预 N 次 / 生效 M 次 / 样本 K」（Spec §4.1）。

    判据两件：
    ① `core/storage.py` 有按策略归集的计数口径（`strategy:<sid>` 聚合键，或 T6
       落地的「`strategy_*` 动作族 + note 的 `[sid]` 前缀」，见 `_strategy_scope_of`）；
    ② `/api/strategy` 真的把它售出（没有这条路由，数出来了也没人看得见）。

    只建议、从不执行的策略（`auto_default=False`）记 `na` + 理由——规格允许的
    唯一一种 na。参数类策略「可被计数」不要求计数非零（今天可能一次都没动过）。
    """
    if not s.auto_default:
        return NA, ("只建议、从不执行（auto_default=False）：没有可统计的执行次数"
                    "——%s" % (s.na_reason or "无自动动作"))
    miss: List[str] = []
    ok, why = ctx.ledger_strategy_stats()
    if not ok:
        miss.append(why)
    if "/api/strategy" not in ctx.routes():
        miss.append("/api/strategy 没把 stats 售出（webui.py 里没有该路由）")
    if miss:
        return N, "台账里数不出这条策略：%s（T12 建口径）" % "；".join(miss)
    return Y, ("按策略归集：%s；干预记 `strategy_*`、策略 id 取 note 的 `[%s]` 前缀"
               % (why, s.id))


PROBES = {
    "configurable": _ax_configurable,
    "observable": _ax_observable,
    "intervenable": _ax_intervenable,
    "toggleable": _ax_toggleable,
    "interruptible": _ax_interruptible,
    "distinguishable": _ax_distinguishable,
    "identifiable": _ax_identifiable,
    "advisable": _ax_advisable,
    "independent": _ax_independent,
    "semantics": _ax_semantics,
    "visualizable": _ax_visualizable,
    "adjustable": _ax_adjustable,
    "clear": _ax_clear,
    "intent": _ax_intent,
    "stats": _ax_stats,
}


# ---------------------------------------------------------------- 对外接口

def audit(plats: Optional[Sequence[str]] = None,
          strategies: Optional[Iterable[Strategy]] = None,
          ctx: Optional[_Ctx] = None) -> List[Row]:
    """策略 → 每轴一格。支持渠道覆盖的策略按渠道展开（`plat="*"` = 不分渠道）。

    未知/未登记的取值不会抛异常，整行按「缺什么、看哪里」报 `n`/`na`。
    """
    ctx = ctx or _ctx()
    items = tuple(strategies) if strategies is not None else STRATEGIES
    plats = tuple(plats) if plats else _default_plats()
    rows: List[Row] = []
    for s in items:
        targets = plats if "channel" in s.scope else ("*",)
        for plat in targets:
            for axis in AXIS_IDS:
                state, note = PROBES[axis](s, plat, ctx)
                rows.append(Row(s.id, plat, axis, state, note))
    return rows


def defects(rows: Optional[Sequence[Row]] = None) -> List[Row]:
    """只返回 `state == "n"` 的格（缺陷清单；`na` 不算缺陷）。"""
    rows = list(rows) if rows is not None else audit()
    return [r for r in rows if r.state == N]


def _worst(states: Sequence[str]) -> str:
    if N in states:
        return N
    if NA in states:
        return NA
    return Y


def _cells(rows: Sequence[Row],
           items: Optional[Sequence[Strategy]] = None
           ) -> List[Tuple[str, str, str, Optional[Row]]]:
    """把审计行压成「每条策略 × 每轴一格」（同一策略的多渠道取最差值）。

    返回 `(sid, axis, state, 代表该状态的那一格)`；`items` 为空时按**行里出现
    过的**策略出（顺序仍按目录），这样传进来的子集也能压。

    **矩阵文本与 `/api/strategy` 的 `matrix` 段都从这里取**：「哪一格最差、
    该拿哪句说明」本身也是判据的一部分，两处各写一份就会在某一轮悄悄分叉
    （CLI 说全绿、面板说有一格 n，是最难查的一类不一致）。
    """
    by: Dict[Tuple[str, str], List[Row]] = {}
    for r in rows:
        by.setdefault((r.sid, r.axis), []).append(r)
    if items is None:
        seen = {r.sid for r in rows}
        items = tuple(s for s in STRATEGIES if s.id in seen)
    out: List[Tuple[str, str, str, Optional[Row]]] = []
    for s in items:
        for axis in AXIS_IDS:
            cells = by.get((s.id, axis)) or []
            if not cells:
                out.append((s.id, axis, N, None))
                continue
            state = _worst([c.state for c in cells])
            out.append((s.id, axis, state,
                        next((c for c in cells if c.state == state), cells[0])))
    return out


def matrix(plats: Optional[Sequence[str]] = None,
           strategies: Optional[Iterable[Strategy]] = None,
           rows: Optional[Sequence[Row]] = None) -> List[dict]:
    """紧凑矩阵：`[{sid, axis, state, note}]`——给界面/接口用（每条策略×每轴一格）。

    与 `matrix_text()` 走**同一个** `_cells()` 聚合，所以 `GET /api/strategy` 的
    `matrix` 段、CLI 的矩阵、`--strict` 的缺陷判定看到的是同一批结论。

    `rows` 可以传进来复用一次已经算好的 `audit()`：一条 3000 格的审计约 1 秒，
    界面开一次面板跑两遍没有意义（`/api/strategy` 就是这么调的）。
    """
    if rows is None:
        items = tuple(strategies) if strategies is not None else STRATEGIES
        rows = audit(plats=plats, strategies=items)
    else:
        items = tuple(strategies) if strategies is not None else None
    return [{"sid": sid, "axis": axis, "state": state,
             "note": (row.note if row is not None else "没有求值")}
            for sid, axis, state, row in _cells(list(rows), items)]


def matrix_text(plats: Optional[Sequence[str]] = None,
                strategies: Optional[Iterable[Strategy]] = None) -> str:
    """策略 × 十五轴的汇总矩阵（同一策略的多渠道格取最差值）+ 缺陷清单。"""
    items = tuple(strategies) if strategies is not None else STRATEGIES
    rows = audit(plats=plats, strategies=items)
    # 列宽 5：十五轴里有 5 字的中文名（可意图理解），截到 4 字会变成
    # 「可意图理」——矩阵是给人看的，宁可列宽一点也别把轴名截断。
    head = ("策略".ljust(20) + "中文名".ljust(22)
            + " ".join(AXIS_CN[a][:5].rjust(5) for a in AXIS_IDS))
    lines = [head, "-" * len(head)]
    glyph = {Y: "√", N: "×", NA: "—"}
    counts = {Y: 0, N: 0, NA: 0}
    cells_by = {(sid, axis): state
                for sid, axis, state, _row in _cells(rows, items)}
    for s in items:
        cells = []
        for axis in AXIS_IDS:
            state = cells_by.get((s.id, axis), N)
            counts[state] = counts.get(state, 0) + 1
            cells.append(glyph.get(state, "?").rjust(4))
        lines.append(s.id.ljust(20) + s.cn.ljust(22) + " ".join(cells))
    lines.append("")
    bad = [r for r in rows if r.state == N]
    n_row = [r for r in rows if r.state == NA]
    if not bad:
        lines.append("全部 %d 条 × %d 轴：无缺陷（na %d 格，结构上不适用）"
                     % (len(items), len(AXIS_IDS), len(n_row)))
    else:
        lines.append("缺陷 %d 处（按策略×轴去重后 %d 条）："
                     % (len(bad), len({(r.sid, r.axis) for r in bad})))
        seen = set()
        for r in bad:
            key = (r.sid, r.axis)
            if key in seen:
                continue
            seen.add(key)
            lines.append("  [%s] %s：%s" % (AXIS_CN[r.axis], r.sid, r.note))
    lines.append("汇总：y %d 格 / n %d 格 / na %d 格（%d 条策略 × %d 轴，"
                 "渠道展开 %d 家）"
                 % (counts.get(Y, 0), counts.get(N, 0), counts.get(NA, 0),
                    len(items), len(AXIS_IDS),
                    len({r.plat for r in rows if r.plat != "*"})))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    # 门禁以 UTF-8 解码 stdout（subprocess encoding="utf-8"），
    # 而 Windows 控制台默认 GBK：这里统一按 UTF-8 输出，避免中文变乱码。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - 老解释器/被重定向
            pass
    if "--json" in argv:
        payload = [
            {"sid": r.sid, "plat": r.plat, "axis": r.axis,
             "state": r.state, "note": r.note}
            for r in audit()
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print(matrix_text())
    if "--strict" in argv:
        return 1 if defects() else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

