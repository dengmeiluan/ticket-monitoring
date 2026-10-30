# -*- coding: utf-8 -*-
"""r240 数据层（渠道调研立案）：

qunar PC 中转/经停行「航程公里」语义修正——distance 键语义=全程
实际飞行公里，旧读层取 binfo1.distance（首段）落库：中转行全程
1758+1890=3648km 却显示「航程1758km」（读者语义错误，dump 实证
两段 distance 48/48 全场在场，自算段和即真值）。直飞行（仅
binfo.distance）不变；二段缺席时宁缺勿错不落键（部分和不能冒充
全程，prate=20 守卫同律）。

样本形态取自生产冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r240_fields.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("r240")
_QC = QunarCrawler({}, _LOG)


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（与 r237 夹具同构）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    import json as _json
    return _json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_pc_trans_distance_sums_segments():
    """中转行 distance=两段之和（全程实际飞行公里）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight(b1={"distance": "1758"},
                   b2={"arrTime": "18:20", "arrDate": "2026-10-05",
                       "depTime": "14:00", "distance": "1890"}),
    ]), "2026-10-05")
    assert rows, "中转样本应产出至少一行"
    assert rows[0].get("distance") == 3648, rows[0]


def test_pc_direct_distance_unchanged():
    """直飞行 distance=整体公里（binfo.distance），行为不变。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight(b1={"distance": "3649"}),
    ]), "2026-10-05")
    assert rows and rows[0].get("distance") == 3649, rows


def test_pc_trans_second_seg_distance_missing_not_landed():
    """中转行二段 distance 缺席→整键不落（部分和不能冒充全程）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight(b1={"distance": "1758"},
                   b2={"arrTime": "18:20", "arrDate": "2026-10-05",
                       "depTime": "14:00"}),
    ]), "2026-10-05")
    assert rows, "中转样本应产出至少一行"
    assert "distance" not in rows[0], rows[0]


# ---- tuniu planeAge 无值不落键（数据观测 P3：空串 42% 平铺） ----

def _tuniu_raw(flight_year=None):
    """tuniu offer 最小载体（flightList detail 携/缺 flightYear，
    夹具形态对齐 test_v15109 同构）。"""
    detail = {"airlineCompany": "东航", "airlineIataCode": "MU",
              "departureTime": "20:20", "arrivalTime": "01:15",
              "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
              "flightTime": "295"}
    if flight_year is not None:
        detail["flightYear"] = flight_year
    return {"data": {"fareList": [
        {"flightOptions": [{"flightNos": "MU8370"}],
         "flightPriceList": [{"fareBreakdownList": [
             {"baseFare": 2472, "psgType": "ADT"}],
             "priceJourneyCabinList": [
                 {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}]}],
        "flightList": {"MU8370#2026-10-06#URC#SHA": detail}}}


def test_tuniu_plane_age_absent_not_landed():
    """detail 层 flightYear 缺席→planeAge 键不落（空串占位不落键）。"""
    from crawlers.tuniu import TuniuCrawler
    offers = TuniuCrawler._parse_offers(_tuniu_raw(), logger=_LOG)
    assert offers, "样本应产出至少一 offer"
    assert "planeAge" not in offers[0], offers[0]
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows, "样本应产出至少一行"
    assert "planeAge" not in rows[0], rows[0]


def test_tuniu_plane_age_valued_still_landed_raw_form():
    """flightYear 有值照落原始串形态（"6.3" 不转数值）。"""
    from crawlers.tuniu import TuniuCrawler
    offers = TuniuCrawler._parse_offers(_tuniu_raw("6.3"), logger=_LOG)
    assert offers and offers[0].get("planeAge") == "6.3", offers[0]
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and rows[0].get("planeAge") == "6.3", rows[0]
