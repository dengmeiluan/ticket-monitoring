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
"""
from __future__ import annotations

import json
import os
import time

LEVELS = ("calm", "watch", "slow", "pause", "human", "rotate")

# 档位 → (分数下限)。分数越高越靠后。
_THRESHOLD = ((80, "human"), (65, "pause"), (45, "slow"), (25, "watch"),
              (0, "calm"))

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

# 登录失败退避阶梯（秒）。第 n 次连击失败后应等这么久再试。
LOGIN_BACKOFF = (0, 90, 300, 900, 1800, 3600, 7200)


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
    device_driven}``；``signals`` 缺失的项按 0 计（不猜）。"""
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
    level = next(lv for lo, lv in _THRESHOLD if score >= lo)
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
        """下一次允许尝试前应等的秒数（按连击数上阶梯）。"""
        r = self.rec(plat)
        n = int(r.get("streak") or 0)
        idx = min(max(0, n), len(LOGIN_BACKOFF) - 1)
        return int(LOGIN_BACKOFF[idx])

    def wait_s(self, plat: str, now: float = None) -> int:
        """现在还不能试 → 剩余秒数；可以为 0。"""
        ts = float(now if now is not None else time.time())
        r = self.rec(plat)
        nxt = _num(r.get("next_allowed"))
        return max(0, int(nxt - ts)) if nxt else 0

    def allow(self, plat: str, now: float = None) -> bool:
        return self.wait_s(plat, now=now) <= 0

    def should_rotate(self, plat: str) -> bool:
        """设备风险计数 ≥3 且连击 ≥2 → 建议换身份（不自动执行）。"""
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
           "rate_pressure": rate_pressure}
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
