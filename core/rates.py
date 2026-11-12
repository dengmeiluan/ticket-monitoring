# -*- coding: utf-8 -*-
"""三率一险（r1182）：爬取率 / 效率 / 速度 / 风险，按 渠道 × 通路 给出。

为什么要有
----------
v2.1 §2 要求把"风控降低、爬取率/效率/速度提升"落成**可比数字**，否则只是口号。
`core/baseline.py` 已经在算这些数（Markdown），但页面拿不到结构化版本——
本模块就是它的**结构化出口**，并且刻意不重写 SQL：

* 真出数的定义、行/次、独立日期数、平均耗时 → 全部来自 `baseline.by_path()`
  （唯一口径，`tests/test_r1182_rates.py::test_matches_baseline_by_path` 守着）；
* 本模块只额外算两件报表里没有的东西：**分母（总尝试次数）** 与 **p95 耗时**。

口径（写在返回值里，前端直接展示，不许另编）
--------------------------------------------
| 指标 | 定义 | 方向 |
|---|---|---|
| `yield` 爬取率 | 真出数行数 ÷ 该通路**全部尝试次数** | ↑ |
| `eff` 效率 | 真出数行数 ÷ 真出数次数（= baseline 的「行/次」） | ↑ |
| `p95_ms` 速度 | 真出数请求的 **单次请求耗时 p95**（毫秒） | ↓ |
| `risk` 风险 | 非真出数次数 ÷ 全部尝试次数（失败面占比） | ↓ |

诚实边界：`p95_ms` 量的是**单次请求耗时**，不是"探针→首批结果"的端到端 p95
（那个要 `core/phase_timer` 的链路计时，本轮没有接）。字段名与文案都不许冒充。
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from core import baseline

KINDS = {
    "yield": "爬取率（真出数次数 ÷ 全部尝试次数，0–100%）",
    "eff": "效率（真出数行 ÷ 出数次数 = 行/次）",
    "p95_ms": "速度（单次请求耗时 p95，毫秒）",
    "risk": "风险（失败次数 ÷ 全部尝试 = 100% − 爬取率）",
}


def _p95(vals: List[float]) -> Optional[int]:
    """最近秩法 p95（样本小也不装精确）。空样本返回 None，不返回 0 冒充"很快"。"""
    v = sorted(float(x) for x in vals)
    if not v:
        return None
    k = max(0, min(len(v) - 1, int(round(0.95 * (len(v) - 1)))))
    return int(v[k])


# r1822：这些状态**不该进分母**——它们是"没机会成功"或"我们主动不发"：
#   unsupported 能力边界（日期超出 App 视野等）
#   paced       节流/TTL 主动跳过
#   skipped     其它显式跳过
# 把它们算进分母，会让 App 渠道的成功率长期显示成个位数（实测同程 9.9%），
# 与"这家渠道其实一半查询能出数"的事实相反。
SKIP_STATUSES = ("unsupported", "paced", "skipped")


def snapshot(hours: int = 12, db: str = "") -> Dict:
    """返回三率一险的结构化快照（只读库，不碰网络）。"""
    db = db or baseline._db_path()
    out: Dict = {"ok": True, "hours": int(hours), "db": db, "kinds": dict(KINDS),
                 "by_path": [], "by_plat": {}, "totals": {}}
    ok_list = ",".join("'%s'" % s for s in baseline.OK_STATUSES)
    hours = int(hours)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        return {"ok": False, "err": "读不到数据库：%s" % str(e)[:120],
                "hours": hours, "db": db, "kinds": dict(KINDS),
                "by_path": [], "by_plat": {}, "totals": {}}

    try:
        # 分母：该 (渠道,通路) 的全部尝试（含失败面）
        attempts: Dict[tuple, int] = {}
        skipped: Dict[tuple, int] = {}
        _skip_list = ",".join("'%s'" % x for x in SKIP_STATUSES)
        for plat, path, n, sk in conn.execute(
                "select platform, entry_path, count(*), "
                "sum(case when path_status in (%s) then 1 else 0 end) "
                "from fetch_paths "
                "where fetched_at >= datetime('now','localtime','-%d hours') "
                "group by platform, entry_path"
                % (_skip_list, hours)):
            attempts[(plat, path)] = int(n or 0)
            skipped[(plat, path)] = int(sk or 0)

        # p95 需要原始样本：只取真出数且有耗时的行
        samples: Dict[tuple, List[float]] = {}
        if baseline._has_elapsed_ms(conn):
            for plat, path, ms in conn.execute(
                    "select platform, entry_path, elapsed_ms from fetch_paths "
                    "where fetched_at >= datetime('now','localtime','-%d hours') "
                    "and path_status in (%s) and elapsed_ms>0" % (hours, ok_list)):
                samples.setdefault((plat, path), []).append(float(ms))

        for r in baseline.by_path(conn, hours=hours):
            key = (r["plat"], r["path"])
            _rec = attempts.get(key, r["n"]) or 0
            _sk = int(skipped.get(key, 0) or 0)
            # r1822：能力边界/主动跳过不进分母，但要**报出来**
            tot = max(0, _rec - _sk)
            rows = r["rows"]
            item = {
                "plat": r["plat"], "path": r["path"],
                "attempts": tot, "ok_n": r["n"], "rows": rows,
                "records": _rec, "skipped_n": _sk,
                "dates": r["dates"],
                # 爬取率 = 几次尝试里成功几次（0–100%）；与风险互补。
                "yield": (r["n"] / float(tot)) if tot else None,
                # 每次尝试平均拿到几行（强度，可以 >1，不与风险互补）
                "rows_per_attempt": (rows / float(tot)) if tot else None,
                "eff": r["eff"],
                "p95_ms": _p95(samples.get(key) or []),
                "risk": ((tot - r["n"]) / float(tot)) if tot else None,
                "avg_ms": int(r["avg_ms"]) if r["avg_ms"] else None,
            }
            out["by_path"].append(item)
        # r1697：**只有尝试、没有成功**的通路也要出现。
        # 基线那条 SQL 只统计成功状态，于是 App 渠道的 app-city / app-form /
        # app-login 这些「一直失败」的通路在页面上压根不存在——
        # 失败面被统计口径藏起来了，这与「一切可统计」相反。
        _seen = {(r["plat"], r["path"]) for r in out["by_path"]}
        for (_p2, _pa2), _tot2 in attempts.items():
            if (_p2, _pa2) in _seen:
                continue
            _sk2 = int(skipped.get((_p2, _pa2), 0) or 0)
            _eff2 = max(0, int(_tot2) - _sk2)
            if _eff2 <= 0:
                # 全是能力边界/主动跳过：不是"0 出数"，单列并标出来
                out["by_path"].append({
                    "plat": _p2, "path": _pa2, "attempts": 0,
                    "ok_n": 0, "rows": 0, "dates": 0,
                    "yield": None, "rows_per_attempt": None,
                    "eff": None, "p95_ms": None, "risk": None,
                    "avg_ms": None, "no_ok": False,
                    "records": int(_tot2), "skipped_n": _sk2,
                    "skipped_only": True,
                })
                continue
            out["by_path"].append({
                "plat": _p2, "path": _pa2,
                "attempts": _eff2, "ok_n": 0, "rows": 0,
                "dates": 0, "yield": 0.0, "rows_per_attempt": 0.0,
                "eff": 0.0, "p95_ms": None, "risk": 1.0,
                "avg_ms": None, "no_ok": True,
                "records": int(_tot2), "skipped_n": _sk2,
            })
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 按渠道汇总（同一渠道多条通路求和后重算，不是比值再平均）
    acc: Dict[str, Dict] = {}
    for it in out["by_path"]:
        a = acc.setdefault(it["plat"], {"attempts": 0, "ok_n": 0, "rows": 0,
                                        "dates": 0, "samples": [],
                                        "skipped_n": 0})
        a["attempts"] += it["attempts"] or 0
        a["skipped_n"] = a.get("skipped_n", 0) + (it.get("skipped_n") or 0)
        a["ok_n"] += it["ok_n"] or 0
        a["rows"] += it["rows"] or 0
        a["dates"] = max(a["dates"], it["dates"] or 0)
        if it["p95_ms"]:
            a["samples"].append(it["p95_ms"])
    for plat, a in acc.items():
        out["by_plat"][plat] = {
            "attempts": a["attempts"], "ok_n": a["ok_n"], "rows": a["rows"],
            "skipped_n": a.get("skipped_n", 0),
            "dates": a["dates"],
            "yield": (a["ok_n"] / float(a["attempts"])) if a["attempts"] else None,
            "rows_per_attempt": ((a["rows"] / float(a["attempts"]))
                                 if a["attempts"] else None),
            "eff": (a["rows"] / float(a["ok_n"])) if a["ok_n"] else None,
            "p95_ms": max(a["samples"]) if a["samples"] else None,
            "risk": ((a["attempts"] - a["ok_n"]) / float(a["attempts"]))
                    if a["attempts"] else None,
        }
    ta = sum(v["attempts"] for v in out["by_plat"].values())
    to = sum(v["ok_n"] for v in out["by_plat"].values())
    tr = sum(v["rows"] for v in out["by_plat"].values())
    out["totals"] = {
        "attempts": ta, "ok_n": to, "rows": tr,
        "skipped_n": sum((v.get("skipped_n") or 0)
                         for v in out["by_plat"].values()),
        "yield": (to / float(ta)) if ta else None,
        "rows_per_attempt": (tr / float(ta)) if ta else None,
        "eff": (tr / float(to)) if to else None,
        "risk": ((ta - to) / float(ta)) if ta else None,
    }
    return out


def demo_snapshot(hours: int = 12) -> Dict:
    """演示模式的**合成**三率快照（与 `snapshot()` 同结构）。

    为什么要有：`snapshot()` 读真库（`baseline._db_path()`），演示实例没有真库，
    于是公开演示页与 CI 上的「三率一险」卡片永远是空表——看着像坏了，
    也让依赖「有行」的门禁在干净环境里必红。
    数值是合成的，`demo: True` 明确标出；页面本身已按演示态写「合成数据」。
    """
    rows = [
        ("ctrip", "PC", 32, 32, 3253, 1, 7200),
        ("ctrip", "H5", 32, 32, 1254, 5, 13400),
        ("fliggy", "PC", 30, 30, 2334, 6, 12800),
        ("tongcheng", "PC", 30, 29, 147, 5, 9800),
        ("tuniu", "PC·国际", 24, 24, 1397, 4, 22700),
        ("tuniu", "H5/API", 14, 14, 461, 3, 12000),
        ("app_zhixing", "日历", 6, 6, 281, 2, 34600),
        ("app_qunar", "航班明细", 18, 18, 18, 6, 35100),
    ]
    by_path = []
    for plat, path, att, ok_n, rw, dates, p95 in rows:
        by_path.append({
            "plat": plat, "path": path, "attempts": att, "ok_n": ok_n,
            "rows": rw, "dates": dates,
            "yield": round(ok_n / float(att), 4) if att else 0.0,
            "rows_per_attempt": round(rw / float(att), 3) if att else 0.0,
            "eff": round(rw / float(ok_n), 3) if ok_n else 0.0,
            "p95_ms": p95,
            "risk": round((att - ok_n) / float(att), 4) if att else 0.0,
            "avg_ms": int(p95 * 0.65),
        })
    att_t = sum(r["attempts"] for r in by_path)
    ok_t = sum(r["ok_n"] for r in by_path)
    rw_t = sum(r["rows"] for r in by_path)
    by_plat: Dict[str, Dict] = {}
    for r in by_path:
        p = by_plat.setdefault(r["plat"], {"attempts": 0, "ok_n": 0, "rows": 0})
        p["attempts"] += r["attempts"]
        p["ok_n"] += r["ok_n"]
        p["rows"] += r["rows"]
    for v in by_plat.values():
        v["yield"] = round(v["ok_n"] / float(v["attempts"]), 4) if v["attempts"] else 0.0
        v["risk"] = round(1 - v["yield"], 4)
        v["eff"] = round(v["rows"] / float(v["ok_n"]), 3) if v["ok_n"] else 0.0
    by_path.sort(key=lambda r: r["yield"], reverse=True)
    return {"ok": True, "demo": True, "hours": int(hours), "db": "(demo)",
            "kinds": dict(KINDS), "by_path": by_path, "by_plat": by_plat,
            "totals": {"attempts": att_t, "ok_n": ok_t, "rows": rw_t,
                       "yield": round(ok_t / float(att_t), 4) if att_t else 0.0,
                       "risk": round(1 - ok_t / float(att_t), 4) if att_t else 0.0,
                       "eff": round(rw_t / float(ok_t), 3) if ok_t else 0.0}}


def to_lines(snap: Dict, limit: int = 6) -> List[str]:
    """给页面/终端用的一行一句摘要（按爬取率降序）。"""
    rows = [r for r in (snap.get("by_path") or []) if r.get("yield") is not None]
    rows.sort(key=lambda r: r["yield"], reverse=True)
    out = []
    for r in rows[:limit]:
        p95 = ("%dms" % r["p95_ms"]) if r.get("p95_ms") else "—"
        out.append("%s·%s 爬取率 %.0f%% ｜ %.1f 行/次 ｜ p95 %s ｜ 风险 %.0f%%"
                   % (r["plat"], r["path"], r["yield"] * 100, r["eff"] or 0,
                      p95, (r["risk"] or 0) * 100))
    return out
