# -*- coding: utf-8 -*-
"""r1063 T164：`python -m core.baseline` —— 可复跑的基线快照。

为什么：判断"改动到底有没有让爬取率变好"，必须**同一口径复测**。以前每次
都是我临时写 SQL（散在会话里，下次没人找得到）。现在一条命令产出
「今日出数 / 各通路效率 / 失败面构成 / 登录槽位 / 降级项 / 最近一轮计时」。

口径铁律：**只算真出数**（ok/calendar）；失败面单独列；对比看 **行/次**。
"""
import datetime
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import baseline as B  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = ("CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
          " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
          " depart_date TEXT, attempt_id TEXT, fetched_at TEXT, rows INTEGER,"
          " note TEXT)")


def _mkdb(tmp_path):
    db = str(tmp_path / "b.db")
    c = sqlite3.connect(db)
    c.execute(SCHEMA)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ("ctrip", "PC", "ok", 100),
        ("ctrip", "PC", "ok", 50),
        ("ctrip", "PC", "login", 0),
        ("ctrip", "日历", "empty", 0),
        ("fliggy", "PC", "ok", 30),
    ]
    for plat, path, st, r in rows:
        c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
                  " fetched_at, rows) VALUES (?,?,?,?,?)",
                  (plat, path, st, now, r))
    c.commit()
    c.close()
    return db


def test_render_has_all_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_base", lambda port=0: "")      # 不依赖实例
    txt = B.render(hours=12, db=_mkdb(tmp_path))
    for h in ("## 一、", "## 二、", "## 三、", "## 复测方法"):
        assert h in txt, "缺章节：%s" % h


def test_only_real_rows_count(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_base", lambda port=0: "")
    txt = B.render(hours=12, db=_mkdb(tmp_path))
    assert "| ctrip | 2 | 150 | 75.0 |" in txt, txt[:600]
    # 登录/空结果不许算进产出
    assert "| ctrip | 4 | 150 |" not in txt


def test_failure_section_lists_login_and_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_base", lambda port=0: "")
    txt = B.render(hours=12, db=_mkdb(tmp_path))
    assert "| ctrip | PC | login | 1 |" in txt
    assert "| ctrip | 日历 | empty | 1 |" in txt


def test_missing_db_is_reported_not_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_base", lambda port=0: "")
    txt = B.render(hours=12, db=str(tmp_path / "nope.db"))
    assert "读不到数据库" in txt


def test_render_mentions_metric_guidance():
    """必须写明"对比看行/次"，否则下一个人只会比总行数。"""
    txt = B.render(hours=1, db="nope.db")
    assert "行/次" in txt


def test_section_two_shows_composition(tmp_path, monkeypatch):
    """效率必须和『分工』一起给：行/次只在分工相同时可比。

    本日教训：`PC·国际` 上线后先吃掉国际日期，`H5/API` 只剩缺口日期，
    行/次从 59.3 掉到 49.2 —— 看着像变差，其实是分母变了。
    """
    monkeypatch.setattr(B, "_base", lambda port=0: "")
    txt = B.render(hours=12, db=_mkdb(tmp_path))
    assert "独立日期数" in txt, "缺分工列，读表的人会被分母骗"
    assert "只在『分工相同』时可比" in txt
