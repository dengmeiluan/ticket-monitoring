# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1182_rates.py
- tests/test_r1822_rates_denominator.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sqlite3
import sys

from core import baseline, rates


# ---- merged from tests/test_r1182_rates.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _mkdb(tmp_path, rows, name="t.db"):
    """建一个最小 fetch_paths（含 elapsed_ms），行格式：(plat,path,status,rows,ms,date)。"""
    db = str(tmp_path / name)
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.execute("create table fetch_paths (id integer primary key, fetched_at text,"
                " platform text, entry_path text, from_city text, to_city text,"
                " depart_date text, path_status text, rows integer, elapsed_ms integer)")
    for plat, path, st, r, ms, d in rows:
        con.execute("insert into fetch_paths (fetched_at, platform, entry_path,"
                    " from_city, to_city, depart_date, path_status, rows, elapsed_ms)"
                    " values (datetime('now','localtime'),?,?,'SHA','PEK',?,?,?,?)",
                    (plat, path, d, st, r, ms))
    con.commit()
    con.close()
    return db


ROWS = [
    # ctrip·PC：4 次成功，共 400 行，耗时 1000/2000/3000/4000ms
    ("ctrip", "PC", "ok", 100, 1000, "2026-11-16"),
    ("ctrip", "PC", "ok", 100, 2000, "2026-11-17"),
    ("ctrip", "PC", "ok", 100, 3000, "2026-11-18"),
    ("ctrip", "PC", "ok", 100, 4000, "2026-11-19"),
    # 同一通路 1 次失败（登录墙）
    ("ctrip", "PC", "login", 0, 0, "2026-11-20"),
    # fliggy·H5：1 次成功 50 行，1 次失败
    ("fliggy", "H5", "ok", 50, 5000, "2026-11-16"),
    ("fliggy", "H5", "challenge", 0, 0, "2026-11-17"),
]


def test_matches_baseline_by_path(tmp_path):
    """同一份库：rates 的 eff/rows 必须与 baseline.by_path 逐格相等。"""
    db = _mkdb(tmp_path, ROWS)
    snap = rates.snapshot(hours=24, db=db)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    base = {(r["plat"], r["path"]): r for r in baseline.by_path(con, hours=24)}
    con.close()
    assert snap["ok"] is True, snap
    for it in snap["by_path"]:
        b = base[(it["plat"], it["path"])]
        assert it["rows"] == b["rows"], it
        assert it["ok_n"] == b["n"], it
        assert abs((it["eff"] or 0) - b["eff"]) < 1e-9, (it, b)


def test_yield_and_risk_are_complementary(tmp_path):
    """分母是全部尝试 → 爬取率（成功占比）+ 风险 = 100%。"""
    db = _mkdb(tmp_path, ROWS)
    snap = rates.snapshot(hours=24, db=db)
    ctrip = [r for r in snap["by_path"] if r["plat"] == "ctrip"][0]
    assert ctrip["attempts"] == 5, ctrip
    assert abs(ctrip["yield"] - 4 / 5.0) < 1e-9, ctrip
    assert abs(ctrip["risk"] - 1 / 5.0) < 1e-9, ctrip
    assert abs(ctrip["yield"] + ctrip["risk"] - 1.0) < 1e-9, ctrip
    # 强度指标单独一列：每次尝试平均拿几行（可以 >1，不与风险互补）
    assert abs(ctrip["rows_per_attempt"] - 400 / 5.0) < 1e-9, ctrip


def test_p95_is_real_and_none_when_empty(tmp_path):
    db = _mkdb(tmp_path, ROWS)
    snap = rates.snapshot(hours=24, db=db)
    ctrip = [r for r in snap["by_path"] if r["plat"] == "ctrip"][0]
    assert ctrip["p95_ms"] == 4000, ctrip          # 4 个样本的最近秩 p95 = 最大值
    # 负控：没有耗时样本时必须是 None，不能是 0（0 会被读成"瞬间完成"）
    db2 = _mkdb(tmp_path, [("tuniu", "H5", "ok", 5, 0, "2026-11-16")])
    snap2 = rates.snapshot(hours=24, db=db2)
    tuniu = [r for r in snap2["by_path"] if r["plat"] == "tuniu"][0]
    assert tuniu["p95_ms"] is None, tuniu


def test_plat_aggregate_is_sum_then_divide(tmp_path):
    """渠道汇总必须"先求和再相除"，不是把各通路的比值平均。"""
    db = _mkdb(tmp_path, ROWS)
    snap = rates.snapshot(hours=24, db=db)
    t = snap["totals"]
    assert t["attempts"] == 7 and t["ok_n"] == 5 and t["rows"] == 450, t
    assert abs(t["yield"] - 5 / 7.0) < 1e-9, t
    assert abs(t["rows_per_attempt"] - 450 / 7.0) < 1e-9, t
    assert abs(t["eff"] - 450 / 5.0) < 1e-9, t


def test_lines_are_speakable():
    """给人看的一行必须带单位与口径（爬取率/行次/p95/风险）。"""
    db_snap = {"by_path": [{"plat": "ctrip", "path": "PC", "yield": 0.8, "eff": 105.7,
                            "p95_ms": 4200, "risk": 0.2}]}
    line = rates.to_lines(db_snap)[0]
    assert "爬取率 80%" in line and "行/次" in line and "p95 4200ms" in line


def test_kinds_document_the_definitions():
    for k in ("yield", "eff", "p95_ms", "risk"):
        assert k in rates.KINDS and rates.KINDS[k].strip()


# ---- merged from tests/test_r1822_rates_denominator.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_rates_skip_statuses_defined():
    assert rates.SKIP_STATUSES == ("unsupported", "paced", "skipped")


def test_snapshot_excludes_skips_from_denominator():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "rates.py"),
        encoding="utf-8").read()
    i = src.index("def snapshot(")
    seg = src[i:i + 3000]
    assert "path_status in (%s)" in seg, "没有把跳过状态单列统计"
    assert "max(0, _rec - _sk)" in seg, "分母没有扣除跳过"
    assert '"skipped_n"' in seg, "没有把剔掉多少条报出来"


def test_storage_counts_paced_separately():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "storage.py"),
        encoding="utf-8").read()
    i = src.index("def bump(node, status, last)")
    seg = src[i:i + 3000]
    assert 'elif status in ("paced", "skipped")' in seg, "paced 没有单列分支"
    assert 'node["paced"]' in seg, "没有 paced 计数"
    # error 分支必须还在（真故障仍要记）
    assert 'node["error"] += 1' in seg
