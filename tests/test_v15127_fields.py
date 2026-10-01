# -*- coding: utf-8 -*-
"""tuniu depTerminal（出发航站楼）：detail 层 dTerminal 有值才落。

渠道对 dTerminal 间歇下发：部分代际 43/43 全有值（T1/T2），部分
代际恒空串——「有值才落键」家族律下零成本（恒空代际自然零出勤）。
与 arrTerminal 同门同守。五渠道 depTerminal/arrTerminal 现均为
无值不落键（恒空键卫生律），本文件钉 tuniu 侧 offer/行层双守卫。

三端协议：爬虫落键（本文件）↔ webui 渲染门消费（stl 段航站楼
合并段既有 depTerminal 消费点，零前端改动）↔ _propagate_fields 补全
链白名单（源行过 cabin_clean 同律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15127_fields.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402
from core.alerter import Alerter  # noqa: E402

_CT = TuniuCrawler

_FLIGHT_BASE = {
    "airlineCompany": "东航",
    "departureTime": "20:20", "arrivalTime": "01:15",
    "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
    "flightTime": "295",
}


def _policy(cabin, code, price, discount="6.7折"):
    return {"supportBlack": False,
            "fareBreakdownList": [
                {"baseFare": price, "discount": discount, "psgType": "ADT"}],
            "priceJourneyCabinList": [{"priceFlightCabinList": [
                {"cabinTypeName": cabin, "cabinCode": code}]}]}


def _raw(detail_extra):
    fl = {"MU8370#2026-10-06#URC#SHA": {**_FLIGHT_BASE, **detail_extra}}
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": [_policy("经济舱", "Y", 1500)]}
    return {"data": {"fareList": [fare], "flightList": fl}}


def _offer(detail_extra):
    offers = _CT._parse_offers(_raw(detail_extra))
    assert len(offers) == 1
    return offers[0]


def test_offer_dep_terminal_when_present():
    # 09-25 dump 实证形态：dTerminal 有值（T1/T2）→ 随 aTerminal 同门落键
    o = _offer({"aTerminal": "T2", "dTerminal": "T3"})
    assert o["arrTerminal"] == "T2"
    assert o["depTerminal"] == "T3"


def test_offer_dep_terminal_empty_string_not_landed():
    # 10-04~07 恒空串形态：有值才落键（空串键=恒空键 DB 卫生律）
    o = _offer({"aTerminal": "T2", "dTerminal": ""})
    assert o["arrTerminal"] == "T2"
    assert "depTerminal" not in o


def test_offer_dep_terminal_absent_key_not_landed():
    # 键缺席（部分代际不下发）：不落键不炸
    o = _offer({"aTerminal": "T2"})
    assert "depTerminal" not in o


def test_row_dep_terminal_passthrough():
    # 行层透传：offer 带 depTerminal → 行带 depTerminal（与 arrTerminal 对称）
    o = _offer({"aTerminal": "T2", "dTerminal": "T3"})
    rows = _CT._offers_to_flights([o])
    assert len(rows) == 1
    assert rows[0]["depTerminal"] == "T3"
    assert rows[0]["arrTerminal"] == "T2"


def test_row_dep_terminal_empty_not_landed():
    # 行层守卫：offer 无 depTerminal → 行不落键（恒空键不落）
    o = _offer({"aTerminal": "T2", "dTerminal": ""})
    rows = _CT._offers_to_flights([o])
    assert len(rows) == 1
    assert "depTerminal" not in rows[0]


def test_propagate_terminal_cross_channel():
    # 航站楼=物理属性（同航班全渠道同值，与 depAirport/arrAirport 同族）：
    # 同指纹组内恰好一个非空值才补；值冲突不补（宁缺勿错）
    base = {"code": "CZ6954", "depDate": "2026-10-05", "depTime": "08:35",
            "arrTime": "13:20", "arrDate": "2026-10-05", "price": 2307}
    q = dict(base, _platform="qunar")
    t = dict(base, price=2310, _platform="tuniu",
             depTerminal="T3", arrTerminal="T2")
    rows = [dict(q), dict(t)]
    Alerter._propagate_fields(rows)
    assert rows[0]["depTerminal"] == "T3"
    assert rows[0]["arrTerminal"] == "T2"
    # 冲突不补：第三渠道 depTerminal 与 tuniu 不一致 → qunar 保持空
    c = dict(base, price=2320, _platform="ctrip", depTerminal="T1")
    rows2 = [dict(q), dict(t), dict(c)]
    Alerter._propagate_fields(rows2)
    assert not rows2[0].get("depTerminal")
    assert rows2[0]["arrTerminal"] == "T2"   # arrTerminal 无冲突仍补
