# -*- coding: utf-8 -*-
"""r1063 T136：`channel_matrix --dates` —— 按"渠道 × 出发日期"看出数缺口。

背景（本轮实测）：想做"远日期覆盖"，结果发现飞猪/携程/同程**远日期本来就有数**
（飞猪 2027-01-29 有 946 行），唯一 0 行的是**途牛远日期**——而它是登录问题，
不是策略问题。结论：这类判断必须有"按日期看"的视角，以前只能靠临时 SQL。

真机输出：
```
渠道          11-16   01-29   01-30   02-14
ctrip           921      41      35      39
fliggy         4306     946     813     899
tongcheng        55     100     100      18
tuniu          1050       0       0       0     ← 缺口一眼可见
```
"""
import datetime
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_matrix as CM  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = ("CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
          " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
          " depart_date TEXT, attempt_id TEXT, fetched_at TEXT, rows INTEGER,"
          " note TEXT)")


def _mkdb(tmp_path):
    db = str(tmp_path / "d.db")
    c = sqlite3.connect(db)
    c.execute(SCHEMA)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ("fliggy", "PC", "ok", "2026-11-16", 100),
        ("fliggy", "PC", "ok", "2027-01-29", 50),
        ("tuniu", "H5/API", "login", "2027-01-29", 0),
        ("tuniu", "PC", "unsupported", "2027-01-29", 0),
        ("tuniu", "H5/API", "ok", "2026-11-16", 30),
    ]
    for plat, path, st, d, r in rows:
        c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
                  " depart_date, fetched_at, rows) VALUES (?,?,?,?,?,?)",
                  (plat, path, st, d, now, r))
    c.commit()
    c.close()
    return db


def test_date_grid_counts_only_real_rows(tmp_path):
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    assert rep["ok"], rep
    assert rep["grid"]["fliggy"]["2027-01-29"] == 50
    assert rep["grid"]["tuniu"]["2027-01-29"] == 0, "登录/不支持不算出数"
    assert rep["tries"]["tuniu"]["2027-01-29"] == 2, "但要记尝试次数"


def test_text_shows_zero_vs_dash(tmp_path):
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    txt = CM._dates_text(rep)
    assert "0 = 该日期没拿到任何价" in txt
    # 途牛远日期有尝试但 0 行 → 显示 0；没尝试的日期显示 -
    line = next(l for l in txt.splitlines() if l.startswith("tuniu"))
    assert " 0" in line


def test_missing_db_reported():
    rep = CM.date_coverage(12, db="nope.db")
    assert rep["ok"] is False and "读不到" in rep["why"]


def test_cli_has_dates_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--dates" in src
    assert "def date_coverage(" in src and "def _dates_text(" in src


def test_path_kind_classification():
    assert CM.path_kind("PC·周历") == "calendar"
    assert CM.path_kind("窗历") == "calendar"
    assert CM.path_kind("PC·国际") == "list"
    assert CM.path_kind("PC") == "list"
    assert CM.path_kind("H5/API") == "list"
    assert CM.path_kind("QUERY") == "api"
    assert CM.path_kind("app-login") == "other"


def test_calendar_only_cell_is_starred(tmp_path):
    db = _mkdb(tmp_path)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
              " depart_date, fetched_at, rows) VALUES"
              " ('tongcheng','窗历','calendar','2026-11-16',datetime('now'),47)")
    c.commit()
    c.close()
    rep = CM.date_coverage(12, db=db)
    txt = CM._dates_text(rep)
    assert "47*" in txt, txt
    assert "票面价" in txt, "必须解释 * 的含义（票面口径未拆税）"


def test_list_rows_are_not_starred(tmp_path):
    """列表/接口出数不该带 *（口径是含税价）。"""
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    txt = CM._dates_text(rep)
    assert "50*" not in txt, txt
