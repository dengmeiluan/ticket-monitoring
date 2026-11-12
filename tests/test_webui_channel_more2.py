# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_channel_trend.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sqlite3
import sys

from core import channel_matrix as CM


# ---- merged from tests/test_r1063_channel_trend.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
