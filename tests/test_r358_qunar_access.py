# -*- coding: utf-8 -*-
"""r358 去哪儿网页版停服后的接入钉。

2026-10-10 起 flight.qunar.com/site/ 只保留停服通知与 App 下载入口：
- 取数：m.flight H5 列表在登录态下仍出全量明细，H5 浏览器必须排在
  PC 复活探测之前（PC 已断供，先试只会白等）；
- 登录：PC 登录入口随站点停服，统一登录页 user.qunar.com 仍可手机号/
  扫码登录，Cookie 落 .qunar.com 与 H5 共用；
- 用户面：健康页给出「PC 停服 → H5 取数 → 登录门」的来源接入路径，
  登录卡说明 App 专属价与自动下单不在采集范围。
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


def test_qunar_login_is_unified_page_not_retired_pc():
    lg = logging.getLogger("t358lg")
    assert QunarCrawler.LOGIN_URL == (
        "https://user.qunar.com/passport/login.jsp")
    assert QunarCrawler({}, lg).login_url() == QunarCrawler.LOGIN_URL
    assert "flight.qunar.com/site" not in QunarCrawler.LOGIN_URL


def test_qunar_h5_home_and_data_url_are_live_h5():
    assert QunarCrawler.H5_HOME == "https://touch.qunar.com/h5/flight/"
    assert "m.flight.qunar.com/ncs/page/flightlist" in QunarCrawler.URL_TPL
    assert "flight.qunar.com/site" not in QunarCrawler.URL_TPL


def test_qunar_fetch_order_h5_before_pc_revival_probe():
    src = inspect.getsource(QunarCrawler._fetch_one)
    i_h5 = src.find("_fetch_via_browser")
    i_pc = src.find("_fetch_via_pc")
    i_http = src.find("_fetch_via_httpx")
    assert 0 <= i_h5 < i_pc < i_http, src


def test_qunar_skips_retired_pc_probe_by_default(monkeypatch):
    """H5 未命中时不得默认去等 PC 复活（3 采样 × 等待≈72s/日期）；
    PC 探测保留为显式开关，供人工一次性复核。"""
    q = QunarCrawler({}, logging.getLogger("t358pc"))
    assert QunarCrawler.PC_PROBE_ON_MISS is False
    calls = []
    monkeypatch.setattr(q, "_fetch_via_browser", lambda *a: None)
    monkeypatch.setattr(q, "_fetch_via_pc",
                        lambda *a: calls.append("pc"))
    monkeypatch.setattr(q, "_fetch_via_httpx", lambda *a: None)
    assert q._fetch_one("SHA", "HAK", "2027-01-29") is None
    assert calls == []


def test_webui_source_access_board_and_login_note():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    for needle in (
        "来源接入",
        "SOURCE ACCESS",
        "网页版已于 2026-10-10 停服",
        "登录后可用",
        "App 专属价与自动下单不在采集范围",
        "scQState",
        "srcAccessState",
        "qunar:'必须'",
        "携程、去哪儿必须登录",
        "携程/去哪儿需本机已建立登录态",
        "channelAuthView(p)",
    ):
        assert needle in src, needle
    assert "flight.qunar.com/site/oneway_list.htm" not in src
