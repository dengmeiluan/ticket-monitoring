# -*- coding: utf-8 -*-
"""r1063 T69：渠道状态记忆（停服 / 登录墙）——浏览器与 App **共用一套**。

实测背景：`app_ctrip` 一次查询 **81 秒、0 条、login_suspect=True**（携程 App 要登录）。
不处理的话每轮白撞一堵墙；现在撞一次就记 2 小时，窗口内**零请求**让位，
状态记 `login`（健康页显示「需登录 + 去登录」），登完清记忆立刻恢复。

结构上，`BaseCrawler`（浏览器）与 `AppCrawler`（App）**互不继承**，所以记忆放在
`core/service_state.py`，两侧各自薄包装——一处实现、一个口径。
"""
import io
import logging
import os
import tempfile
import time

import pytest

from core import service_state as sst
from crawlers.app_ctrip import AppCtripCrawler


@pytest.fixture(autouse=True)
def _clean():
    yield
    sst.clear(tempfile.gettempdir(), "probe", "login_wall")


def test_mark_until_clear_roundtrip():
    root = tempfile.mkdtemp()
    assert sst.until(root, "x", "login_wall") == 0.0
    sst.mark(root, "x", "login_wall", "需登录", window_s=60)
    assert sst.until(root, "x", "login_wall") > time.time()
    assert "需登录" in sst.detail(root, "x", "login_wall")
    sst.clear(root, "x", "login_wall")
    assert sst.until(root, "x", "login_wall") == 0.0


def test_permanent_flag_is_recorded():
    root = tempfile.mkdtemp()
    sst.mark(root, "x", "service_closed", "永久停服", permanent=True)
    assert sst.is_permanent(root, "x", "service_closed") is True
    assert sst.until(root, "x", "service_closed") - time.time() > 3000 * 86400


def test_kinds_use_separate_files():
    root = tempfile.mkdtemp()
    sst.mark(root, "x", "login_wall", "a")
    assert sst.until(root, "x", "service_closed") == 0.0
    assert os.path.basename(sst.path_for(root, "x", "login_wall")) == \
        "login_wall.json"


def test_broken_file_is_treated_as_absent():
    root = tempfile.mkdtemp()
    p = sst.path_for(root, "x", "login_wall")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ 不是 json")
    assert sst.until(root, "x", "login_wall") == 0.0      # 不抛


def test_app_crawler_has_the_shared_memo():
    c = AppCtripCrawler({"user_data_dir": tempfile.mkdtemp(), "android": {}},
                        logging.getLogger("t69"))
    for name in ("service_closed_until", "mark_service_closed",
                 "service_closed_skip", "login_wall_until", "mark_login_wall",
                 "login_wall_skip", "clear_login_wall", "early_skip"):
        assert hasattr(c, name), name


def test_login_wall_makes_fetch_return_instantly():
    """没登录时不该每轮白跑 81 秒——窗口内必须 0 秒返回。"""
    c = AppCtripCrawler({"user_data_dir": tempfile.mkdtemp(), "android": {}},
                        logging.getLogger("t69"))
    c.mark_login_wall("页面停在登录墙")
    notes = []
    c.path_note = lambda *a, **kw: notes.append((a, kw))
    t0 = time.time()
    assert c.fetch("SHA", "PEK", ["2026-11-16"]) == []
    assert time.time() - t0 < 3, "登录墙窗口内不该再去跑（实测一次 81 秒）"
    assert notes and notes[0][0][1] == "login", (
        "状态必须是 login（健康页显示需登录），不是 paced/error", notes)


def test_login_wall_is_cross_instance_and_clearable():
    root = tempfile.mkdtemp()
    a = AppCtripCrawler({"user_data_dir": root, "android": {}},
                        logging.getLogger("t69"))
    a.mark_login_wall("x")
    b = AppCtripCrawler({"user_data_dir": root, "android": {}},
                        logging.getLogger("t69"))
    assert b.login_wall_until() > time.time(), "新实例必须记得"
    b.clear_login_wall()
    assert b.login_wall_until() == 0.0


def test_every_app_channel_calls_early_skip():
    """五家 App 渠道的 fetch 开头都要上闸（否则登录墙记忆对它们没用）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("app_ctrip.py", "app_fliggy.py", "app_qunar.py",
                 "app_tongcheng.py", "app_zhixing.py"):
        src = io.open(os.path.join(root, "crawlers", name),
                      encoding="utf-8").read()
        assert "self.early_skip(dates)" in src, name
