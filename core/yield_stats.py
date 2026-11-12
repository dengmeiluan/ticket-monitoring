# -*- coding: utf-8 -*-
"""爬取率账本：把「成功率」变成可以算、可以比较、可以驱动决策的数。

为什么需要（这是「提升爬取率」的前提）
------------------------------------
现在程序里散落着很多**单轮事实**：`path_note` 记「这一条路径这次怎么了」，
`ChannelBreaker` 记「这个渠道要不要冷却」，健康面板按日志文本估一个百分比。
但没有人回答这三个问题：

  1. 这个渠道最近 24 小时**真实**爬取率是多少？（不是「有没有报错」，是
     成功取到 ≥1 行数据的比例）
  2. 它的**哪条路径**在撑住？（PC 列表 / H5 列表 / API / 日历）
  3. 既然这么差，**间隔该调成多少**才既不浪费轮次、又不继续喂失败样本？

没有这三个数，「提升爬取率」只能靠感觉：调快怕封，调慢怕漏。

口径（刻意选窄、可复现）
-----------------------
* 一次 `safe_fetch` = 一个样本。**`rows > 0` 才算 ok**，`login/blocked/
  soft_reject/timeout/parse_error` 全算 fail——这与仓库「账本只记事实、
  未登录绝不记 empty」同一条纪律。
* 区间用 **Wilson 下界**，不是点估计：样本 3 次成功 3 次时下界只有 0.44，
  不会让程序误以为「100% 稳」而加速。仓库既往的教训（`health_min_samples`
  小于 5 不判、按路径行算成功率会罚错整家渠道）都指向同一个方向。
* 落盘 `user_data/<profile>/yield_stats.json`，**只做统计不做决策**：
  决策由调用方（`recommend_interval()` 的返回值 / 人）拿数去改配置。
  这样它坏了最多是少一张报表，不会把采集带崩。

与既有模块的边界
----------------
``core/pacing.py`` 管**限负荷**（TTL 分层、令牌桶、熔断），本模块只管
**度量与建议**。两者不互相写对方的状态，避免把已经被 852 个测试钉住的
节奏逻辑改出回归。
"""
from __future__ import annotations

import json
import math
import os
import time

FILE_NAME = "yield_stats.json"

# 需要多少样本才敢给建议（与 crawler.health_min_samples 同一口径）
MIN_SAMPLES = 5

# 各路径状态里，哪些算「取到数了」（其余一律算失败）
OK_STATUS = ("ok", "calendar")


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def wilson(ok: int, n: int, z: float = 1.64) -> tuple:
    """Wilson 区间下界/上界（z=1.64 ≈ 90% 置信）。n=0 返回 (0,1)。"""
    n = int(n or 0)
    ok = max(0, min(int(ok or 0), n))
    if n <= 0:
        return (0.0, 1.0)
    p = ok / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


class YieldLedger:
    """按渠道 / 路径 / 小时聚合的成功率账本（原子写、坏文件不致命）。"""

    def __init__(self, path: str):
        self.path = str(path)
        self.data = self._load()

    # ---------- 持久化 ----------
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

    # ---------- 记录 ----------
    def _plat(self, plat: str) -> dict:
        rec = self.data.get(str(plat))
        if not isinstance(rec, dict):
            rec = {}
            self.data[str(plat)] = rec
        rec.setdefault("paths", {})
        rec.setdefault("hours", {})
        rec.setdefault("total", {"ok": 0, "fail": 0, "rows": 0})
        return rec

    def note(self, plat: str, path: str, ok: bool, rows: int = 0,
             now: float = None, status: str = "",
             detail: str = "") -> dict:
        """记一次采集结果。返回该路径的累计记录。

        ``status``（可选）只做**观测**用：累加进该路径的 ``st`` 直方图。
        没有它的话，账本里 ``fail`` 会把"站点确实没票（empty）"、
        "解析/交互失败（error/timeout）"、"登录墙（login/captcha）"
        混成一个数字——三者处置方向完全不同（2026-11-05）。
        它**不影响** ok/fail 判定：``empty`` 仍然算"没取到数"，
        新增的只是"为什么没取到"。老账本没有 ``st`` 键，读时用 .get 兜底。
        """
        ts = float(now if now is not None else time.time())
        rec = self._plat(plat)
        key = str(path or "unknown")
        p = rec["paths"].setdefault(key, {"ok": 0, "fail": 0, "rows": 0,
                                          "last": 0.0})
        _st = str(status or "").strip()
        if _st:
            hist = p.setdefault("st", {})
            hist[_st] = int(hist.get(_st) or 0) + 1
        # `why`＝最后一次的**原因原文**（r1063 T75）：只留一条，截断，
        # 否则"为什么失败"只能靠翻日志。
        _d = str(detail or "").strip()
        if _d:
            p["why"] = _d[:120]
        if ok:
            p["ok"] = int(p.get("ok") or 0) + 1
            rec["total"]["ok"] = int(rec["total"].get("ok") or 0) + 1
        else:
            p["fail"] = int(p.get("fail") or 0) + 1
            rec["total"]["fail"] = int(rec["total"].get("fail") or 0) + 1
        p["rows"] = int(p.get("rows") or 0) + int(rows or 0)
        p["last"] = ts
        if ok:
            rec["total"]["rows"] = int(rec["total"].get("rows") or 0) \
                + int(rows or 0)
        # 按小时：用来找「这个渠道在这个钟点基本没戏」
        hour = str(time.localtime(ts).tm_hour)
        h = rec["hours"].setdefault(hour, {"ok": 0, "fail": 0})
        h["ok" if ok else "fail"] = int(h.get("ok" if ok else "fail") or 0) + 1
        self._save()
        return p

    # ---------- 查询 ----------
    def rate(self, plat: str, path: str = None) -> float:
        rec = self._plat(plat)
        if path:
            p = rec["paths"].get(str(path)) or {}
            ok, n = int(p.get("ok") or 0), int(p.get("ok") or 0) + int(
                p.get("fail") or 0)
        else:
            t = rec["total"]
            ok = int(t.get("ok") or 0)
            n = ok + int(t.get("fail") or 0)
        return (ok / n) if n else 0.0

    def samples(self, plat: str, path: str = None) -> int:
        rec = self._plat(plat)
        if path:
            p = rec["paths"].get(str(path)) or {}
            return int(p.get("ok") or 0) + int(p.get("fail") or 0)
        t = rec["total"]
        return int(t.get("ok") or 0) + int(t.get("fail") or 0)

    def bounded_rate(self, plat: str, path: str = None) -> tuple:
        """(下界, 上界, 样本数)：`recommend_interval` 只看下界。"""
        rec = self._plat(plat)
        if path:
            p = rec["paths"].get(str(path)) or {}
            ok = int(p.get("ok") or 0)
            n = ok + int(p.get("fail") or 0)
        else:
            t = rec["total"]
            ok = int(t.get("ok") or 0)
            n = ok + int(t.get("fail") or 0)
        lo, hi = wilson(ok, n)
        return (lo, hi, n)

    def path_rank(self, plat: str) -> list:
        """按成功率排路径（低样本量的排后面，不拿 1/1 当满分）。"""
        rec = self._plat(plat)
        out = []
        for name, p in (rec.get("paths") or {}).items():
            ok = int(p.get("ok") or 0)
            n = ok + int(p.get("fail") or 0)
            lo, hi = wilson(ok, n)
            out.append({"path": name, "ok": ok, "n": n,
                        "rate": (ok / n) if n else 0.0,
                        "lower": round(lo, 3), "rows": int(p.get("rows") or 0),
                        # 状态直方图：ok/fail 只说明"有没有取到数"，
                        # st 说明"为什么"（empty=没票 / error=解析 /
                        # login=登录墙）。老账本没有 st，给空 dict。
                        "st": dict(p.get("st") or {})})
        out.sort(key=lambda r: (-r["lower"], -r["n"]))
        return out

    def dead_hours(self, plat: str, min_samples: int = 3) -> list:
        """常年失败的钟点（供 schedule 的 scan_quiet 参考，不自动改）。"""
        rec = self._plat(plat)
        dead = []
        for hour, h in (rec.get("hours") or {}).items():
            ok = int(h.get("ok") or 0)
            n = ok + int(h.get("fail") or 0)
            if n >= min_samples and ok == 0:
                dead.append(int(hour))
        return sorted(dead)

    # ---------- 建议 ----------
    def note_phases(self, plat: str, rows) -> dict:
        """记一次采集的**分段耗时**（r1063 T77）：`{阶段: {n, total_s}}`。

        与 `note()` 分开存：那是成功率账，这是耗时账，两者别搅在一起。
        只留最近 12 个阶段名（阶段名是代码里写死的，不会无限增长）。
        """
        rec = self._plat(plat)
        ph = rec.setdefault("phases", {})
        for r in (rows or []):
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            try:
                dt = float(r.get("s") or 0)
            except (TypeError, ValueError):
                continue
            cur = ph.setdefault(name, {"n": 0, "total_s": 0.0})
            cur["n"] = int(cur.get("n") or 0) + 1
            cur["total_s"] = round(float(cur.get("total_s") or 0) + dt, 1)
        if len(ph) > 12:
            keep = sorted(ph.items(), key=lambda kv: -float(kv[1].get(
                "total_s") or 0))[:12]
            rec["phases"] = dict(keep)
        self._save()          # 真实方法名是 `_save`（没有公开 `save`）
        return dict(rec.get("phases") or {})

    def recommend_interval(self, plat: str, base_min: int,
                           lo_ok: float = 0.9, lo_bad: float = 0.4) -> dict:
        """按 Wilson 下界给「间隔该调成多少分钟」。

        规则（保守优先，宁可慢一点也别喂失败样本——重试风暴是唯一能把
        「限你」升级成「封你」的动作）：

        ============  ==========================================
        Wilson 下界    建议
        ============  ==========================================
        ≥0.90          0.8×（有余量，可以多跑）
        ≥0.70          1.0×（维持）
        ≥0.40          1.5×（降负荷）
        <0.40          2.5×（大幅降，先修因果链）
        样本 <5        1.0×（不判，避免首轮误伤）
        ============  ==========================================
        """
        base = max(1, int(_num(base_min, 30)))
        lo, hi, n = self.bounded_rate(plat)
        if n < MIN_SAMPLES:
            return {"minutes": base, "factor": 1.0, "samples": n,
                    "lower": round(lo, 3),
                    "why": "样本不足（%d<%d），按基准" % (n, MIN_SAMPLES)}
        if lo >= lo_ok:
            return {"minutes": max(1, int(round(base * 0.8))), "factor": 0.8,
                    "samples": n, "lower": round(lo, 3),
                    "why": "下界 %.2f ≥ %.2f，有余量" % (lo, lo_ok)}
        if lo >= 0.70:
            return {"minutes": base, "factor": 1.0, "samples": n,
                    "lower": round(lo, 3), "why": "下界 %.2f，维持基准" % lo}
        if lo >= lo_bad:
            return {"minutes": max(1, int(round(base * 1.5))), "factor": 1.5,
                    "samples": n, "lower": round(lo, 3),
                    "why": "下界 %.2f，降负荷 1.5×" % lo}
        return {"minutes": max(1, int(round(base * 2.5))), "factor": 2.5,
                "samples": n, "lower": round(lo, 3),
                "why": "下界 %.2f < %.2f，先修因果链再谈频率" % (lo, lo_bad)}

    def snapshot(self, exclude_infra: bool = False) -> dict:
        """给面板/日志的整体视图。

        ``exclude_infra=True`` 时按**通路**重算样本：跳过 ``INFRA_PATHS``
        （快照恢复/运行时/解析兜底——它们的成败说明的是设备状态，
        不是站点对采集的反应）。``total`` 是历史累计，含 ``is_non_attempt``
        上线前的旧数，改不了；只有在读侧剔除，顶行才等于真实采集口径
        （app_zhixing 实测 0.60 → 0.99）。
        """
        out = {}
        for plat, rec in self.data.items():
            t = rec.get("total") or {}
            ok = int(t.get("ok") or 0)
            n = ok + int(t.get("fail") or 0)
            if exclude_infra:
                ok = 0
                n = 0
                for name, p in (rec.get("paths") or {}).items():
                    if str(name) in NO_SAMPLE_PATHS:
                        continue
                    _ok = int(p.get("ok") or 0)
                    ok += _ok
                    n += _ok + int(p.get("fail") or 0)
            lo, hi = wilson(ok, n)
            out[plat] = {
                "ok": ok, "n": n, "rows": int(t.get("rows") or 0),
                "rate": round((ok / n) if n else 0.0, 3),
                "lower": round(lo, 3), "upper": round(hi, 3),
                "paths": self.path_rank(plat),
                "dead_hours": self.dead_hours(plat),
            }
        return out


def user_data_root(config=None, default: str = "user_data") -> str:
    """账本根目录（**唯一口径**）。

    优先级：config 显式值 > 环境变量 ``TM_USER_DATA_DIR`` > ``default``。

    为什么要有环境变量这一层（2026-11-05，同类第三次）：
    测试里的假渠道（app_demo / probe / app_dummy）按"模块默认路径"把账本
    写进了**真实** ``user_data/``，于是 ``scripts/yield_report.py`` 把它们
    当成真渠道渲染成 0% 成功率，还给出"建议间隔 75 分钟"——污染了爬取率
    这张决策表。写点分散在 4 处，逐用例打补丁注定漏，所以按 conftest 既有
    惯例（PUSH_HISTORY_FILE / TM_RENDER_DIR 同律）做**集中重定向**。

    为什么 config 优先：生产 ``main.py`` 总会显式传绝对 ``user_data_dir``；
    而"显式传 tmp 并断言落在那里"的既有用例也不该被环境变量改写。

    但**显式传默认值不算显式配置**（2026-11-05 补）：`{"user_data_dir":
    "user_data"}` 与不传等价，全仓 16 个测试文件 22 处都这么写；把它当
    显式配置的话，集中重定向就永远漏这些用例，脏账本会继续长出来。
    """
    cfg = config if isinstance(config, dict) else {}
    dflt = str(default or "user_data").strip() or "user_data"
    root = str(cfg.get("user_data_dir") or "").strip()
    # **显式传默认值 ≠ 显式配置**：`{"user_data_dir": "user_data"}` 与
    # 不传该键在语义上完全等价（都是"用默认目录"）。全仓 16 个测试文件、
    # 22 处都这么写，逐处改注定漏，且下个新用例还会这么写。
    # 所以把默认值当哨兵：等于它就继续往下走（可被重定向），
    # 只有**真的换了目录**（绝对路径如生产的 session_root，或别的相对名）
    # 才算显式配置并优先返回。
    if root and os.path.normpath(root) != os.path.normpath(dflt):
        return root
    env = str(os.environ.get("TM_USER_DATA_DIR") or "").strip()
    return env or root or dflt


def default_ledger(user_data_dir: str = "user_data",
                   profile: str = "") -> YieldLedger:
    base = os.path.join(str(user_data_dir), str(profile)) if profile \
        else str(user_data_dir)
    return YieldLedger(os.path.join(base, FILE_NAME))


def is_paced(paths) -> bool:
    """这一轮是不是**我方主动没发请求**（配额让位/节流跳过）。

    判据：所有路径状态都是 ``paced``（一条都没真发）。只要有一条真跑过
    （哪怕是 timeout/soft_reject），这一轮就是真实样本。

    为什么要有这个概念（2026-11-04）：qunar 国际航线有"配额让位"——
    软空一次就 900s 不再查其它国际线。让位原先被记成 ``soft_reject``，
    于是"我方主动让步"被算成"渠道失败"，账面成功率只剩 50%，
    让人误以为去哪儿被风控了，实际它只是在守配额。
    """
    recs = [r for r in (paths or []) if isinstance(r, dict)]
    if not recs:
        return False
    return all(str(r.get("status") or "") == "paced" for r in recs)


# **基础设施通路**：它们的成败说明的是"设备/恢复/运行时"的状态，
# 不是站点对采集的反应。把它们混进渠道成功率，会把"我方没尝试"
# 记成"渠道失败"。
INFRA_PATHS = ("snap-restore", "android-runtime", "android-device",
               "app-dump", "app-error")

#: 读侧算成功率时要剔除的通路 = 基础设施 + 明确"没发起查询"的两类。
#:   * ``TRIP``    —— 往返明细本渠道不支持（状态 ``unsupported``）；
#:   * ``unknown`` —— ``app-silent`` 上线前的旧轮次，连通路都没记。
#: 两者都不是采集尝试；把它们算进分母，实测把 app_qunar 从 0.28 拖到 0.09，
#: 让人误判成"整个渠道几乎全挂"。
NO_SAMPLE_PATHS = INFRA_PATHS + ("TRIP", "unknown")


def is_non_attempt(paths) -> bool:
    """这一轮**根本没有真正尝试采集**（不支持的通路 / 纯基础设施步骤）。

    为什么需要（2026-11-05 实测）：`app_zhixing` 的账本里
    数据通路 `日历` 成功率 **0.99(636)**，可整渠道被算成 0.59 ——
    因为 266 条 `snap-restore`（登录态快照恢复，永远 rows=0）和
    52 条 `android-runtime/unsupported`（该通路本渠道不支持）
    全被当成"采集失败"进了分母。

    这与 `is_paced` 是**同一个病**（"我方主动让位"曾被算成"渠道失败"，
    账面成功率只剩 50%，让人误以为被风控）。原则也照搬：
    **不是采集尝试的轮次，不该进成功率样本**。

    判据（保守，宁可少判）：
      * 状态是 `paced`（我方让位）或 `unsupported`（本就不支持）→ 不算尝试；
      * 通路属于 `INFRA_PATHS`（快照恢复/运行时/解析兜底）→ 不算尝试；
      * 只要有一条是**真的打了站点**（ok/empty/timeout/soft_reject/login…）
        → 这一轮就是真实样本，照常计入（失败也照实记）。
    """
    recs = [r for r in (paths or []) if isinstance(r, dict)]
    if not recs:
        return False
    for r in recs:
        st = str(r.get("status") or "")
        pth = str(r.get("path") or "")
        if st in ("paced", "unsupported"):
            continue
        if pth in INFRA_PATHS:
            continue
        return False
    return True


def statuses_ok(paths) -> tuple:
    """从一轮 `path_note` 记录判断「这轮算不算取到数」。

    返回 ``(ok, rows, best_path)``：`ok` 表示至少一条路径拿到了行；
    `best_path` 是行数最多的那条路径名（用于按路径记账）。
    """
    ok, rows, best, best_rows = False, 0, "", 0
    for rec in paths or []:
        st = str(rec.get("status") or "")
        r = int(rec.get("rows") or 0)
        if st in OK_STATUS and r > 0:
            ok = True
            rows += r
            if r > best_rows:
                best, best_rows = str(rec.get("path") or ""), r
    return ok, rows, best or (str((paths or [{}])[0].get("path") or "")
                              if paths else "")
