# -*- coding: utf-8 -*-
"""r1063 T268：把"远日期更差"变成**系统自己说**的建议。

今天两次是人工跑分桶才发现：`tuniu` ≤30 天 98% vs 61–90 天 49%，
`app_zhixing` 30% vs 10%，而浏览器三家与距离无关。
这种结构性差异应该由产品自己说出来（一切可建议），不该等人半夜查 SQL。

判定要严格，避免噪音：近端样本够 + 近端确实能成（≥60%）+ 远端比近端低 ≥25pp。
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.advise import distance_advice  # noqa: E402


def _db(tmp_path, rows, name="x.db"):
    """rows: [(plat, depart_date, path_status, n)]"""
    p = os.path.join(str(tmp_path), name)
    c = sqlite3.connect(p)
    c.execute("""create table fetch_paths(
        platform text, depart_date text, path_status text, fetched_at text)""")
    for plat, dd, st, n in rows:
        for _ in range(n):
            c.execute("insert into fetch_paths values(?,?,?,datetime('now'))",
                      (plat, dd, st))
    c.commit()
    c.close()
    return p


def _d(offset, today=None):
    import datetime as dt
    return ((today or dt.date.today()) + dt.timedelta(days=offset)).isoformat()


def test_flags_near_good_far_bad(tmp_path):
    db = _db(tmp_path, [
        ("tuniu", _d(7), "ok", 10),
        ("tuniu", _d(80), "timeout", 10),
    ])
    got = distance_advice(24, db=db)
    assert len(got) == 1 and got[0]["plat"] == "tuniu", got
    assert got[0]["near_pct"] == 100 and got[0]["far_pct"] == 0
    assert "交浏览器" in got[0]["text"]


def test_ignores_platform_bad_on_both_ends(tmp_path):
    """近端也不行（<60%）→ 不是"远日期"问题，不许建议收窄。"""
    db = _db(tmp_path, [
        ("app_ctrip", _d(7), "timeout", 10),
        ("app_ctrip", _d(80), "timeout", 10),
    ])
    assert distance_advice(24, db=db) == []


def test_ignores_small_gap_and_small_samples(tmp_path):
    # 差距只有 10pp（近端 100% vs 远端 90%）
    db = _db(tmp_path, [("fliggy", _d(7), "ok", 20),
                        ("fliggy", _d(80), "ok", 18),
                        ("fliggy", _d(80), "timeout", 2)])
    assert distance_advice(24, db=db) == []
    # 远端样本不足
    db2 = _db(tmp_path, [("ctrip", _d(7), "ok", 20),
                         ("ctrip", _d(80), "timeout", 2)], name="x2.db")
    assert distance_advice(24, db=db2) == []


def test_panel_surfaces_it(tmp_path):
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'data["distance_advice"]' in w
    assert 'const _d=(j&&j.distance_advice)||[]' in w, \
        "前端要把距离建议拼进「建议」行（不加行，窄档才稳）"
