# -*- coding: utf-8 -*-
"""r1063 T66：解析失败**留现场** + 退避窗口按国际/国内分两套。

今天的真实数据（`data/prices.db`，2026-11-08）：
```
qunar  H5  error  7 次  全是「国际列表有响应但未解析出价格」
qunar  QUERY paced 7 次  「本轮等待预算用尽（已 268s），主动让位」
```
第一条＝**有响应、解析对不上**（改版症状），但现场一点没留；
第二条＝国内线没有退避窗口，每轮把 300s 预算烧满还拿不到数。

今天各渠道成功率（账本）：app_zhixing 89.4% · fliggy 100% · tongcheng 100% ·
tuniu 66.5%（PC 全 unsupported）· **qunar 6.5%**。
"""
import io
import logging
import os
import tempfile

import pytest

from crawlers.base import BaseCrawler
from crawlers.qunar import QunarCrawler


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
