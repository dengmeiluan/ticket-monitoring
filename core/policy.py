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
============  ==========================================================

判定顺序（**短路，先重后轻**——这是"统一"的核心）
-----------------------------------------------
1. 登录侧被冻结（`LoginLedger.wait_s > 0`） → `blocked`，照它给的时间停；
2. `riskscore` 到 `human`/`rotate` 档 → `blocked` 1h（等人工过验证）；
3. 到 `pause` 档 → `blocked` 30min；
4. 到 `slow` 档 → `degraded`（2.5×）；
5. 到 `watch` 档 → `watch`（1.5×）；
6. 否则看产量：Wilson 下界 ≥0.90 且样本足 → `healthy` 但允许 0.8×；
   下界 <0.40 且样本 ≥8 → `degraded`（1.5×，理由写「先修因果链」）；
   其余 `healthy`。

为什么产量**不能**直接触发停手：真无票、真冷门航线都会让成功率掉下来，
它们和风控无关。产量只能调**速度**，不能调**开关**——这条边界写死在这里，
免得以后有人为了让报表好看去停一个健康的渠道。

状态机（`blocked → rehab → healthy`）
------------------------------------
`blocked` 到期后不会立刻回到 `healthy`，先给一个 `rehab`（恢复期）：
倍率仍 1.5×、`need_warmup=True`，**成功一次就转正**。理由很实在——刚被
拦过的会话，第一次请求最容易再触发一次；直接满速等于把刚恢复的渠道再打回去。
"""
from __future__ import annotations

import json
import os
import time

STATE_FILE = "policy_state.json"

# 状态枚举（顺序即「从好到坏」，便于比较）
STATES = ("healthy", "rehab", "watch", "degraded", "blocked")

# 各状态的基础倍率（后续会被 riskscore 档位覆盖）
_PACE = {
    "healthy": 1.0,
    "rehab": 1.5,
    "watch": 1.5,
    "degraded": 2.5,
    "blocked": 3.0,
}

# blocked 的默认时长（秒）：人工档更久
_BLOCK_S = {"human": 3600, "rotate": 3600,
            "pause": 0, "slow": 0, "watch": 0}

# 余温窗口（秒）：watch/degraded 的证据在窗口内继续生效，过点自动失效。
# 取 30/60 分钟是因为定时采集一轮本身就是 30 分钟——窗口略大于一轮，
# 保证「上一轮的教训下一轮还没忘」，但不会变成永久降速。
_STICKY_S = {"watch": 1800, "degraded": 3600, "rehab": 1800}


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


class ChannelPolicy:
    """一个渠道一次的完整决定。不可变语义：构造后只读。"""

    __slots__ = ("plat", "state", "allow", "stop_until", "pace_factor",
                 "humanize", "need_warmup", "rotate", "reasons", "score",
                 "decided_at")

    def __init__(self, plat, state="healthy", allow=True, stop_until=0.0,
                 pace_factor=1.0, humanize=1.0, need_warmup=False,
                 rotate=False, reasons=None, score=0.0, decided_at=0.0):
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
        root = str(self.config.get("user_data_dir") or user_data_dir
                   or "user_data")
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
        d = _load(self.state_path)
        return d if isinstance(d, dict) else {}

    def _save_state(self, plat: str, state: str, until: float = 0.0) -> None:
        try:
            d = self._state()
            rec = d.get(plat) if isinstance(d.get(plat), dict) else {}
            rec.update({"state": state, "until": float(until or 0.0),
                        "at": time.time()})
            d[plat] = rec
            os.makedirs(self.base_dir, exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.state_path)
        except (OSError, ValueError, TypeError):
            pass

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
        prev = self._prev(plat)

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
        try:
            from core.riskscore import evaluate
            got = evaluate({
                "statuses": list(statuses or []), "soft": soft,
                "captcha": captcha, "login_wall": login_wall,
                "login_fail_streak": streak,
                "identity_score": identity_score,
                "stealth_score": stealth_score,
                "rate_pressure": rate_pressure,
            })
            score, level, dev = got["score"], got["level"], got["device_driven"]
            reasons.extend(got.get("reasons") or [])
        except Exception:
            pass

        if level in ("human", "rotate"):
            block = _BLOCK_S.get(level, 3600)
            reasons.append("风险 %.0f（%s）：等人工过验证/重登" % (score, level))
            if not two_way:
                self._save_state(plat, "blocked", ts + block)
            return ChannelPolicy(plat, "blocked", False, ts + block, 3.0, 2.0,
                                 True, rotate, reasons, score, ts)
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
        prev_until = float(prev.get("until") or 0.0)
        if prev_state == "blocked" and prev_until > ts:
            reasons.append("仍在上次停手窗口内（剩 %d 分钟）"
                           % int((prev_until - ts) // 60 + 1))
            return ChannelPolicy(plat, "blocked", False, prev_until, 3.0, 2.0,
                                 True, rotate, reasons, score, ts)

        # ---- 4. 恢复期：blocked 刚到期，先慢跑一轮，成功一次就转正 ----
        if prev_state == "blocked" and prev_until and ts >= prev_until:
            reasons.append("恢复期：先慢跑一轮（1.5×），成功即转正")
            if not two_way:
                self._save_state(plat, "rehab", ts + _STICKY_S["rehab"])
            return ChannelPolicy(plat, "rehab", True, 0.0, 1.5, 1.5, True,
                                 rotate, reasons, score, ts)

        # pause 档在**本层**不关闸（短时冷却归熔断器），但要压到最慢一档；
        # slow 档 2.5×；watch 档 1.5×。
        state = {"pause": "degraded", "slow": "degraded",
                 "watch": "watch"}.get(level, "healthy")
        pace = _PACE.get(state, 1.0)
        if level == "pause":
            pace = 3.0
            reasons.append("风险 %.0f（pause）：压到最慢档，短时冷却由熔断器接管"
                           % score)

        # ---- 4. 产量只调速度，不调开关 ----
        if n >= 8 and lo < 0.40:
            state = "degraded"
            pace = max(pace, 1.5)
            reasons.append("产量下界 %.2f（%d 样本）：先修因果链（预热/锁/登录）"
                           % (lo, n))
        elif n >= 8 and lo >= 0.90 and state == "healthy":
            pace = 0.8
            reasons.append("产量下界 %.2f（%d 样本）：有余量，可加频" % (lo, n))
        elif n and n < 8:
            reasons.append("产量样本 %d <8，不据此调整" % n)

        # 设备项占主导但还没到 human 档：提前提示换身份（不自动）
        if dev and not rotate and score >= 45:
            rotate = False
            reasons.append("命中项以设备为主：降到 pause 前建议评估换身份")

        # 登录退避在场：至少降一档速，并且下次必须先预热（会话没养熟别打深链）
        if wait > 0 and state == "healthy":
            state = "rehab"
            pace = max(pace, _PACE["rehab"])

        # ---- 5. 余温：上一轮的 watch/degraded 在窗口内保留 ----
        #
        # 为什么需要：一轮滑块的证据只影响那一轮的话，下一轮（30 分钟后、
        # 不带任何信号）就回到满速，等于「记了不认」。这里给一个**有界**的
        # 记忆窗口（watch 30min / degraded 60min），过点自动失效——比
        # 无条件粘住安全得多，也不会像熔断器那样长期停机。
        keep_s = _STICKY_S.get(prev_state, 0)
        residue_until = 0.0
        if keep_s and prev_until and prev_until > ts:
            if STATES.index(prev_state) > STATES.index(state):
                state = prev_state
                pace = max(pace, _PACE[prev_state])
                # **沿用原到期时间，不续期**：否则每次查询都把窗口往后推
                # 3600s，余温永远不过期，等于永久降速（这正是"粘住"最坏的
                # 形态）。窗口属于事件发生的那一刻，不属于每次读数。
                residue_until = prev_until
                reasons.append("上轮 %s 的余温还在（%d 分钟内保留）"
                               % (prev_state, int((prev_until - ts) // 60) + 1))

        # 只在「状态变化」或「非健康」时落盘：健康的稳态每轮写一次毫无意义，
        # 还会让磁盘 IO 跟着采集轮次涨（一轮 5 个渠道 × 每轮都写）。
        if not two_way and (state != "healthy" or prev_state):
            until = residue_until or (ts + _STICKY_S.get(state, 0))
            self._save_state(plat, state, until)
        need_warm = bool(captcha or soft or login_wall or wait > 0
                         or state != "healthy")
        return ChannelPolicy(plat, state, True, 0.0, pace,
                             1.5 if state != "healthy" else 1.0,
                             need_warm, rotate, reasons, score, ts)

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
