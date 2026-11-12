# -*- coding: utf-8 -*-
"""tuniu cabin 串舱修复：舱名/舱位代码随选中价政策配对。

r222 调研 B 实锤（_scratch/r222_research_b.md）：_fare_cabin 取首个
政策的舱名、不随 _adt_fare 选中价配对——公务舱政策排前时，行价是
经济舱最低价却标「公务舱」（三份独立 dump 复现 5/40、2/46、3/44，
DB 今日轮 56/605 公务舱行价 2615/2920 旁证）。同族：cabinCode 全列表
聚合守卫出勤仅 35-59%，选中价政策内聚合三 dump 均 100% 恒单码。

fixture 取生产真实形态：同一 offer 的 flightPriceList 多政策并存、
公务舱政策在前、经济舱政策价更低（真实 dump 的错配触发形态）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15122_tuniu_cabin.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402

_CT = TuniuCrawler

_FLIGHT_LIST = {
    "MU8370#2026-10-06#URC#SHA": {
        "airlineCompany": "东航",
        "departureTime": "20:20", "arrivalTime": "01:15",
        "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
        "flightTime": "295",
    },
}


def _policy(cabin, code, price, black=False, discount="6.7折"):
    pj = [{"priceFlightCabinList": [
        {"cabinTypeName": cabin, "cabinCode": code}]}] if cabin else []
    return {"supportBlack": black,
            "fareBreakdownList": [
                {"baseFare": price, "discount": discount, "psgType": "ADT"}],
            "priceJourneyCabinList": pj}


def _raw(*policies):
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": list(policies)}
    return {"data": {"fareList": [fare], "flightList": _FLIGHT_LIST}}


def _one(*policies):
    offers = _CT._parse_offers(_raw(*policies))
    assert len(offers) == 1
    return offers[0]


def test_cabin_follows_selected_policy_not_first():
    # 串舱复现（生产错配形态）：公务舱政策排前、经济舱政策价更低
    # → 行价 1500（经济舱），舱名必须随选中价政策落「经济舱」
    o = _one(_policy("公务舱", "J", 3000), _policy("经济舱", "Y", 1500))
    assert o["price"] == 1500
    assert o["cabin"] == "经济舱"


def test_cabin_business_when_selected():
    # 公务舱政策恰是最低价时：舱名公务舱（选中价配对的双向正确性）
    o = _one(_policy("经济舱", "Y", 2000), _policy("公务舱", "J", 1800))
    assert o["price"] == 1800
    assert o["cabin"] == "公务舱"
    assert o["bizPrice"] == 1800  # _biz_fare 独立遍历不受本修复影响


def test_cabin_code_within_selected_policy():
    # cabinCode 随选中价政策聚合：两政策各单码（J/Y），选中经济舱
    # → 落 Y（旧全列表聚合 J≠Y 恒空=出勤 35-59% 的根因）
    o = _one(_policy("公务舱", "J", 3000), _policy("经济舱", "Y", 1500))
    assert o["cabinCode"] == "Y"


def test_cabin_code_multi_in_selected_policy_stays_empty():
    # 选中价政策内仍多码：宁缺勿错守卫保持（单政策内不落）
    o = _one({"supportBlack": False,
              "fareBreakdownList": [
                  {"baseFare": 1500, "psgType": "ADT"}],
              "priceJourneyCabinList": [
                  {"priceFlightCabinList": [
                      {"cabinCode": "Y"}, {"cabinCode": "B"}]}]},
             _policy("公务舱", "J", 3000))
    assert o["price"] == 1500
    assert o["cabinCode"] == ""


def test_black_tie_normal_policy_wins_cabin():
    # 同价平手按普通政策算（标记零误报）：舱名随平手胜者（普通政策）
    o = _one(_policy("经济舱", "Y", 1000, black=True),
             _policy("经济舱", "M", 1000))
    assert o["price"] == 1000
    assert not o.get("blackCard")
    assert o["cabin"] == "经济舱"


def test_cabin_legacy_top_level_fallback_kept():
    # 09-18 旧顶层形态兼容回退保持：选中政策无舱名 → fare 顶层舱名
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": 3600,
                                        "psgType": "ADT"}]}],
            "priceJourneyCabinList": [
                {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}
    offers = _CT._parse_offers(
        {"data": {"fareList": [fare], "flightList": _FLIGHT_LIST}})
    assert len(offers) == 1
    assert offers[0]["cabin"] == "经济舱"


def test_cabin_missing_returns_empty():
    # 两层都无舱名：宁缺勿错返回空（不借兄弟政策的舱名造数据）
    o = _one({"supportBlack": False,
              "fareBreakdownList": [{"baseFare": 1500, "psgType": "ADT"}]})
    assert o["price"] == 1500
    assert o["cabin"] == ""
    assert o["cabinCode"] == ""
