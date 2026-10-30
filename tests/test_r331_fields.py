# -*- coding: utf-8 -*-
"""r331 数据层：qunar H5 中转+经停复合行 stopsCitys 防回归钉。

约束语义：换源门（``if not trans and _stopflight``）只管 transInfo
补缺——stopsCitys 的读取在其上游无条件执行，中转行（trans 真值）
照落 ``stopCitys`` 键，经 normalize 产 stopCity/stopover。若重构把
读取收进换源门，中转+经停复合行将 stopover=True 而 stopCity 空，
渲染裸「经停」徽标，违背 flightnorm 行律「经停徽标须带地点」。
fixture 按 dump 实证形态构造（9C7372/HO1108，乌→沪 2026-10-05：
binfo1.stopsCitys=',陇南'、extparams.stopFlight=true、transCity=兰州）。"""
import json

from crawlers.qunar import QunarCrawler


def _resp():
    b1 = {"depTime": "15:00", "arrTime": "00:25",
          "depDate": "2026-10-06", "arrDate": "2026-10-08",
          "totalDuration": "33h25m", "transCity": "兰州",
          "stopsCitys": ",陇南", "stop": True}
    f = {"code": "9C7372/HO1108", "transCity": "兰州", "minPrice": 2502,
         "binfo1": b1,
         "binfo2": dict(b1),
         "extparams": json.dumps({"stopFlight": True, "lowPrice": 2502})}
    return json.dumps({"data": {"flights": [f]}})


def test_qunar_transfer_row_stops_city_lands():
    rows = QunarCrawler._parse_response_flights(_resp())
    assert len(rows) == 1
    r = rows[0]
    assert r.get("stopCitys") == "陇南"
    assert r.get("stopFlight") is True


def test_qunar_transfer_row_stop_city_normalizes():
    from core.flightnorm import normalize
    rows = QunarCrawler._parse_response_flights(_resp())
    f = normalize(rows[0], "2026-10-06")
    assert f.get("stopCity") == "陇南"
    assert f.get("stopover") is True
