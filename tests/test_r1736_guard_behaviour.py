# -*- coding: utf-8 -*-
"""r1736：同程守卫的**行为**验证——喂火车票 dump，必须马上停并写明原因。

上一版的测试只查源码文字（"有没有这段代码"），这一版真跑一遍：
用 `tests/fixtures/tongcheng_train_page.xml`（线上自动留证的真实页面）
当设备 dump，看 `_on_flight_form` 是否
  1) 返回 False（不继续点城市/日期）；
  2) 记一条 timeout，detail 写明「偏离机票表单（页面: 火车票），本次提前结束」。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import AppTongchengCrawler as _TC  # noqa: E402
from crawlers.app_tongcheng_parse import is_form  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    warning = info
    debug = info


class _Dev:
    def __init__(self, xml):
        self._xml = xml

    def dump(self):
        return self._xml


def _crawler(xml):
    c = _TC({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(ROOT, "_scratch", "_u")
    c._last_dev = _Dev(xml)
    return c


def _train_xml():
    return io.open(TRAIN, encoding="utf-8", errors="replace").read()


def test_guard_stops_on_train_page():
    xml = _train_xml()
    assert is_form(xml) is False, "fixture 本身不该被当成机票表单"
    c = _crawler(xml)
    ok = c._on_flight_form(dev=c._last_dev, entry="app-city")
    assert ok is False, "停在火车票页时守卫没有拦住"
    notes = [p for p in c.paths if p.get("path") == "app-city"]
    assert notes, "守卫没有记账"
    detail = notes[-1].get("detail") or ""
    assert "偏离机票表单" in detail, detail
    assert "火车票" in detail, detail
    assert notes[-1].get("status") == "timeout", notes[-1]


def test_guard_allows_flight_form():
    """机票表单页要放行（用同一份 dump 的伪造版：加一个「机票查询」节点）。"""
    xml = _train_xml().replace("查询火车票", "机票查询")
    c = _crawler(xml)
    ok = c._on_flight_form(dev=c._last_dev, entry="app-city")
    assert ok is True, "机票表单被误拦"
    assert not [p for p in c.paths if p.get("path") == "app-city"], \
        "放行时不该记账"
