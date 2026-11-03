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
             now: float = None) -> dict:
        """记一次采集结果。返回该路径的累计记录。"""
        ts = float(now if now is not None else time.time())
        rec = self._plat(plat)
        key = str(path or "unknown")
        p = rec["paths"].setdefault(key, {"ok": 0, "fail": 0, "rows": 0,
                                          "last": 0.0})
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
                        "lower": round(lo, 3), "rows": int(p.get("rows") or 0)})
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

    def snapshot(self) -> dict:
        """给面板/日志的整体视图。"""
        out = {}
        for plat, rec in self.data.items():
            t = rec.get("total") or {}
            ok = int(t.get("ok") or 0)
            n = ok + int(t.get("fail") or 0)
            lo, hi = wilson(ok, n)
            out[plat] = {
                "ok": ok, "n": n, "rows": int(t.get("rows") or 0),
                "rate": round((ok / n) if n else 0.0, 3),
                "lower": round(lo, 3), "upper": round(hi, 3),
                "paths": self.path_rank(plat),
                "dead_hours": self.dead_hours(plat),
            }
        return out


def default_ledger(user_data_dir: str = "user_data",
                   profile: str = "") -> YieldLedger:
    base = os.path.join(str(user_data_dir), str(profile)) if profile \
        else str(user_data_dir)
    return YieldLedger(os.path.join(base, FILE_NAME))


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
