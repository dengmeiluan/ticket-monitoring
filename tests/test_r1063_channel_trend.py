# -*- coding: utf-8 -*-
"""r1063 T133：`--trend` —— 把"爬取率"变成一条曲线。

意义：这几十轮改了浏览器通路、订阅、熔断、清墙……"到底变好没有"以前只能靠
临时 SQL 回答。现在 `python -m core.channel_matrix --trend --hours 6` 就是尺子。

统计口径：只算**真出数**（`ok` / `calendar`），按小时 × 渠道汇总。
"""
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_matrix as CM  # noqa: E402

SCHEMA = ("CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
          " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
          " depart_date TEXT, attempt_id TEXT, fetched_at TEXT, rows INTEGER,"
          " note TEXT)")


def _mkdb(tmp_path):
    db = str(tmp_path / "p.db")
    c = sqlite3.connect(db)
    c.execute(SCHEMA)
    import datetime
    now = datetime.datetime.now()
    rows = [
        ("fliggy", "PC", "ok", 10, (now - datetime.timedelta(minutes=5))),
        ("fliggy", "PC", "ok", 20, (now - datetime.timedelta(minutes=65))),
        ("tongcheng", "PC", "ok", 5, (now - datetime.timedelta(minutes=10))),
        ("ctrip", "PC", "login", 0, (now - datetime.timedelta(minutes=3))),
        ("app_fliggy", "app-login", "login", 0, (now - datetime.timedelta(minutes=1))),
    ]
    for plat, path, st, r, ts in rows:
        c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
                  " fetched_at, rows) VALUES (?,?,?,?,?)",
                  (plat, path, st, ts.strftime("%Y-%m-%d %H:%M:%S"), r))
    c.commit()
    c.close()
    return db


def test_trend_sums_only_real_rows(tmp_path):
    db = _mkdb(tmp_path)
    rep = CM.trend(6, db=db)
    assert rep["ok"], rep
    totals = {p: sum(rep["grid"][p].values()) for p in rep["plats"]}
    assert totals["fliggy"] == 30, totals
    assert totals["tongcheng"] == 5
    # 登录失败不算出数
    assert totals.get("ctrip", 0) == 0
    assert totals.get("app_fliggy", 0) == 0


def test_trend_text_has_header_and_totals(tmp_path):
    rep = CM.trend(6, db=_mkdb(tmp_path))
    txt = CM._trend_text(rep)
    assert "每小时出数" in txt
    assert "合计" in txt
    assert "fliggy" in txt


def test_trend_missing_db_is_reported():
    rep = CM.trend(6, db="no/such/file.db")
    assert rep["ok"] is False
    assert "读不到" in rep["why"]


def test_cli_supports_trend_flags():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "channel_matrix.py"),
        encoding="utf-8").read()
    assert "--trend" in src and "--hours" in src
    assert "def trend(" in src and "def _trend_text(" in src
