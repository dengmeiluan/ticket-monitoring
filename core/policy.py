# -*- coding: utf-8 -*-
"""统一策略层：把四本账收敂成「这个渠道现在该怎么做」的唯一决定。

为什么需要它（散着判会互相打架）
--------------------------------
现在每个部件都在**各自**判：

* `ChannelBreaker` 判「冷却多久」（只看 HTTP 拒绝与挑战）；
* `Pacing` 判「这一轮要不要跑、跑多快」（只看 TTL 与令牌桶）；
* `riskscore` 判「风险多少分、该停还是该换身份」（只看信号加权）；
* `yield_stats` 判「成功率多少、间隔建议多少」（只看产量）。

四套结论合在一起就会出现矛盾的决定：熔断器说「停 40 分钟」，产量账说
「下界 0.95、可以 0.8× 加速」，登录账说「还能再试」。谁先谁后取决于调用
顺序——这是最难查的一类 bug：**每个部件单独看都对，合起来是错的**。

本模块只做一件事：**给定同样的输入，输出同一个决定**。

决定的内容（每渠道一份）
------------------------
============  ==========================================================
字段          含义
============  ==========================================================
`state`       healthy / watch / degraded / blocked / rehab
`allow`       本轮允不允许发起采集
`stop_until`  什么时候可以再来（epoch 秒；0=不用等）
`pace_factor` 间隔倍率（1.0=原样；>1 降负荷；<1 有余量可加频）
`humanize`    拟人化轮数倍率（风险高时把「像人」这件事做得更足）
`need_warmup` 下次是否**必须**先预热（会话没养熟就别打深链）
`rotate`      是否建议换设备身份（**只建议，不自动执行**）
`reasons`     人可读的理由（面板/日志直接用）
`decisions`   决策明细：这次读了哪些参数、生效值多少、**来自哪一层**、为什么读
============  ==========================================================

判定顺序（**短路，先重后轻**——这是"统一"的核心）
-----------------------------------------------
0. **人工停手**（`user_data/<profile>/strategy_halt.json`） → `blocked`，
   按人工给的分钟数停；`minutes<=0` 或已到期一律**不拦**（见下文「人工停手」）；
1. 登录退避（`LoginLedger.wait_s > 0`） → 降速 + 强制预热，**不关闸**；
2. `riskscore` 到 `human`/`rotate` 档 → `blocked`（默认 1h，等人工过验证）；
3. 到 `pause` 档 → **不关闸**，只压到最慢一档（短时冷却归 `ChannelBreaker`）；
4. 到 `slow` 档 → `degraded`（默认 2.5×）；
5. 到 `watch` 档 → `watch`（默认 1.5×）；
6. 否则看产量：Wilson 下界 ≥0.90 且样本足 → `healthy` 但允许 0.8×；
   下界 <0.40 且样本 ≥8 → `degraded`（默认 1.5×，理由写「先修因果链」）；
   其余 `healthy`。

上面写的数字都是**默认值**（见文末「参数化」一节）：真值来自参数层，改配置
立刻生效。

为什么产量**不能**直接触发停手：真无票、真冷门航线都会让成功率掉下来，
它们和风控无关。产量只能调**速度**，不能调**开关**——这条边界写死在这里，
免得以后有人为了让报表好看去停一个健康的渠道。

状态机（`blocked → rehab → healthy`）
------------------------------------
`blocked` 到期后不会立刻回到 `healthy`，先给一个 `rehab`（恢复期）：
倍率仍 1.5×、`need_warmup=True`，**成功一次就转正**。理由很实在——刚被
拦过的会话，第一次请求最容易再触发一次；直接满速等于把刚恢复的渠道再打回去。

参数化（r1063，2026-11-06）：所有决定数字都**现读参数层**
--------------------------------------------------------
本模块曾自带三张常量表（`_PACE` / `_BLOCK_S` / `_STICKY_S`）与三个产量阈值
字面量（8 / 0.40 / 0.90）。它们现在是 `core/strategy_contract.py` 里登记的
`Param`，配置键在 `crawler.policy.*` / `crawler.health.*`，默认值与搬家前**逐位
相等**（门禁 `tests/test_r1063_policy_params_equivalent.py` 逐个对）：

    _pace(state)     ← crawler.policy.pace.<state>      1.0/1.5/1.5/2.5/3.0
    _block(level)    ← crawler.policy.block_s.<level>   3600/3600（human/rotate）
    _sticky(state)   ← crawler.policy.sticky_s.<state>  1800/3600/1800
    _band(key)       ← crawler.health.<key>             8 / 0.40 / 0.90

**读的是「此刻」的值**：每次 `decide()` 都现调 `strategy_params.resolve()`，
绝不把结果抄进实例属性（`self.pace = …`）——`reload_config()` 只换 cfg、不重建
对象，抄进实例就等于「配了不生效」，这正是本项目列为头号缺陷的那一类。
取值的来源标注（默认/全局/渠道）由参数层给出，本模块只消费数值。

**坏值不许炸闸门**：手写的配置里写了 `"2.0x"` 这类转不过去的值，`_coerce()`
退回该参数目录里的默认值，并把「已按默认 X 生效」写进 `reasons`——绝不让异常
冒到 `crawlers/base.py` 那层被裸 `except` 吞成 `pol is None`（那等于闸门静默全开）。

**两套「同值近名」阈值不是一个旋钮**：`crawler.health_slow_ratio` /
`health_slow_factor` / `health_min_samples` 是 **pacing 的 TTL 阶梯**（改采集
**间隔**）；`crawler.health.min_samples` / `ok_low` / `ok_high` 是 **policy 的
产量分带**（改**风险姿态倍率**）；`pace_factor.*` 是风险档位倍率。三者互不影响，
键名相似是历史原因（r485 的 pacing 四档 + r1063 的 policy 分带各登记一次）。

决策明细（`decisions`，r1063 T5）：让「谁说了算」看得见
-----------------------------------------------------
界面被问过最多的一句话是「这个 2.5× 到底是谁定的？」。`decide()` 因此把**这次
真正读过的每一个参数**记进 `ChannelPolicy.decisions`，一条一个 dict：

    {"pid": "pace_factor.degraded", "value": 2.5,
     "source": "channel", "why": "degraded 档的间隔倍率"}

* `pid` 是策略目录里的参数 id（界面拿它对 `GET /api/strategy` 的生效值表）；
* `value` 是**实际生效值**——转换/夹取/坏值兜底**之后**的值，不是配置里的原文；
* `source` 就是参数层报的那一层：`default|global|channel|dimension|path`。
  界面「来源」列直接用它，**本模块绝不自己猜来源**；
* `why` 说明为什么读它（人看的，不参与判定）。

顺序 = 读取顺序（先五档倍率、再停手窗口、再余温、最后产量判据）。坏值兜底时
`why` 里追加「配置值 X 无法解析，按默认 Y」——面板因此不必另开一列。

人工停手（halt，r1063 T5）：最高优先级、单独落盘、到期自动失效
-------------------------------------------------------------
人工点了「停手」，那是**人的判断**，不许败给任何自动分档：`decide()` 的**第一段**
就查 `strategy_halt.json`，命中即 `blocked`（`allow=False`、`stop_until` 取人工
给的到期时间、倍率取参数层的 `pace_factor.blocked`、`need_warmup=True`、理由里
有 `人工停手`），**风险分与状态机都不再参与**。

三条边界写死在这里：
1. **单独文件**：halt **不写** `policy_state.json`——那个文件的 `{state,until,at}`
   形状是**自动**状态机的口径（到期转 `rehab`、余温按它算）；混进人工干预会让
   `reset_auto()` 顺手解掉人工停手，两套语义在一个文件里必然互相打架；
2. **到期自动失效**（`minutes<=0` 立即失效）：停手是「有上限的中断」，不是永久
   判死（设计 I6）；进程重启后照旧按文件里的到期时间恢复，不额外记内存态；
3. **`reset_auto()` 不碰 halt**：「解除自动熔断」与「恢复人工停手」是两件事，
   界面上是两个按钮（T6 接线）；
4. **这条链上的失败一律不许静默**（复核 2026-11-06）：读不懂的停手记录由
   `read_halt_ex()` 作为「事实」返回，`decide()` 写进 `reasons`；**日志侧按
   文件签名去重**（`_warn_bad_file`：同一份坏文件只喊一次，改一版再喊一次
   ——每个渠道每一轮一条 warning 会把日志淹掉）；整份文件读不懂与「文件不
   存在」严格分开（前者留痕，后者是正常启动）；
   `set_halt` / `clear_halt` 的写盘失败一律 `_LOG.warning` 且**返回 `False`**
   （`set_halt` 失败时返回 `False` 而不是停手表），绝不让界面报「已停手/已恢复」
   而磁盘上什么都没发生；分钟数解析不了同样 `ValueError`，不静默归 0。
   判 `set_halt` 失败**必须**写 `rec is False`，不许写 `not rec`（`minutes<=0`
   的成功返回值可以是空字典）。
"""
from __future__ import annotations

import json
import logging
import os
import time

from core import strategy_params as sp

_LOG = logging.getLogger(__name__)

STATE_FILE = "policy_state.json"

# 人工停手的落盘文件（**与 policy_state.json 分家**，见模块文档三条边界）
HALT_FILE = "strategy_halt.json"

# 状态枚举（顺序即「从好到坏」，便于比较）
STATES = ("healthy", "rehab", "watch", "degraded", "blocked")

# 决定参数对照表：本模块的语义键 → 参数层 pid。
# 存在的意义是**门禁对账**（`tests/test_r1063_policy_params_equivalent.py`
# 拿它与搬家前的常量逐个比），以及让「哪些数字是可调的」一眼可查；
# 它装的是 pid 字符串，**不是数值**——值永远在 `decide()` 里现读。
POLICY_PIDS = {
    # 间隔倍率五档（原 `_PACE`）
    "pace.healthy": "pace_factor.healthy",
    "pace.rehab": "pace_factor.rehab",
    "pace.watch": "pace_factor.watch",
    "pace.degraded": "pace_factor.degraded",
    "pace.blocked": "pace_factor.blocked",
    # 停手时长（原 `_BLOCK_S`；human/rotate 两档，其余档在本层不停手）
    "block.human": "block_window.human",
    "block.rotate": "block_window.rotate",
    # 余温窗口（原 `_STICKY_S`）：证据在窗口内继续生效，过点自动失效
    "sticky.watch": "residue_window.watch",
    "sticky.degraded": "residue_window.degraded",
    "sticky.rehab": "residue_window.rehab",
    # 产量判据（原字面量 8 / 0.40 / 0.90）
    "health.min_samples": "health_bands.min_samples",
    "health.ok_low": "health_bands.ok_low",
    "health.ok_high": "health_bands.ok_high",
}


def _value(key: str, plat: str = "") -> object:
    """现读一个决定参数（**每次调用都问参数层**，绝不缓存成模块/实例状态）。

    `plat` 传下去是为了让渠道级覆盖真的生效：`crawler.strategy_overrides:`
    里给某个渠道配的倍率/窗口，只有在求值时带上渠道名才命得中。
    """
    try:
        pid = POLICY_PIDS[key]
    except KeyError:
        raise KeyError("core/policy.py 没有这个决定参数：%r（对照表 POLICY_PIDS 里"
                       "只有 %s）" % (key, "、".join(sorted(POLICY_PIDS)))) from None
    return sp.resolve(pid, plat=plat).value


def _say_bad(param, raw, warn: list = None) -> None:
    """坏值的说明句**只落一处**：有收集器就进 `reasons`，没有就打 warning 日志。

    为什么两路都要有（与 `core/riskscore.py::_say_bad` 同律，复核 2026-11-06）：
    `decide()` 会把 `reasons` 一路带到面板与日志，但本模块的取值点不止那一条
    ——别的调用方（报表/界面/后续 T 任务的直接读档位）**没有 reasons 可写**，
    以前就完全不吭声：用户把 `crawler.policy.pace.watch` 写成 `"2.0x"`，程序
    默默用 1.5，任何地方都不留痕。日志是那条路唯一的出口，不许省。
    有 `warn` 时不再重复打日志（同一句话两处出现只会稀释日志）。
    """
    msg = ("配置 %s 的值 %r 无法解析，已按默认 %s 生效"
           % (param.cfg, raw, param.default))
    if warn is not None:
        warn.append(msg)
    else:
        _LOG.warning(msg)


def _note(dec: list, pid: str, value: object, source: str, why: str) -> None:
    """记一条决策明细（`decisions` 的**唯一**写入口，形状在这里定死）。"""
    if dec is not None:
        dec.append({"pid": pid, "value": value, "source": source, "why": why})


# 策略开关的读点（r1063 T12c）：`<sid>.enabled`，**缺省 True＝今天的行为**。
#
# 关掉一条策略 = 该策略「不生效」的语义（Spec §2 推论：关的是**处置**，不是
# 记账——观测与留证继续跑）。本模块管三条：间隔倍率（`pace_factor`）、停手
# 窗口（`block_window`，含余温）、拟人化倍率（`stealth_humanize`），另加两条
# 信号侧的开关（`identity_headers` 的身份自检分、`slider_attempt` 的「遇挑战
# 要不要硬刚」）。
#
# 为什么在 `decide()` 这条路上读：这是「给定同样输入输出同一个决定」的唯一
# 出口，开关若在别处判，面板与实跑迟早说两套话。每次现读，不落实例属性。
def _on(pid: str, plat: str = "") -> bool:
    """读一条策略的 `enabled` 开关（读不懂按开启处理：fail-open 且由参数层留痕）。"""
    try:
        got = sp.resolve(str(pid), plat=str(plat or "")).value
    except Exception:               # 参数层不可用：按开启处理（缺省即旧行为）
        return True
    if isinstance(got, bool):
        return got
    if isinstance(got, (int, float)):
        return bool(got)
    text = str(got).strip().lower()
    if not text:                    # 写了键却空值：等于没配
        return True
    if text in ("1", "true", "yes", "on", "y", "是", "开"):
        return True
    if text in ("0", "false", "no", "off", "n", "否", "关"):
        return False
    return True


def _hum(plat: str, base: float) -> float:
    """拟人化轮数倍率：`stealth_humanize.enabled` 关掉 → 恒 1.0（不额外拟人）。"""
    return float(base) if _on("stealth_humanize.enabled", plat) else 1.0


def _coerce(key: str, plat: str, cast, warn: list = None, dec: list = None,
            why: str = "") -> object:
    """现读参数、转成目标类型；**用户把值写坏了就退回目录里的默认值**并留一句话。

    为什么必须兜底（复核 2026-11-06）：手写的 `config.yaml` 里出现 `"2.0x"` /
    `"一小时"` 这类值时，参数层按「类型不硬转」原样返回，`float()`/`int()` 于是
    抛 `ValueError`；而 `crawlers/base.py::_policy_now` 是裸
    `except Exception: return None`，`_policy_gate` 再把 `None` 解释成放行——
    一条坏配置就能让整条策略闸门**静默全开、不留日志**，`_sleep` 的倍率也退回
    1.0。搬家前三张常量不可能坏，这是参数化新开的失效面，必须在这里收口。

    兜底不是静默：把「实际生效值 = 默认值」写进 `decide()` 的 `reasons`
    （没有 `warn` 时打 warning 日志，见 `_say_bad`），面板/日志直接看得见
    （`无法解析` 是界面文案的锚点，别改）。

    `dec` 是本次决策的明细收集器：**同一次 `resolve()` 同时产出值与来源**，
    所以明细里 `value` 一定是实际生效值、`source` 一定是参数层报的那一层
    ——不另开一次求值，也就不会出现「明细写的和实际用的不是一个值」。
    """
    pid = POLICY_PIDS[key]
    param = sp.PARAMS[pid]
    got = sp.resolve(pid, plat=plat)
    note = why
    try:
        val = cast(got.value)
    except (TypeError, ValueError):
        _say_bad(param, got.value, warn)
        note = ("%s（配置值 %r 无法解析，按默认 %s）"
                % (why, got.value, param.default)) if why else \
               ("配置值 %r 无法解析，按默认 %s" % (got.value, param.default))
        try:
            val = cast(param.default)
        except (TypeError, ValueError):
            # 目录里的默认值本身也转不动（目录被改坏）：**绝不在兜底路径里
            # 二次抛异常**，那是把坏目录变成一个能炸闸门的雷。
            val = param.default
    _note(dec, pid, val, got.source, note)
    return val


# 档位的中文名（只用于 `decisions.why` 的人话说明，不参与判定）
# 都选「能直接接『档』字」的词：健康档 / 恢复档 / 观察档 / 降速档 / 停手档
_STATE_CN = {"healthy": "健康", "rehab": "恢复", "watch": "观察",
             "degraded": "降速", "blocked": "停手"}


def _pace(state: str, plat: str = "", warn: list = None,
          dec: list = None) -> float:
    """某状态的间隔倍率。未知状态按 `healthy` 档（等价旧的 `_PACE.get(state, 1.0)`）。"""
    key = "pace.%s" % state
    if key not in POLICY_PIDS:
        key = "pace.healthy"
    if not _on("pace_factor.enabled", plat):
        # 倍率策略关掉 = **恒 1.0**：风险档不再拉长间隔（面板照样显示档位与
        # 理由，只是不再据此放慢）——关处置，不关记账。
        got = sp.resolve("pace_factor.enabled", plat=plat)
        _note(dec, "pace_factor.enabled", got.value, got.source,
              "间隔倍率策略已关闭：倍率恒 1.0")
        return 1.0
    return _coerce(key, plat, float, warn, dec,
                   "%s档（%s）的间隔倍率"
                   % (_STATE_CN[key.rsplit(".", 1)[-1]],
                      key.rsplit(".", 1)[-1]))


def _block(level: str, plat: str = "", warn: list = None,
           dec: list = None) -> int:
    """human/rotate 档的停手时长（秒）。未知档按 `human` 档
    （等价旧的 `_BLOCK_S.get(level, 3600)`；pause/slow/watch 在本层本就不停手）。"""
    key = "block.%s" % level
    if key not in POLICY_PIDS:
        key = "block.human"
    if not _on("block_window.enabled", plat):
        # 停手窗口策略关掉 = **程序不再自动停手**（仍按最慢档放慢、仍记理由）：
        # 停不停由人判断，程序不替人按下暂停键。
        got = sp.resolve("block_window.enabled", plat=plat)
        _note(dec, "block_window.enabled", got.value, got.source,
              "停手窗口策略已关闭：不自停，风险只体现为放慢")
        return 0
    return _coerce(key, plat, int, warn, dec,
                   "%s 档的风险停手窗口（秒）" % key.rsplit(".", 1)[-1])


def _sticky(state: str, plat: str = "", warn: list = None,
            dec: list = None) -> int:
    """某状态的余温窗口（秒）。没有窗口的状态返回 0（等价旧 `_STICKY_S.get(s, 0)`）。"""
    key = "sticky.%s" % state
    if key not in POLICY_PIDS:
        return 0
    if not _on("block_window.enabled", plat):
        # 余温窗口挂在同一条策略上（同类归一条，见目录里的注释）：关掉停手
        # 窗口时余温也一并失效——否则「已关闭」的策略还会在下一轮偷偷降速。
        got = sp.resolve("block_window.enabled", plat=plat)
        _note(dec, "block_window.enabled", got.value, got.source,
              "停手窗口策略已关闭：不留余温")
        return 0
    return _coerce(key, plat, int, warn, dec,
                   "%s 的余温窗口（秒）：证据保留多久" % state)


# 产量分带的三种判据各自的类型（`health_bands.*` 在目录里的 kind）
_BAND_CAST = {"min_samples": int, "ok_low": float, "ok_high": float}

# 产量判据的说明句（`decisions.why`）
_BAND_WHY = {
    "min_samples": "产量判据的最小样本数：样本不够就不据此调档",
    "ok_low": "产量下界低于此值判「先修因果链」",
    "ok_high": "产量下界高于此值可加频（0.8×）",
}


def _band(key: str, plat: str = "", warn: list = None,
          dec: list = None) -> object:
    """产量判据（`min_samples` / `ok_low` / `ok_high`），现读参数层。"""
    return _coerce("health.%s" % key, plat, _BAND_CAST[key], warn, dec,
                   _BAND_WHY[key])


def _sig(path: str):
    """文件的 `(mtime_ns, size)` 签名；读不到属性时 `None`。

    为什么用它当**告警去重键**：停手文件与状态文件都被我们自己用
    `os.replace` 原子换掉，换一次签名必变——「同一份坏文件只喊一次」
    与「改坏了立刻再喊一次」因此是同一个判据，不需要另存哈希。
    """
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _load_ex(path: str) -> tuple:
    """读一份 JSON 并**连「读没读懂」一起返回**：`(字典, 状态)`。

    状态三种：
      * `"missing"`：文件不存在——最正常的一种（没有停手 / 还没有自动状态）；
      * `"ok"`：读到了对象；
      * `"bad"`：文件在，但读不懂（半个 JSON、不是对象、读不动）。

    为什么必须分开（复核 2026-11-06 Critical 3）：原来一律回 `{}`，于是
    「手改成半个 JSON 的 `strategy_halt.json`」与「本来就没有停手文件」在
    调用方看来**完全一样**——人工停手凭空消失、采集继续跑、全链路无痕；
    `policy_state.json` 同理会变成「每次启动都从零开始」而没人知道。
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}, "missing"
    except OSError:
        return {}, "bad"          # 文件在但读不动（权限/占用/IO）：不许当「没有」
    try:
        d = json.loads(raw)
    except ValueError:
        return {}, "bad"
    if not isinstance(d, dict):
        return {}, "bad"
    return d, "ok"


def _load(path: str) -> dict:
    """只要数据的老口径（读不懂/不存在都按空表）：给不需要「读没读懂」的调用点用。"""
    return _load_ex(path)[0]


# 已经喊过的坏文件（`(path, 原因标签) -> 签名`）。为什么要有（复核 2026-11-06）：
# `decide()` 每个渠道每一轮都读一次停手文件，告警若跟着每次读走，坏文件
# 就是每分钟一条 warning——日志被淹掉之后真正的告警再也看不见，比不喊更糟。
# 按「文件签名」去重之后：同一份坏文件只喊一次，改一版（签名变）重新喊。
#
# 为什么键里还要有**原因标签**（复核 2026-11-06 Important 1）：同一份坏文件
# 下，「读不懂」（read）与「本次写入会覆盖它、其它渠道的停手一并丢」（overwrite）
# 是两件不同的事，后者更该被看见。只按 `(path, sig)` 去重时，路由「先读一次、
# 再写一次」的次序会把 overwrite 那句每次都吞掉——读者只看到「读不懂」，永远
# 不知道自己那一下把别人的停手抹了。所以每种原因各报一次。
_REPORTED_BAD: dict = {}

# 原因标签（写死在调用点，别用自由字符串，免得同一件事两个名字）
_BAD_READ = "read"          # 读到了但读不懂
_BAD_OVERWRITE = "overwrite"  # 本次写入会覆盖坏文件
_BAD_UNCLEARABLE = "unclearable"  # 坏文件让「撤销」无从做起


def _warn_bad_file(path: str, sig, msg: str, tag: str = _BAD_READ) -> bool:
    """同一份坏文件的**同一种原因**只喊一次。返回这次是否真的喊了。"""
    key = (path, tag)
    mark = sig if sig is not None else "no-sig"
    if _REPORTED_BAD.get(key) == mark:
        return False
    _REPORTED_BAD[key] = mark
    _LOG.warning(msg)
    return True


def _forget_bad(path: str) -> None:
    """忘掉某个路径的所有已报原因（文件被我们重写之后用）。"""
    for key in [k for k in _REPORTED_BAD if k[0] == path]:
        _REPORTED_BAD.pop(key, None)


def _dur_cn(sec) -> str:
    """把秒数说成人话（r1799）：7 天 / 12 小时 / 15 分钟。

    与前端 `durCN()` 同口径——同一个停手状态不该在界面和日志里用两种量纲。
    """
    try:
        v = max(0, int(round(float(sec or 0))))
    except (TypeError, ValueError):
        v = 0
    if v >= 172800:
        return "%d 天" % max(1, round(v / 86400))
    if v >= 3600:
        return "%d 小时" % max(1, round(v / 3600))
    if v >= 60:
        return "%d 分钟" % max(1, round(v / 60))
    return "%d 秒" % v


def halt_bad_msg(b: dict) -> str:
    """坏停手记录的人话说明（`read_halt_ex()` 的告警与 `decide()` 的 reason 共用一句）。

    只写一处的理由：这两条路读的是**同一个事实**，分开写必然漂移——面板上
    的说明句与日志里的告警对不上，排查时反而更糊涂。
    """
    b = b if isinstance(b, dict) else {}
    plat = str(b.get("plat") or "*")
    why = str(b.get("why") or "")
    if plat == "*":
        return ("人工停手记录读不懂（%s 整份文件：%s），已按「未停手」"
                "处理，请检查该文件" % (HALT_FILE, why))
    return ("人工停手记录读不懂（%s 里 %s 的 %s），已按「未停手」处理，"
            "请检查该文件" % (HALT_FILE, plat, why))


def _save_json(path: str, data: dict) -> bool:
    """原子写一份 JSON（tmp + `os.replace`）。成功 True，写不动 False。

    为什么不用 `open(path, "w")` 直写：写到一半断电/被杀，留下的是**半个
    JSON**——下一次读出来就是空字典，等于把人工停手静默忘掉（或者更糟：
    把自动状态机忘掉）。`os.replace` 在同一分区上是原子的。
    """
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------- 人工停手
#
# 停手是**人的判断**，所以它有独立的文件、独立的生命周期（见模块文档
# 「人工停手」四条边界）。这几个函数都是模块级的：`webui` 的 halt/resume 路由
# （T6）直接调，不需要凭一个 `PolicyEngine` 实例才能用。

_HALT_CACHE: dict = {}   # path -> (mtime_ns, size, 停手表, 坏记录列表)


def _num_checked(v, default: float = 0.0) -> tuple:
    """`(值, 是否解析成功)`。`None`/空串按「没写」算成功（缺键是常态）。

    **两个读点都用它**（停手文件与 `policy_state.json`）：只返回值的写法会让
    「读不懂」这件事在调用方无从判断，于是只能二选一——抛异常（炸闸门）或者
    静默按默认走（缺陷）。把「成功与否」一起返回，调用方才能既兜底又留痕。
    """
    if v is None or (isinstance(v, str) and not v.strip()):
        return float(default), True
    try:
        return float(v), True
    except (TypeError, ValueError):
        return float(default), False


def profile_of(plat: str) -> str:
    """某渠道**资料目录名**（＝采集器决策时用的 `profile`）。

    全仓唯一口径：抄自爬虫自己的 `profile_name or name`。
    **绝不能图省事写成 `plat`**：`fliggy` 的 H5 爬虫 `name="fliggy"` 而
    `profile_name="fliggy_h5"`，写成 plat 就会把停手写进没人读的目录
    （复核 2026-11-06 Critical）。webui 的 `_profile_of` 现在代理到这里，
    避免两处各写一份、日后漂移。
    """
    plat = str(plat or "").strip()
    if not plat:
        return ""
    try:
        from crawlers import REGISTRY
    except Exception:
        return plat                 # 爬虫包不可用：按原值兜底，别把停手写丢
    cls = REGISTRY.get(plat)
    if cls is None:
        return plat
    return str(getattr(cls, "profile_name", "") or getattr(cls, "name", "")
               or plat)


def halt_path(profile_dir: str) -> str:
    """`profile_dir` 下的人工停手文件路径（`user_data/<profile>/strategy_halt.json`）。"""
    return os.path.join(str(profile_dir or "."), HALT_FILE)


def read_halt_ex(profile_dir: str) -> tuple:
    """读人工停手文件，**连「读不懂的记录」一起返回**：`(停手表, 坏记录列表)`。

    停手表形状不变：`{plat: {"until": float, "note": str}}`；
    `bad` 是 `[{"plat": str, "why": str}]`，只装**本来像条停手记录但读不懂**
    的项（`until` 被手改成 `"明天"`、或整条不是字典）；`why` 是给人看的说明。

    为什么不在这里就 `continue` 掉（复核 2026-11-06 Important 2）：以前坏记录被
    静默丢弃，`decide()` 里那段「坏 until 留一句话」的守卫于是**永远走不到**
    ——意图装在了错误的层。净效果是最坏的一种：手改坏的 `strategy_halt.json`
    让「人工停手」凭空消失、采集继续跑、全链路无痕。现在把「读不懂」作为
    **事实**返回，由 `decide()`（有 reasons 的那一层）去喊。

    `until` 缺失 / 为空 / `<=0` 是**合法**的「没有停手」（`set_halt(minutes=0)`
    就写 `0`），不算坏记录——否则正常文件每次决策都会喊狼来了。

    为什么缓存：`decide()` 每个渠道每一轮都要查一次（面板轮询时更密），每次
    都开文件读 JSON 是白花 IO。缓存键是 `(mtime_ns, size)`——`set_halt` 用
    `os.replace` 换文件，mtime 必变，所以「改了立刻生效」不会被打折。

    坏文件（手改成半个 JSON / 不是字典）→ 返回 `({}, [{"plat": "*", ...}])`
    并**打一条 warning**（同一份坏文件只打一次），**不抛**：读不出停手最多
    是「该停的没停」，抛异常则会顺着 `decide()` 把整条闸门带成放行。
    整份文件读不懂时 `plat` 记 `"*"`（＝所有渠道）：这种情况下没法知道
    是哪一家的记录坏了，`decide()` 把它当成「每个渠道都要吭声」的事实。
    """
    path = halt_path(profile_dir)
    sig = _sig(path)
    if sig is None:
        _HALT_CACHE.pop(path, None)
        return {}, []
    hit = _HALT_CACHE.get(path)
    if hit and hit[0] == sig:
        return ({k: dict(v) for k, v in hit[1].items()},
                [dict(b) for b in hit[2]])
    data, kind = _load_ex(path)
    if kind == "bad":
        # 整份读不懂 ≠ 没有停手：留一条坏记录（`plat="*"`），并喊一次。
        bad = [{"plat": "*",
                "why": "JSON 解析失败或内容不是对象（可能被手改过/写了一半）"}]
        _warn_bad_file(path, sig, "；".join(halt_bad_msg(b) for b in bad))
        _HALT_CACHE[path] = (sig, {}, bad)
        return {}, [dict(b) for b in bad]
    good: dict = {}
    bad: list = []
    for plat, rec in data.items():
        name = str(plat)
        if not isinstance(rec, dict):
            bad.append({"plat": name, "why": "整条记录不是字典：%r" % (rec,)})
            continue
        raw_until = rec.get("until")
        until, ok = _num_checked(raw_until)
        if not ok:
            bad.append({"plat": name, "why": "until=%r 不是时间" % (raw_until,)})
            continue
        if until <= 0:
            continue                      # 合法的「没有停手」，不是坏记录
        good[name] = {"until": until, "note": str(rec.get("note") or "")}
    _HALT_CACHE[path] = (sig, good, bad)
    if bad:
        # 告警只在这里打：缓存命中即返回（上面），所以「每轮每次 decide 刷屏」
        # 这件事从根上没了；而文件一改签名变，会重新喊（见 `_warn_bad_file`）。
        _warn_bad_file(path, sig, "；".join(halt_bad_msg(b) for b in bad))
    return {k: dict(v) for k, v in good.items()}, [dict(b) for b in bad]


def read_halt(profile_dir: str) -> dict:
    """读人工停手表：`{plat: {"until": float, "note": str}}`。**带 mtime 缓存**。

    只要停手表（`{until, note}` 两键），是给界面/只读消费方用的干净视图；
    需要知道「有记录读不懂」的一方（`decide()`）用 `read_halt_ex()`。
    """
    return read_halt_ex(profile_dir)[0]


def halt_key(plat: str, scope: str = "") -> str:
    """停手记录的键：渠道级是 `plat`，带作用域是 `plat/<scope>`。

    `scope` 的形状与参数覆盖一致：`"<维度>"` 或 `"<维度>/<链路>"`。
    渠道级**不换了键的形状**——历史文件里就是裸渠道名，换形状等于让
    上一次的停手集体失效（用户点过停手的渠道会突然又开始跑）。
    """
    plat = str(plat or "").strip()
    scope = str(scope or "").strip().strip("/")
    return (plat + "/" + scope) if scope else plat


def halt_for(halts: dict, plat: str, dim: str = "", path: str = "") -> tuple:
    """在停手表里按「链路 → 维度 → 渠道」找一条生效中的停手。

    返回 `(key, rec)`；没有命中返回 `("", {})`。**顺序即语义**：链路级停手
    只停那一条路，不会连坐同维度的其它通路（这是「可精准控制」的落点）。
    """
    halts = halts if isinstance(halts, dict) else {}
    plat = str(plat or "").strip()
    dim = str(dim or "").strip()
    path = str(path or "").strip()
    for key in ((halt_key(plat, "%s/%s" % (dim, path)) if path else ""),
                (halt_key(plat, dim) if dim else ""),
                plat):
        if not key:
            continue
        rec = halts.get(key)
        # 到点即失效：调用方不必自己判时间（少一处「忘了比对 now」的口子）
        if isinstance(rec, dict) and float(rec.get("until") or 0) > time.time():
            return key, dict(rec)
    return "", {}


def set_halt(profile_dir: str, plat: str, minutes: int, note: str = "",
             scope: str = "") -> dict:
    """给某渠道（或它的某个维度/链路）下一条人工停手。

    `minutes` 分钟后自动失效（`<=0` 立即失效）。`scope` 为空 = 渠道级
    （历史行为逐位不变）；非空 = 只停该作用域，例如 `"intl"` 或
    `"detail/H5/API"`。

    **返回值两种**：写盘成功 → 写盘后的完整停手表 `{key: {"until","note"}}`；
    写盘失败 → `False`（并打 warning）。停手是**安全动作**，一次磁盘故障就
    报成功的话，界面会显示「已停手」而渠道其实还在跑（复核 2026-11-06）。

    调用方判失败必须写 `if rec is False:`（T6 的路由就是这么写的）——
    **绝不能写 `if not rec:`**：`minutes<=0`（立即失效）那条路径写盘成功后
    返回的停手表可以是**空字典**（`until<=0` 不算停手），`not {}` 会把一次
    完全正常的「立即失效」报成 500（复核 2026-11-06 陷阱 A）。

    `plat` 为空 → `ValueError`：停手必须挂在某个渠道上，写一个 `""` 键既查
    不到也删不掉，等于「点了停手什么都没发生」。

    `minutes` 解析不了 → `ValueError`（不是静默归 0）：归 0 等于「立即失效的空
    操作」，用户点了停手、界面报成功、渠道照跑，是同族缺陷。
    """
    plat = str(plat or "").strip()
    if not plat:
        raise ValueError("人工停手必须指定渠道")
    key = halt_key(plat, scope)
    if key.startswith("/"):
        raise ValueError("停手作用域不能为空作用域：%r" % (scope,))
    try:
        mins = int(float(minutes))
    except (TypeError, ValueError):
        raise ValueError("人工停手的分钟数 %r 无法解析（要整数分钟）"
                         % (minutes,)) from None
    until = (time.time() + mins * 60) if mins > 0 else 0.0
    path = halt_path(profile_dir)
    d, kind = _load_ex(path)
    if kind == "bad":
        # 老文件读不懂 → 这次写入会**覆盖**它（其它渠道的停手跟着丢）。不许
        # 静默：至少让操作员知道「刚才那份手改坏的停手表被这一笔换掉了」。
        # 这一句与「读不懂」是**两种原因**（`_BAD_OVERWRITE`），不会被前一次
        # 读取的告警去重掉（复核 2026-11-06 Important 1）。
        _warn_bad_file(path, _sig(path), "；".join([
            halt_bad_msg({"plat": "*",
                          "why": "JSON 解析失败或内容不是对象（可能被手改过"
                                 "/写了一半）"}),
            "本次写入会覆盖该文件（里面其它渠道的停手一并丢失）"]),
            _BAD_OVERWRITE)
    d[key] = {"until": until, "note": str(note or "")}
    ok = _save_json(path, d)
    _HALT_CACHE.pop(path, None)          # 自己写完必失效：别让 mtime 精度骗人
    _forget_bad(path)                    # 新文件＝新签名：以后坏了还要能喊
    if not ok:
        _LOG.warning("停手状态没能落盘：%s（渠道 %s，作用域 %r，%d 分钟）——"
                     "策略层会按「未停手」继续跑，请检查磁盘/权限",
                     path, plat, scope, mins)
        return False
    return read_halt(profile_dir)


def clear_halt(profile_dir: str, plat: str, scope: str = "") -> bool:
    """撤掉某渠道（或它的某个维度/链路）的人工停手。

    **`False` 有两层意思**：本来就没有这条记录，或者**写盘失败**（后者会打
    warning）。两个姊妹函数的失败契约因此一致：没真的落盘，就不许报「已恢复」
    ——否则界面显示「人工停手已解除」而策略层还在拦，操作员会以为按钮坏了。
    写盘失败时文件里那条**仍然在**，返回 `False` 与「停手继续生效」是同一个事实。
    """
    plat = str(plat or "").strip()
    if not plat:
        return False
    key = halt_key(plat, scope)
    path = halt_path(profile_dir)
    d, kind = _load_ex(path)
    if kind == "bad":
        # 读不懂就没有「撤销」可言：这次返回 False，界面上那条停手照旧显示
        # （策略层也确实按「未停手」在跑），二者一致——但要让操作员知道
        # 是文件坏了，而不是按钮坏了。
        _warn_bad_file(path, _sig(path), "；".join([
            halt_bad_msg({"plat": "*",
                          "why": "JSON 解析失败或内容不是对象（可能被手改过"
                                 "/写了一半）"}),
            "无法撤销 %s 的停手，请先修好该文件" % plat]), _BAD_UNCLEARABLE)
        return False
    if key not in d:
        return False
    d.pop(key, None)
    ok = _save_json(path, d)
    _HALT_CACHE.pop(path, None)
    _forget_bad(path)                    # 新文件＝新签名：以后坏了还要能喊
    if not ok:
        _LOG.warning("停手状态没能落盘：%s（撤销渠道 %s 失败）——"
                     "人工停手仍然生效，请检查磁盘/权限", path, plat)
        return False
    return True


class ChannelPolicy:
    """一个渠道一次的完整决定。不可变语义：构造后只读。"""

    __slots__ = ("plat", "state", "allow", "stop_until", "pace_factor",
                 "humanize", "need_warmup", "rotate", "reasons", "score",
                 "decided_at", "decisions")

    def __init__(self, plat, state="healthy", allow=True, stop_until=0.0,
                 pace_factor=1.0, humanize=1.0, need_warmup=False,
                 rotate=False, reasons=None, score=0.0, decided_at=0.0,
                 decisions=None):
        self.plat = str(plat)
        self.state = str(state)
        self.allow = bool(allow)
        self.stop_until = float(stop_until or 0.0)
        self.pace_factor = float(pace_factor or 1.0)
        self.humanize = float(humanize or 1.0)
        self.need_warmup = bool(need_warmup)
        self.rotate = bool(rotate)
        self.reasons = list(reasons or [])
        self.score = float(score or 0.0)
        self.decided_at = float(decided_at or 0.0)
        # 决策明细（r1063 T5）：**只读**，构造后不再追加。默认空列表是为了
        # 兼容旧的手工构造（`ChannelPolicy("ctrip", "degraded", True, 0, 2.5)`）
        # 与测试夹具——它们不该为了一个显示字段去改每一个调用点。
        self.decisions = [dict(x) for x in (decisions or [])]

    def wait_s(self, now: float = None) -> int:
        ts = float(now if now is not None else time.time())
        return max(0, int(self.stop_until - ts)) if self.stop_until else 0

    def as_dict(self) -> dict:
        return {
            "plat": self.plat, "state": self.state, "allow": self.allow,
            "wait_s": self.wait_s(), "pace_factor": self.pace_factor,
            "humanize": self.humanize, "need_warmup": self.need_warmup,
            "rotate": self.rotate, "score": self.score,
            "reasons": list(self.reasons),
            # 只加键、不改既有键：`/api/pacing` 的既有消费方按名字取，
            # 多一个 `decisions` 不会打破它（T12/T13 用它回答「谁说了算」）。
            "decisions": [dict(x) for x in self.decisions],
        }

    def __repr__(self):
        return "<Policy %s %s allow=%s pace=%.1f>" % (
            self.plat, self.state, self.allow, self.pace_factor)


class PolicyEngine:
    """统一策略：读账本 → 出决定 → 记状态机（`policy_state.json`）。

    **只读别的东西、只写自己的状态文件**：不碰 `pacing` 的内部状态、
    不碰登录账本、不碰产量账本。这样它坏了最多是决定变回「全放行」，
    不会把采集链路带崩。
    """

    def __init__(self, config: dict = None, *, user_data_dir: str = "user_data",
                 profile: str = "", repo_root: str = "."):
        self.config = config if isinstance(config, dict) else {}
        self.repo_root = str(repo_root or ".")
        # 根目录唯一口径（config > TM_USER_DATA_DIR > 默认）：策略状态
        # policy_state.json 也落在同一处，测试同样不该写进真 user_data
        from core.yield_stats import user_data_root
        root = user_data_root(self.config, default=user_data_dir or "user_data")
        base = os.path.join(self.repo_root, root)
        if profile:
            base = os.path.join(base, profile)
        self.base_dir = base
        self.state_path = os.path.join(base, STATE_FILE)

    # ---------- 账本 ----------
    def _yield(self):
        try:
            from core.yield_stats import YieldLedger
            return YieldLedger(os.path.join(self.base_dir, "yield_stats.json"))
        except Exception:
            return None

    def _login(self):
        try:
            from core.riskscore import LoginLedger
            return LoginLedger(os.path.join(self.base_dir, "login_ledger.json"))
        except Exception:
            return None

    # ---------- 状态机 ----------
    def _state(self) -> dict:
        """读自动状态机（`policy_state.json`）。

        读不懂 → **从空开始**继续跑（绝不能因为一份坏文件把闸门带崩），但
        留一条痕、且只留一条（同 `read_halt_ex` 的告警口径）：手改坏的
        `policy_state.json` 表现为「自动熔断/余温全部消失」，而正常启动
        （文件不存在）**不算**异常、一个字都不喊——否则每次开机都是一条
        warning，真正的告警会被淹掉（复核 2026-11-06 陷阱 C）。
        """
        d, kind = _load_ex(self.state_path)
        if kind == "bad":
            _warn_bad_file(
                self.state_path, _sig(self.state_path),
                "自动状态机读不懂（%s），本次按「没有任何自动状态」继续"
                "（自动熔断/余温会因此失效）：请检查该文件" % STATE_FILE)
        return d if isinstance(d, dict) else {}

    def _save_state(self, plat: str, state: str, until: float = 0.0) -> None:
        try:
            d = self._state()
            rec = d.get(plat) if isinstance(d.get(plat), dict) else {}
            rec.update({"state": state, "until": float(until or 0.0),
                        "at": time.time()})
            d[plat] = rec
            _save_json(self.state_path, d)
        except (OSError, ValueError, TypeError):
            pass

    def reset_auto(self, plat: str = "") -> bool:
        """解除**自动**熔断/余温：只清 `policy_state.json`，**绝不碰人工停手**。

        「解除自动熔断」与「恢复人工停手」是两件事（设计 Q5）：熔断是程序自己
        判出来的（还会自己到期转 `rehab`），停手是人下的命令（存在
        `strategy_halt.json`，只有 `clear_halt()`/到期能解）。把它们绑在一个
        按钮上，就会出现「点一下解除，顺手把人工的停手也解了」——那是操作员
        最不能接受的一类意外。

        `plat` 给了只清该渠道，没给清全部（T6 的 `/api/pacing/reset` 是**按
        渠道**调的）。

        **返回是否真的落盘**（复核 2026-11-06 Important 2）：原来这里把
        `_save_json()` 的返回值丢掉、异常也吞掉，返回 `None` ——于是调用方那圈
        `except` 永远走不到，`_save_json` 失败时接口照样回「已解除」、零痕迹，
        而策略层还在拦。写不动就是写不动，必须让调用方知道（并自己决定怎么
        告诉用户）；抛异常则不行——调用方会以为「停手也一起被清了」。
        """
        ok = False
        try:
            d = self._state()
            if plat:
                d.pop(str(plat), None)
            else:
                d = {}
            ok = bool(_save_json(self.state_path, d))
        except (OSError, ValueError, TypeError):
            ok = False
        if not ok:
            _LOG.warning("自动状态没能落盘：%s（解除自动熔断未生效，策略层可能"
                         "仍在拦；人工停手不受影响）", self.state_path)
        return ok

    def _prev(self, plat: str) -> dict:
        rec = self._state().get(plat)
        return rec if isinstance(rec, dict) else {}

    # ---------- 决定 ----------
    def decide(self, plat: str, *, now: float = None,
               statuses=None, soft: bool = False, captcha: bool = False,
               login_wall: bool = False, identity_score=None,
               stealth_score=None, rate_pressure: bool = False,
               two_way: bool = False) -> ChannelPolicy:
        """出决定。``two_way`` 只查询不更新状态机（给报表/面板用）。"""
        ts = float(now if now is not None else time.time())
        plat = str(plat)
        reasons = []
        dec: list = []              # 决策明细：本次真正读过的参数（见模块文档）
        warn: list = []

        # ---- 00. 人工停手：**最高优先级，先于一切自动判定** ----
        #
        # 人工点了「停手」，那是人的判断，不许败给任何自动分档：这里在最前面
        # 就短路，风险分/状态机/产量一律不参与（也就不会被它们的理由搅浑）。
        # 只读一个参数（停手期间的倍率），明细因此也只有一条——面板会看到
        # 「这次决策只读了 pace_factor.blocked，来源 X」，这正是实情。
        #
        # 不写 `policy_state.json`：那个文件是**自动**状态机（到期转 rehab、
        # 余温按它算）。人工停手一旦混进去，`reset_auto()` 就会顺手把人的
        # 命令解掉，而且自动窗口会被 5 分钟的人工窗口改写（见模块文档）。
        #
        # `rotate=False` 也写死：人工停手期间不该同时建议换身份——面板上给出
        # 两个方向相反的动作，操作员只会犯迷糊。
        #
        # **读不懂的停手记录必须在 reasons 里吭声**（复核 2026-11-06 Important 2）：
        # 坏记录被静默丢弃 = 「人工停手」凭空消失、采集照跑、全链路无痕。归因和
        # 说明句只能落在有 reasons 的这一层（`read_halt_ex()` 那层没地方写）。
        halts, bad_halts = read_halt_ex(self.base_dir)
        halt = halts.get(plat) or {}
        for b in bad_halts:
            # `plat == "*"` ＝整份文件读不懂（见 `read_halt_ex`），每个渠道都
            # 该在 reasons 里吭一声；具体是哪条记录坏了归 `why` 说。
            if b["plat"] not in ("*", plat):
                continue
            # **只写进 reasons，不再打日志**（复核 2026-11-06 陷阱 B）：日志
            # 由 `read_halt_ex()` 按文件签名喊一次，这里每次决策都要说一句
            # （面板要看得见），两件事分层。
            reasons.append(halt_bad_msg(b))
        halt_until = float(halt.get("until") or 0.0)
        if halt_until > ts:
            _left_s = int(max(0, halt_until - ts))
            note = str(halt.get("note") or "").strip()
            # 倍率**先取**再拼理由：坏值说明句是 `_pace` 往 `warn` 里写的，
            # 先 `extend` 再取值会让那句话静默丢掉（坏值提示不许丢第二次）。
            halt_pace = _pace("blocked", plat, warn, dec)
            reasons.append("人工停手，剩 %s%s：到期自动恢复，或人工解除"
                           % (_dur_cn(_left_s),
                              "（%s）" % note if note else ""))
            reasons.extend(warn)
            return ChannelPolicy(plat, "blocked", False, halt_until,
                                 halt_pace, _hum(plat, 2.0), True, False,
                                 reasons, 0.0, ts, decisions=dec)

        prev = self._prev(plat)

        # ---- 0. 这次决策要用的数字，先**现读一遍**参数层 ----
        #
        # 一次读全、而不是各分支临时读：① 坏值的提示一次就齐（哪怕这次走的是
        # 提前 return 的 blocked 分支）；② 同一条决策路径上不会有第二次求值。
        # 仍然「决策时求值」——不落实例属性、不进模块常量（热生效靠这一点）。
        #
        # 两套「同值近名」的阈值各管各的（**别把它们当成一个旋钮**）：
        #   `crawler.health_slow_ratio` / `health_slow_factor` / `health_min_samples`
        #       = **pacing 的 TTL 阶梯**，改的是**采集间隔**（由 core/pacing.py 读）；
        #   `crawler.health.min_samples` / `ok_low` / `ok_high`（下面 `_band`）
        #       = **policy 的产量分带**，改的是**风险姿态倍率**；
        #   `pace_factor.*` = 风险档位倍率本身。
        # 三组互不影响；0.4 与 0.40、`health_min_samples` 与
        # `health.min_samples` 长得像，是历史原因（r485 的 pacing 四档 + r1063 的
        # policy 分带各登记一次），不是同一份数据。
        # `warn` 在函数开头就建好了（停手那段也要用它收坏值提示），这里不再重建。
        pace_of = {st: _pace(st, plat, warn, dec) for st in STATES}
        block_of = {lv: _block(lv, plat, warn, dec) for lv in ("human", "rotate")}
        sticky_of = {st: _sticky(st, plat, warn, dec)
                     for st in ("watch", "degraded", "rehab")}
        min_samples = _band("min_samples", plat, warn, dec)
        ok_low = _band("ok_low", plat, warn, dec)
        ok_high = _band("ok_high", plat, warn, dec)
        reasons.extend(warn)

        yl, ll = self._yield(), self._login()
        lo, _hi, n = (0.0, 1.0, 0)
        if yl is not None:
            try:
                lo, _hi, n = yl.bounded_rate(plat)
            except Exception:
                pass

        # ---- 1. 登录侧退避：降速 + 强制预热，但**不拦采集** ----
        #
        # 为什么不停手：登录退避的作用对象是「人工重登」，而定时采集一轮本来
        # 就是 30 分钟，远长于 90–900s 的阶梯。更关键的是仓库既有语义——
        # 登录墙必须如实记 `login` 并继续跑（由人过完再采），把它改成静默
        # 跳过会让「掉登录」这件事从账本上消失，比多打几次更危险。
        wait = 0
        streak = 0
        rotate = False
        if ll is not None:
            try:
                wait = ll.wait_s(plat, now=ts)
                streak = int(ll.rec(plat).get("streak") or 0)
                rotate = ll.should_rotate(plat)
            except Exception:
                pass
        if wait > 0:
            reasons.append("登录退避中（连击 %d 次，%ds 后可再试登录）"
                           % (streak, wait))

        # ---- 2. 风险分：与 riskscore 同一口径，不另算一套 ----
        #
        # 分工（刻意的）：**短时冷却归 `ChannelBreaker`**——它拿得到服务端的
        # `Retry-After`，按真实配额退避；**本层只管长期姿态**（要不要停一整段、
        # 要不要换身份、倍率给多少）。两层都去拦会过度降温，产量白掉。
        score, level, dev = 0.0, "calm", False
        # `identity_headers.enabled` 关掉 = 身份三件套（UA/移动 UA/TLS）**不再
        # 套用**，那么"身份自检分/隐藏自检分"这两个信号也就不该参与打分——
        # 拿一个"我们没在用的身份"去扣风险分，只会凭空把渠道说坏。
        _ident_on = _on("identity_headers.enabled", plat)
        try:
            from core.riskscore import evaluate
            got = evaluate({
                "statuses": list(statuses or []), "soft": soft,
                "captcha": captcha, "login_wall": login_wall,
                "login_fail_streak": streak,
                "identity_score": identity_score if _ident_on else None,
                "stealth_score": stealth_score if _ident_on else None,
                "rate_pressure": rate_pressure,
                # **渠道名必须带上**：`risk_bands` 的四个分界是可按渠道覆盖的
                # （`crawler.strategy_overrides: {ctrip: {risk_bands.pause: 50}}`），
                # `evaluate()` 拿不到 plat 就只能按全局值分档——界面/账本里
                # `assess("ctrip")` 判 pause、本层同一分数判 slow，正是本项目
                # 定义的「配了不生效」（复核 2026-11-06 Important 1）。这里就在
                # `decide(self, plat, …)` 里面，渠道名在手边，没有理由不带。
                "plat": plat,
            })
            score, level, dev = got["score"], got["level"], got["device_driven"]
            reasons.extend(got.get("reasons") or [])
        except Exception:
            pass

        # `slider_attempt.enabled` 关掉 = 遇滑块/人机验证**不再硬刚**：直接按
        # 「等人工过验证」处理（人档），而不是按风险分慢跑着继续试——自动尝试
        # 被关掉之后，再试一次就是把次数白送出去。
        if captcha and not _on("slider_attempt.enabled", plat):
            if level not in ("human", "rotate"):
                level = "human"
            reasons.append("滑块自动尝试策略已关闭：遇挑战直接等人工过验证")

        if level in ("human", "rotate"):
            block = block_of[level]
            reasons.append("风险 %.0f（%s）：等人工过验证/重登" % (score, level))
            if block <= 0:
                # `block_window.enabled` 关掉（`_block()` 返回 0）：**不自停**。
                # 降到最慢档继续跑，且**不写** `policy_state.json` 的 blocked
                # ——没发生过停手窗口，就不该在状态机里留一段假的停手记录。
                reasons.append("停手窗口策略已关闭：不自停，按最慢档继续")
                return ChannelPolicy(plat, "degraded", True, 0.0,
                                     pace_of["blocked"], _hum(plat, 2.0),
                                     True, rotate, reasons, score, ts,
                                     decisions=dec)
            if not two_way:
                self._save_state(plat, "blocked", ts + block)
            return ChannelPolicy(plat, "blocked", False, ts + block,
                                 pace_of["blocked"], _hum(plat, 2.0),
                                 True, rotate, reasons, score, ts,
                                 decisions=dec)
        # pause 档在**本层不关闸**：短时冷却归 ChannelBreaker（它拿得到
        # Retry-After），本层只把速度压到最慢一档。两层都拦会过度降温。
        if level == "pause":
            reasons.append("风险 %.0f（pause）：压到最慢档，短时冷却由熔断器接管"
                           % score)

        # ---- 3. 上次停手窗口：**先尊重已成事实**，别靠信号重算 ----
        #
        # 这是"统一"最容易错的一处：停手决定一旦落下，就必须按剩余时间继续
        # 停，哪怕这一轮的信号全空（例如程序刚重启、账本还没喂新信号）。
        # 只靠 riskscore 重算的话，信号一空就立刻放行——等于停手从来没发生。
        prev_state = str(prev.get("state") or "")
        # **坏账本不许炸闸门**（复核 2026-11-06，与参数坏值同律）：这里原来是
        # `float(prev.get("until") or 0.0)`，手改成 `"until": "一小时后"` 就抛
        # `ValueError`；调用方 `crawlers/base.py::_policy_now` 是裸
        # `except Exception: return None`，`_policy_gate` 再把 `None` 当放行
        # ——一个手抖的 JSON 就能让闸门**静默全开、不留日志**。
        prev_until, until_ok = _num_checked(prev.get("until"))
        if not until_ok:
            reasons.append("policy_state.json 里 %s 的 until 值 %r 无法解析，"
                           "已按「没有停手窗口」处理"
                           % (plat, prev.get("until")))
        if prev_state == "blocked" and prev_until > ts:
            reasons.append("仍在上次停手窗口内（剩 %d 分钟）"
                           % int((prev_until - ts) // 60 + 1))
            return ChannelPolicy(plat, "blocked", False, prev_until,
                                 pace_of["blocked"], _hum(plat, 2.0),
                                 True, rotate, reasons, score, ts,
                                 decisions=dec)

        # ---- 4. 恢复期：blocked 刚到期，先慢跑一轮，成功一次就转正 ----
        if prev_state == "blocked" and prev_until and ts >= prev_until:
            rehab_pace = pace_of["rehab"]
            reasons.append("恢复期：先慢跑一轮（%.1f×），成功即转正" % rehab_pace)
            if not two_way:
                self._save_state(plat, "rehab", ts + sticky_of["rehab"])
            return ChannelPolicy(plat, "rehab", True, 0.0, rehab_pace,
                                 _hum(plat, 1.5), True,
                                 rotate, reasons, score, ts,
                                 decisions=dec)

        # pause 档在**本层**不关闸（短时冷却归熔断器），但要压到最慢一档；
        # slow 档 2.5×；watch 档 1.5×（具体数值见参数层）。
        state = {"pause": "degraded", "slow": "degraded",
                 "watch": "watch"}.get(level, "healthy")
        pace = pace_of.get(state, pace_of["healthy"])
        if level == "pause":
            pace = pace_of["blocked"]
            reasons.append("风险 %.0f（pause）：压到最慢档，短时冷却由熔断器接管"
                           % score)

        # ---- 4. 产量只调速度，不调开关 ----
        if n >= min_samples and lo < ok_low:
            state = "degraded"
            pace = max(pace, pace_of["watch"])
            reasons.append("产量下界 %.2f（%d 样本）：先修因果链（预热/锁/登录）"
                           % (lo, n))
        elif n >= min_samples and lo >= ok_high and state == "healthy":
            pace = 0.8
            reasons.append("产量下界 %.2f（%d 样本）：有余量，可加频" % (lo, n))
        elif n and n < min_samples:
            reasons.append("产量样本 %d <%d，不据此调整" % (n, min_samples))

        # 设备项占主导但还没到 human 档：提前提示换身份（不自动）
        if dev and not rotate and score >= 45:
            rotate = False
            reasons.append("命中项以设备为主：降到 pause 前建议评估换身份")

        # 登录退避在场：至少降一档速，并且下次必须先预热（会话没养熟别打深链）
        if wait > 0 and state == "healthy":
            state = "rehab"
            pace = max(pace, pace_of["rehab"])

        # ---- 5. 余温：上一轮的 watch/degraded 在窗口内保留 ----
        #
        # 为什么需要：一轮滑块的证据只影响那一轮的话，下一轮（30 分钟后、
        # 不带任何信号）就回到满速，等于「记了不认」。这里给一个**有界**的
        # 记忆窗口（watch 30min / degraded 60min），过点自动失效——比
        # 无条件粘住安全得多，也不会像熔断器那样长期停机。
        keep_s = sticky_of.get(prev_state, 0)
        residue_until = 0.0
        if keep_s and prev_until and prev_until > ts:
            if STATES.index(prev_state) > STATES.index(state):
                state = prev_state
                pace = max(pace, pace_of[prev_state])
                # **沿用原到期时间，不续期**：否则每次查询都把窗口往后推
                # 3600s，余温永远不过期，等于永久降速（这正是"粘住"最坏的
                # 形态）。窗口属于事件发生的那一刻，不属于每次读数。
                residue_until = prev_until
                reasons.append("上轮 %s 的余温还在（%d 分钟内保留）"
                               % (prev_state, int((prev_until - ts) // 60) + 1))

        # 只在「状态变化」或「非健康」时落盘：健康的稳态每轮写一次毫无意义，
        # 还会让磁盘 IO 跟着采集轮次涨（一轮 5 个渠道 × 每轮都写）。
        if not two_way and (state != "healthy" or prev_state):
            until = residue_until or (ts + sticky_of.get(state, 0))
            self._save_state(plat, state, until)
        need_warm = bool(captcha or soft or login_wall or wait > 0
                         or state != "healthy")
        return ChannelPolicy(plat, state, True, 0.0, pace,
                             _hum(plat, 1.5 if state != "healthy" else 1.0),
                             need_warm, rotate, reasons, score, ts,
                             decisions=dec)

    # ---------- 便捷 ----------
    def allow(self, plat: str, now: float = None) -> bool:
        return self.decide(plat, now=now, two_way=True).allow

    def snapshot(self, plats=None, now: float = None) -> dict:
        """一次性看所有渠道的决定（报表/面板用，不改状态机）。"""
        plats = list(plats or [])
        if not plats:
            plats = sorted(set(self._state()) | self._known_plats())
        return {p: self.decide(p, now=now, two_way=True).as_dict()
                for p in plats}

    def _known_plats(self) -> list:
        out = []
        for name in ("yield_stats.json", "login_ledger.json"):
            d = _load(os.path.join(self.base_dir, name))
            out.extend(d.keys())
        return sorted(set(out))


def default_engine(config: dict = None, *, repo_root: str = ".",
                   profile: str = "") -> PolicyEngine:
    cfg = config if isinstance(config, dict) else {}
    return PolicyEngine(cfg, profile=profile, repo_root=repo_root)
