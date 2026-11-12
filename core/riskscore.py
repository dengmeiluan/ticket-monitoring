# -*- coding: utf-8 -*-
"""风控评分：把散落的信号汇成一个 0–100 的风险分，并给出**可执行**处置。

为什么要有这一层
----------------
现在这些信号分散在各个模块里，各自反应：``ChannelBreaker`` 只管熔断、
``Pacing`` 只管节奏、``app_base`` 只管账本、身份层只管身份。结果是
「每个部件都在动，但没人回答一个整体问题」：

    这一轮到底该**继续、降速、停 40 分钟、还是换设备**？

真实现场就吃过这个亏：携程 App 连续登录失败时，程序按 30 分钟节奏一直
重试，而**每次失败的登录尝试本身就是加分项**——越试越像撞库，三天后
同一个账号连 PC 端都开始要短信。降速救不了「已经踩到设备规则」的账号，
继续试也救不了「IP 已被标记」的会话。

评分口径（每项都是**可观测事实**，不是猜测）
-------------------------------------------
======================  =====  ==========================================
信号                    权重   来源
======================  =====  ==========================================
403 / 429 / 503         28     响应状态（base._watch_retry_after）
202 空体 / 444 软拒     14     base.last_soft_reject
滑块 / 点选 / 人机验证  30     challenge.classify_text / app_blockers
登录墙（会话失效）      18     app_base.is_login_wall
登录失败连击            6×n    LoginLedger（本模块）
身份自检分低            (100-分)/4   android.fingerprint.audit
隐藏自检分低            (100-分)/4   android.stealth.detect
当前是否处于限速压力    12     pacing.TokenBucket.wait_hint
======================  =====  ==========================================

处置档位（分数越高越保守，且**只升不降地粘住**一段时间）
-------------------------------------------------------
``calm``(<25) → 照常；``watch``(<45) → 提速间隔 1.5×；
``slow``(<65) → 间隔 2.5×、只跑快层；``pause``(<80) → 熔断 30–60min；
``human``(>=80) → 停下来等人工过验证；其中**设备项占主导时**给 ``rotate``
（换身份）——这是「降速无效、只有换设备有用」的唯一出口。

刻意不做的事
------------
* 不自动换身份：换身份 = 一次「新设备登录」，会触发二次校验。给建议，
  由操作员或显式命令决定（``fingerprint.rotate``）。
* 不写进 ``Pacing`` 的既有决策：本模块只**读** pacing 的快照再算分，
  避免把已经被 852 个测试钉住的节奏逻辑改出回归。

阈值从哪来（r1063 T4 参数化）
-----------------------------
上面那张「档位表」里的分数分界与登录退避阶梯**不再是本模块的常量**：
它们登记在 `core/strategy_contract.py` 的 `risk_bands` 策略里
（`risk_bands.watch/slow/pause/human` + `risk_bands.login_backoff_s`，
cfg 键 `crawler.risk.levels.*` / `crawler.risk.login_backoff_s`），
在**每一次** `evaluate()` / `backoff_s()` 调用的那一刻通过
`core/strategy_params.resolve()` 现读——`set_config()` 换一份 cfg，
下一次分档就按新值走，不需要重启、不需要重建账本对象。

为什么不缓存成模块常量：缓存就是「配了不生效」的另一种写法（改完配置
程序照旧按老数字分档，还没有任何日志）。`tests/test_r1063_risk_params_
equivalent.py` 用「同一份配置单例改完再 `evaluate()`」钉这一条。

用户把值写坏（`watch: "低"`、`login_backoff_s: "0,90,300"`）→ **退回目录里
的默认值**，并把「无法解析」那句写进本次返回的 `reasons`（与
`core/policy.py::_coerce` 同一口径）：坏配置不许静默变成一个更松的分档，
更不许从决策路径里抛出去。
"""
from __future__ import annotations

import json
import logging
import os
import time

from core import strategy_params as sp

LEVELS = ("calm", "watch", "slow", "pause", "human", "rotate")

# 本模块的语义键 → 参数层 pid（对照表只装 **pid 字符串**，不装数值）。
# 存在的意义：①「哪些数字是可调的」一眼可查；② 审计矩阵的 `configurable`
# 轴靠这些字面量认出「这个 pid 真有生产读点」（`read_by_param` 要求同一个
# 文件里既有 pid 字面量、又有 `strategy_params` 与 `resolve(` 调用）。
# 值永远在 `_coerce()` / `_backoff_ladder()` 里现读，绝不在这里写成常量。
RISK_PIDS = {
    "levels.watch": "risk_bands.watch",
    "levels.slow": "risk_bands.slow",
    "levels.pause": "risk_bands.pause",
    "levels.human": "risk_bands.human",
    "login_backoff_s": "risk_bands.login_backoff_s",
}

# 搬家前的字面量（**最后兜底**，正常路径永远读参数层）：
# `LEVEL_DEFAULTS` 与 `LOGIN_BACKOFF` 只在「目录里的 `Param.default` 本身也被
# 改坏到转不动」时用——那种时候宁可按搬家前的口径分档，也不能把异常抛进
# `evaluate()` / `note_result()` 的调用链（下游是裸 `except Exception`，会把
# 异常吞成「放行」）。两份字面量与参数层默认值的逐位一致由
# `tests/test_r1063_risk_params_equivalent.py` 钉住（漂移当场红）。
LEVEL_DEFAULTS = {"watch": 25, "slow": 45, "pause": 65, "human": 80}

# 搬家前的默认退避阶梯（秒）。第 n 次连击失败后应等这么久再试。
# `tests/test_r911_web_stealth_human_risk.py` 仍按
# `riskscore.LOGIN_BACKOFF[3]` 对照阶梯（那份门禁不许改），所以常量留在原处。
LOGIN_BACKOFF = (0, 90, 300, 900, 1800, 3600, 7200)

# 每个档位给出的具体动作（给操作员/程序看的，不是形容词）
ADVICE = {
    "calm": {"speed": 1.0, "pause_s": 0, "paths": "all",
             "text": "正常采集"},
    "watch": {"speed": 1.5, "pause_s": 0, "paths": "all",
              "text": "间隔放大到 1.5×，观察下一轮"},
    "slow": {"speed": 2.5, "pause_s": 0, "paths": "fast",
             "text": "间隔放大到 2.5×，本轮只跑快层（临期日期）"},
    "pause": {"speed": 3.0, "pause_s": 1800, "paths": "none",
              "text": "停 30–60 分钟再跑，别再喂失败样本"},
    "human": {"speed": 3.0, "pause_s": 3600, "paths": "none",
              "text": "停手，等人工在可见窗口过验证/重登"},
    "rotate": {"speed": 3.0, "pause_s": 3600, "paths": "none",
               "text": "设备侧已命中规则：考虑换身份（fingerprint.rotate）"},
}


# ---------------------------------------------------------------------------
# 参数读取（每次调用现读，不缓存）
# ---------------------------------------------------------------------------
_LOG = logging.getLogger(__name__)


def _say_bad(param, raw, warn: list = None) -> None:
    """坏值的说明句**只落一处**：有收集器就进 `reasons`，没有就打 warning 日志。

    为什么两路都要有（复核 2026-11-06 Important 2）：`evaluate()` 会把本次
    `reasons` 传下来，坏值于是跟着决策一起被
    `crawlers/app_base.py` 记成 warning；但 `LoginLedger.backoff_s()` 这条路上
    没有 reasons 可写——它以前就**完全不吭声**，用户把
    `crawler.risk.login_backoff_s` 写成 `"0,90,300"` 时程序默默用默认阶梯，
    任何地方都不留痕。日志是那条路唯一的出口，不许省。
    有 `warn` 时不再重复打日志（同一句话两处出现只会稀释日志）。
    """
    msg = ("配置 %s 的值 %r 无法解析，已按默认 %s 生效"
           % (param.cfg, raw, param.default))
    if warn is not None:
        warn.append(msg)
    else:
        _LOG.warning(msg)


def _on(pid: str, plat: str = "") -> bool:
    """读一条策略的 `enabled` 开关（r1063 T12c），**缺省 True＝今天的行为**。

    本模块管两条：`risk_bands`（分档线还生不生效）与 `rotate_advice`
    （还要不要建议换身份——它只建议、从不执行，所以"关掉"就是不再提示）。
    读不懂按开启处理并留痕：拼错的 `flase` 静默关掉一条分档策略，比报错更难查。
    """
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


def _coerce(key: str, cast, warn: list = None, plat: str = "") -> object:
    """现读一个风险参数并转成目标类型；**用户把值写坏了退回目录默认值**并留话。

    唯一的转换点：分界走 `int`、阶梯走 `_backoff_ladder()` 自己的列表校验。
    兜底不是静默——说明句交给 `_say_bad()`（进 `reasons` 或打日志）。
    目录里的默认值本身也转不动时，再退到搬家前的字面量 `LEVEL_DEFAULTS`：
    `except` 分支里绝不允许再抛一次。

    `plat` 一路传进 `resolve()`：`risk_bands` 的 scope 声明了 channel 级覆盖，
    不带上渠道名就等于这条声明是空话。
    """
    pid = RISK_PIDS[key]
    param = sp.PARAMS[pid]
    raw = sp.resolve(pid, plat=plat).value
    try:
        return cast(raw)
    except (TypeError, ValueError):
        _say_bad(param, raw, warn)
        try:
            return cast(param.default)
        except (TypeError, ValueError):
            # 目录被改坏到默认值都转不动：`_coerce()` 只为四个分界服务，
            # 短名（`watch`/…）就是 `LEVEL_DEFAULTS` 的键。
            return cast(LEVEL_DEFAULTS[key.rsplit(".", 1)[-1]])


def _levels(warn: list = None, plat: str = "") -> tuple:
    """风险档位分界：`((分数下限, 档位), …)`，**按分数降序**。

    顺序即短路语义：`evaluate()` 用 `next(...)` 取**第一个**满足
    `score >= 下限` 的档位，所以必须降序（旧的 `_THRESHOLD` 就是降序
    字面量）。默认值下这里拼出来的就是 `((80,"human"),(65,"pause"),
    (45,"slow"),(25,"watch"))`，与搬家前逐位一致。

    排序防的是**非单调配置**（`pause: 30` 而 `slow: 70`）：不排序时结果取决于
    四个 pid 的声明顺序，同一分数在「界面配的值」与「代码里的顺序」之间打架；
    排序后档位一律由「分数所达到的**最高**那道门」决定，与声明顺序无关。
    （注意这不是「越保守越好」的单调保证——把 `human` 配成 40、`pause` 留在
    65，50 分仍判 `pause`，因为 65 才是它够得着的最高一道门。）

    低于最小分界一律 `calm`（等价旧表末尾那条 `(0, "calm")` 兜底）。

    `warn` 收坏值说明句（`evaluate()` 传的是本次的 `reasons`）。
    """
    pairs = [(_coerce("levels.%s" % k, int, warn, plat), k)
             for k in ("human", "pause", "slow", "watch")]
    pairs.sort(key=lambda x: x[0], reverse=True)
    return tuple(pairs)


def _levels_on(warn: list = None, plat: str = "") -> tuple:
    """分档线**在生效时**才返回四道门；`risk_bands.enabled=False` → 只有一个 calm。

    r1063 T12c：风险分档是「处置」的一部分——关掉它，风险分仍然照算、面板照显
    （关处置不关记账），只是不再据此改姿态（`calm` 通路：不降速、不停手）。
    """
    if not _on("risk_bands.enabled", plat):
        return ((0, "calm"),)
    return _levels(warn, plat)


def _as_ladder(raw) -> tuple:
    """把阶梯值收成 `(秒, …)`；不是「真列表 + 非空 + 非负整数」就抛 `ValueError`。

    校验比 `_coerce` 严，因为这个参数的载荷是**列表**：`"0,90,300"`（字符串）
    会被逐字符迭代成 `[0, 9, 0, …]`，比「类型不对」糟得多
    （`strategy_params._to_kind` 对 `list` 是原样透传，不做类型强转）。
    半截阶梯等于把退避策略改成随机数，所以宁可整体退回默认。
    """
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise ValueError("不是列表：%r" % (raw,))
    vals = tuple(int(v) for v in raw)
    if not vals or any(v < 0 for v in vals):
        raise ValueError("阶梯为空或有负值：%r" % (raw,))
    return vals


def _backoff_ladder(warn: list = None, plat: str = "") -> tuple:
    """登录退避阶梯（秒），**每次调用现读参数层**；坏配置退回默认值并留话。

    兜底两级：① 配置写坏 → 目录里的 `Param.default`；② 连默认值都坏
    （目录被改坏）→ `LOGIN_BACKOFF` 常量。`except` 分支里绝不二次抛异常：
    本函数被 `note_result()` 的写盘路径调用，那里没有任何 `try`。
    """
    pid = RISK_PIDS["login_backoff_s"]
    param = sp.PARAMS[pid]
    raw = sp.resolve(pid, plat=plat).value
    try:
        return _as_ladder(raw)
    except (TypeError, ValueError):
        _say_bad(param, raw, warn)
        try:
            return _as_ladder(param.default)
        except (TypeError, ValueError):
            return tuple(LOGIN_BACKOFF)


# ---------------------------------------------------------------------------
# 评分
# ---------------------------------------------------------------------------
def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def evaluate(signals: dict) -> dict:
    """按可观测信号算风险分。返回 ``{score, level, advice, reasons,
    device_driven}``；``signals`` 缺失的项按 0 计（不猜）。

    分界在**这一刻**从参数层现读（`crawler.risk.levels.*`）；`signals` 里带
    ``plat`` 时按该渠道求值，于是 `risk_bands` 声明的 channel 级覆盖真生效。
    """
    s = signals if isinstance(signals, dict) else {}
    score = 0.0
    reasons = []
    device_points = 0.0

    # 1) HTTP 拒绝
    codes = [int(_num(c)) for c in (s.get("statuses") or [])]
    hard = [c for c in codes if c in (403, 429, 503)]
    if hard:
        score += 28
        reasons.append("HTTP %s（服务端明确拒绝）" % ",".join(map(str, hard)))
    # 2) 软拒
    if s.get("soft") or 202 in codes or 444 in codes:
        score += 14
        reasons.append("软拒（202 空体 / 444 断连）")
    # 3) 人机挑战
    if s.get("captcha"):
        score += 30
        reasons.append("滑块/点选/人机验证已出现")
    # 4) 登录墙
    if s.get("login_wall"):
        score += 18
        reasons.append("登录墙（会话已失效）")
    # 5) 登录失败连击：**这一项是「越试越糟」的量化**
    streak = int(_num(s.get("login_fail_streak")))
    if streak > 0:
        add = min(30.0, 6.0 * streak)
        score += add
        reasons.append("登录连续失败 %d 次（+%d）" % (streak, int(add)))
        device_points += add * 0.5
    # 6) 身份/隐藏自检
    for key, label in (("identity_score", "设备身份"), ("stealth_score", "root/模拟器")):
        val = s.get(key)
        if val is None:
            continue
        gap = max(0.0, 100.0 - _num(val))
        if gap > 0:
            add = gap / 4.0
            score += add
            reasons.append("%s自检 %d 分（残留 +%d）" % (label, int(_num(val)),
                                                        int(add)))
            device_points += add
    # 7) 限速压力
    if s.get("rate_pressure"):
        score += 12
        reasons.append("本渠道限速压力已满（wait_hint>0）")

    score = max(0.0, min(100.0, round(score, 1)))
    # 分界在**这一刻**现读（参数层）：降序短路，第一个够得着的档位胜出；
    # 低于最小分界 → calm。坏配置的说明句直接落进本次 reasons。
    plat = str(s.get("plat") or "")
    level = next((lv for lo, lv in _levels_on(reasons, plat) if score >= lo),
                 "calm")
    # 设备项主导（占分过半）且已到 human 档 → 建议换身份
    if level == "human" and device_points >= score * 0.5:
        level = "rotate"
        reasons.append("命中项以设备为主：降速无效，需换身份")
    return {
        "score": score,
        "level": level,
        "advice": dict(ADVICE.get(level, ADVICE["calm"])),
        "reasons": reasons,
        "device_driven": device_points >= score * 0.5,
    }


# ---------------------------------------------------------------------------
# 登录账本（跨进程持久化）
# ---------------------------------------------------------------------------
class LoginLedger:
    """每个渠道的登录尝试/失败记录，落 ``user_data/login_ledger.json``。

    为什么必须持久化：程序按 30 分钟一轮跑、经常重启（打包版尤其），
    内存里的连击数一重启就清零，于是「今天已经失败 5 次」被忘掉，第 6 次
    照常去打——**这就是「越重登越登不上」的机制**。

    ``backoff_s()`` 返回"现在还不该试，请等 N 秒"；``note_ok()`` 清零。
    """

    def __init__(self, path: str):
        self.path = str(path)
        self.data = self._load()

    # --- 持久化 ---
    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2,
                          sort_keys=True)
            os.replace(tmp, self.path)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def rec(self, plat: str) -> dict:
        r = self.data.get(str(plat))
        if not isinstance(r, dict):
            r = {}
            self.data[str(plat)] = r
        for k in ("attempts", "fails", "streak", "last_attempt", "last_ok",
                  "last_fail", "next_allowed", "device_risk"):
            r.setdefault(k, 0 if k not in ("last_ok",) else 0)
        return r

    # --- 记录 ---
    def note_attempt(self, plat: str, now: float = None) -> dict:
        r = self.rec(plat)
        r["attempts"] = int(r.get("attempts") or 0) + 1
        r["last_attempt"] = float(now if now is not None else time.time())
        self._save()
        return r

    def note_result(self, plat: str, ok: bool, *, device_risk: bool = False,
                    now: float = None) -> dict:
        ts = float(now if now is not None else time.time())
        r = self.rec(plat)
        if ok:
            r["streak"] = 0
            r["last_ok"] = ts
            r["next_allowed"] = 0
        else:
            r["fails"] = int(r.get("fails") or 0) + 1
            r["streak"] = int(r.get("streak") or 0) + 1
            r["last_fail"] = ts
            if device_risk:
                r["device_risk"] = int(r.get("device_risk") or 0) + 1
            r["next_allowed"] = ts + self.backoff_s(plat, now=ts)
        self._save()
        return r

    # --- 查询 ---
    def backoff_s(self, plat: str, now: float = None) -> int:
        """下一次允许尝试前应等的秒数（按连击数上阶梯）。

        阶梯在**这一刻**从参数层现读（`crawler.risk.login_backoff_s`，可带渠道
        覆盖）；`streak` 超界取末元素——等价旧的
        `LOGIN_BACKOFF[min(n, len(LOGIN_BACKOFF) - 1)]`。参数层不可用/被写坏时
        退回默认阶梯，绝不抛（本方法在 `note_result()` 的写盘路径上）。
        """
        r = self.rec(plat)
        n = int(r.get("streak") or 0)
        ladder = _backoff_ladder(plat=str(plat or ""))
        idx = min(max(0, n), len(ladder) - 1)
        return int(ladder[idx])

    def wait_s(self, plat: str, now: float = None) -> int:
        """现在还不能试 → 剩余秒数；可以为 0。"""
        ts = float(now if now is not None else time.time())
        r = self.rec(plat)
        nxt = _num(r.get("next_allowed"))
        return max(0, int(nxt - ts)) if nxt else 0

    def allow(self, plat: str, now: float = None) -> bool:
        return self.wait_s(plat, now=now) <= 0

    def should_rotate(self, plat: str) -> bool:
        """设备风险计数 ≥3 且连击 ≥2 → 建议换身份（不自动执行）。

        `rotate_advice.enabled` 关掉 → 不再给这条建议（它只建议、从不执行，
        所以关掉就是「别在面板上催我换身份」；设备风险计数照旧累积）。
        """
        if not _on("rotate_advice.enabled", plat):
            return False
        r = self.rec(plat)
        return int(r.get("device_risk") or 0) >= 3 and int(r.get("streak") or 0) >= 2

    def signals(self, plat: str) -> dict:
        r = self.rec(plat)
        return {"login_fail_streak": int(r.get("streak") or 0)}


def default_ledger(user_data_dir: str = "user_data",
                   profile: str = "") -> LoginLedger:
    base = os.path.join(str(user_data_dir), str(profile)) if profile \
        else str(user_data_dir)
    return LoginLedger(os.path.join(base, "login_ledger.json"))


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
def assess(plat: str, *, ledger: LoginLedger = None, statuses=None,
           soft=False, captcha=False, login_wall=False,
           identity_score=None, stealth_score=None,
           rate_pressure=False, blocked=False) -> dict:
    """一句话入口：``assess("ctrip", ledger=led)`` → 评分 + 建议。

    ``blocked`` 只接受、不参与打分：App 账本里的 ``blocked`` 同时包含
    「人机验证」和「关不掉的广告/ANR」，后者不是风控信号。传进来只是让
    调用方能无脑透传账本键，不会因为是「被挡住」就被算成命中。
    """
    sig = {"statuses": list(statuses or []), "soft": soft,
           "captcha": captcha, "login_wall": login_wall,
           "identity_score": identity_score, "stealth_score": stealth_score,
           "rate_pressure": rate_pressure,
           # 渠道名进 signals 只为了让 `risk_bands` 的 channel 级覆盖生效
           # （分界参数带 plat 求值）；它不参与打分，也不会出现在返回里
           # （返回的 `plat` 由下面那行写，与这里同一个值）。
           "plat": str(plat or "")}
    if ledger is not None:
        try:
            sig.update(ledger.signals(plat))
        except Exception:
            pass
    out = evaluate(sig)
    out["plat"] = str(plat)
    if ledger is not None:
        try:
            out["login_wait_s"] = ledger.wait_s(plat)
            out["rotate_suggested"] = ledger.should_rotate(plat)
        except Exception:
            pass
    return out
