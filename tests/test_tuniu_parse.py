# -*- coding: utf-8 -*-
"""途牛解析回归测试。

原 bug（2026-10-06 实报取证）：fare 层舱位键从顶层 priceJourneyCabinList
再度改版嵌套进 flightPriceList[].priceJourneyCabinList[].priceFlightCabinList[]
.cabinTypeName——顶层读取 0/11479 行全空，舱位字段死了正是因此无人报警。

fixture 内联自 debug/tuniu_raw_2026-10-06.json 真实报文最小片段
（debug/ 不入库，测试必须在无该文件的干净环境可跑）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_tuniu_parse.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402


# 10-06 真实形态：舱位嵌套在 flightPriceList 下（顶层键已消失）
_FARE_10_06 = {
    "flightOptions": [{"flightNos": "MU8370"}],
    "flightPriceList": [
        {
            # ADT baseFare 3600（另两档 CHD/INF 由 psgType 过滤排除）
            "fareBreakdownList": [
                {"baseFare": 3600, "discount": "7.7折", "psgType": "ADT"},
                {"baseFare": 2370, "discount": "0", "psgType": "CHD"},
                {"baseFare": 470, "discount": "0", "psgType": "INF"},
            ],
            "priceJourneyCabinList": [
                {"priceFlightCabinList": [
                    {"cabinClass": "Y", "cabinCode": "M",
                     "cabinTypeName": "经济舱"},
                ]},
            ],
        },
    ],
}

# 09-18 旧形态：舱位挂 fare 顶层（兼容回退必须仍可解）
_FARE_LEGACY = {
    "flightOptions": [{"flightNos": "MU8370"}],
    "flightPriceList": [
        {"fareBreakdownList": [{"baseFare": 3600, "psgType": "ADT"}]},
    ],
    "priceJourneyCabinList": [
        {"priceFlightCabinList": [
            {"cabinTypeName": "经济舱"},
        ]},
    ],
}

# flightList 键为「航班号#日期#起点#终点」复合键（真实形态）
_FLIGHT_LIST = {
    "MU8370#2026-10-06#URC#SHA": {
        "airlineCompany": "东航",
        "departureTime": "20:20", "arrivalTime": "01:15",
        "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
        "flightTime": "295",
    },
}


def test_fare_cabin_new_nested_layout():
    # 10-06 改版后嵌套层（顶层无键）：修复前此处恒空（0/11479 实锤）
    assert TuniuCrawler._fare_cabin(_FARE_10_06) == "经济舱"


def test_fare_cabin_legacy_top_level_fallback():
    # 09-18 旧顶层形态兼容回退
    assert TuniuCrawler._fare_cabin(_FARE_LEGACY) == "经济舱"


def test_fare_cabin_missing_returns_empty():
    # 两层都无舱位：宁缺勿错返回空
    assert TuniuCrawler._fare_cabin({"flightOptions": []}) == ""
    assert TuniuCrawler._fare_cabin({}) == ""


def test_parse_offers_cabin_end_to_end():
    # 端到端：detail.cabinTypeName 不在场 → cabin 必须来自 fare 嵌套层
    raw = {"data": {"fareList": [_FARE_10_06], "flightList": _FLIGHT_LIST}}
    offers = TuniuCrawler._parse_offers(raw)
    assert len(offers) == 1
    o = offers[0]
    assert o["flight_no"] == "MU8370"
    assert o["price"] == 3600
    assert o["cabin"] == "经济舱"


def test_to_price_upper_bound():
    # 上限 50000 与 qunar/fliggy 价格带对齐：越界弃（脏数据/键义漂移）
    assert TuniuCrawler._to_price(60000) is None
    assert TuniuCrawler._to_price(50000) == 50000
    assert TuniuCrawler._to_price(300) == 300
    assert TuniuCrawler._to_price(0) is None
    assert TuniuCrawler._to_price(-5) is None
    assert TuniuCrawler._to_price("abc") is None
