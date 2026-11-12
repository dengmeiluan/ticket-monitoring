# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_baseline.py
- tests/test_r1063_parse_scene.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime
import io
import logging
import os
import pytest
import sqlite3
import sys
import tempfile

from core import baseline as B
from crawlers.base import BaseCrawler
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1063_baseline.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r1063_parse_scene.py ----

class _Probe(BaseCrawler):
    name = "probe_scene"

    def fetch(self, *a, **kw):      # pragma: no cover
        return []


def _crawler(root):
    return _Probe({"user_data_dir": root}, logging.getLogger("t66"))


def test_scene_is_saved_and_signature_shows_structure():
    root = tempfile.mkdtemp()
    c = _crawler(root)
    body = ("<html>" + '<div class="flight-item"><span class="b1">KN5956</span>'
            "</div>" * 5 + "</html>")
    scene = c.save_parse_scene([body], tag="intl", anchors=("flight-item",))
    assert scene["bytes"] > 0 and scene["nodes"] >= 5
    assert os.path.exists(scene["path"]), scene
    sig = c.scene_sig(scene)
    assert "节点" in sig and "锚点未命中 无" in sig, sig


def test_signature_names_the_missing_anchors_when_layout_changed():
    """改版时最有用的一句话：**哪个锚点不在了**。"""
    root = tempfile.mkdtemp()
    c = _crawler(root)
    body = "<html><div class='v2-card'>新结构</div></html>"
    scene = c.save_parse_scene([body], tag="intl", anchors=("flight-item", "b1"))
    sig = c.scene_sig(scene)
    assert "flight-item" in sig and "b1" in sig, sig


def test_scene_is_honest_when_there_is_no_body():
    c = _crawler(tempfile.mkdtemp())
    scene = c.save_parse_scene([], tag="x")
    assert scene["bytes"] == 0 and "没有响应体" in scene["why"]
    assert "无现场" in c.scene_sig(scene)


def test_only_recent_scenes_are_kept():
    root = tempfile.mkdtemp()
    c = _crawler(root)
    c.PARSE_SCENE_KEEP = 3
    for i in range(6):
        c.save_parse_scene(["<html>" + str(i) + "</html>"], tag="t%d" % i)
    d = os.path.join(root, "probe_scene", "parse_fail")
    assert len([n for n in os.listdir(d) if n.endswith(".html")]) <= 3


def test_scene_never_raises_on_bad_input():
    c = _crawler(tempfile.mkdtemp())
    assert isinstance(c.save_parse_scene([object()], tag="x"), dict)


def test_intl_and_domestic_backoff_windows_are_independent():
    """国内线以前**没有**退避窗口 → 每轮烧满 300s 预算。"""
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK = 0
    QunarCrawler._WAIT_BACKOFF_UNTIL_DOM = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK_DOM = 0
    c = QunarCrawler({}, logging.getLogger("t66"))
    assert c._open_wait_backoff("intl") > 0
    assert QunarCrawler._WAIT_BACKOFF_STREAK_DOM == 0, "开国际窗口不该动国内计数"
    assert c._open_wait_backoff("dom") > 0
    assert QunarCrawler._WAIT_BACKOFF_STREAK == 1
    assert QunarCrawler._WAIT_BACKOFF_STREAK_DOM == 1
    c._reset_wait_backoff()
    assert (QunarCrawler._WAIT_BACKOFF_UNTIL,
            QunarCrawler._WAIT_BACKOFF_UNTIL_DOM) == (0.0, 0.0)


def test_honor_check_covers_both_lines():
    src = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "qunar.py"), encoding="utf-8").read()
    assert "_WAIT_BACKOFF_UNTIL_DOM" in src
    # 老写法（只认国际）不许回来
    assert "if _is_intl and _bo_left > 0:" not in src
