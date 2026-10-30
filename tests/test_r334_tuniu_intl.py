# -*- coding: utf-8 -*-
"""r334 案②：tuniu intl 机场码→城市码归并缺失。

活体取证（r334_probe_pvg*.py）：PVG-CDG 与 SHA-CDG 探针多拍终态恒空
（needQueryMore=1 productList=0×6 拍），SHA-BKK 单拍出数 9 行——
tuniu dCityCode/aCityCode 只认城市码。校准台账 R4x 早有
「acity=NRT 机场码直传=全窗 380 行零报价实锤；归并后真 profile
直验 SHA→NRT 落地」，fliggy/ctrip/tongcheng 三渠道均已接
core.intl.airport_city_code 归并（fliggy:341/ctrip:196/
tongcheng:151），唯 tuniu _fetch_intl 漏接——生产配置纯机场码航线
（PVG-CDG/LAX/DXB/SFO、SHA-NRT/LHR/JFK/YYZ 共 8 条）配线即死，
tuniu 全史零行（DB DISTINCT 证实），12/16 航线占比下 qsup/zdom
双哨门槛内静默。

修法：_fetch_intl 入口 fc/tc 过 airport_city_code（三渠道同款形态）；
落库 from_city/to_city 保持配置原码（展示面/出链零变化）；tz 印章
随归并后城市对（INTL_TZ 城市码覆盖更全，归并前后同区值零变化）。
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402

_L = logging.getLogger("probe")


def _capture_hoop(monkeypatch, raw=None):
    captured = []

    def _fake(self, fc, tc, date):
        captured.append((fc, tc, date))
        return {} if raw is None else raw

    monkeypatch.setattr(TuniuCrawler, "_hoop_intl", _fake)
    return captured


def _stub_parse(monkeypatch):
    monkeypatch.setattr(TuniuCrawler, "_parse_offers_intl",
                        lambda self, data: [{"price": 1000.0}])
    monkeypatch.setattr(TuniuCrawler, "_sleep", lambda self: None)


def test_tuniu_intl_merges_airport_to_city_code(monkeypatch):
    """纯机场码航线（PVG-CDG 实录）请求链归并为城市码（SHA-PAR）。"""
    captured = _capture_hoop(monkeypatch)
    _stub_parse(monkeypatch)
    c = TuniuCrawler({}, _L)
    out = c._fetch_intl("PVG", "CDG", ["2026-11-16"])
    assert captured == [("SHA", "PAR", "2026-11-16")], captured
    # 落库保持配置原码（展示面/出链零变化）
    assert len(out) == 1
    assert out[0].from_city == "PVG"
    assert out[0].to_city == "CDG"


def test_tuniu_intl_city_code_passthrough(monkeypatch):
    """城市码/同名码航线零变形（SHA-BKK 恒等回退）——在产航线零回归
    面。"""
    captured = _capture_hoop(monkeypatch)
    _stub_parse(monkeypatch)
    c = TuniuCrawler({}, _L)
    c._fetch_intl("SHA", "BKK", ["2026-11-16"])
    assert captured == [("SHA", "BKK", "2026-11-16")], captured
