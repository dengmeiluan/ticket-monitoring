# -*- coding: utf-8 -*-
"""r1182：三率一险（爬取率 / 效率 / 速度 / 风险）必须**与基线报表同一口径**。

用户要的是"爬取率提升、效率提升、速度提升、风控降低"，那就必须能被数字验收；
而数字一旦有两套算法，页面上写的和 `python -m core.baseline` 跑出来的就会对不上，
从此没人敢信。本文件守住三件事：

1. `eff`（行/次）与 `baseline.by_path()` **逐格相等**（同一份 SQL）；
2. 分母用"全部尝试次数"，所以 `yield + risk == 1`（同口径闭环）；
3. 空样本的 p95 返回 `None`，**不许返回 0** 冒充"很快"（负控）。
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import baseline, rates  # noqa: E402


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
