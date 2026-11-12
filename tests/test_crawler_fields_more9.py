# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r311_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r311_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r311")
_CT = CtripCrawler({}, _LOG)


# ---- tongcheng（sts 缺席 → prate/meal 双空串平铺案） ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def _tc_text(fl):
    return json.dumps({"data": {"fl": fl}}, ensure_ascii=False)


def test_tongcheng_prate_absent_without_sts():
    """fl 无 sts → prate 不落（直飞 100% 空串平铺案，DB 实锤
    36/36；缺席≡空串消费端等价，r241 同族漏网收口）。"""
    rows = TongchengCrawler._extract_flights(_tc_text([_tc_flight()]))
    assert rows, "样本应产出至少一行"
    assert "prate" not in rows[0], rows[0]


def test_tongcheng_meal_absent_without_sts():
    """fl 无 sts → meal 不落（同函数镜像消费点，同族同轮收口）。"""
    rows = TongchengCrawler._extract_flights(_tc_text([_tc_flight()]))
    assert rows, "样本应产出至少一行"
    assert "meal" not in rows[0], rows[0]


def test_tongcheng_prate_meal_still_landed():
    """sts tt=1/tt=4 有值照落：prate 提取百分数、meal 原文词面。"""
    fl = _tc_flight(sts=[{"tt": 1, "td": "到达准点率97%"},
                         {"tt": 4, "td": "无餐食"}])
    rows = TongchengCrawler._extract_flights(_tc_text([fl]))
    assert rows and rows[0].get("prate") == "97", rows
    assert rows[0].get("meal") == "无餐食", rows


# ---- ctrip（classinfor/aset 双源皆缺 → prate 空串平铺案） ----

def _ctrip_item(segs, policies, aset=None):
    item = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        item["aset"] = aset
    return item


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, ci=None):
    p = {"tprice": price, "quantity": 5, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def test_ctrip_prate_absent_without_sources():
    """classinfor 无 prate 且 aset 无 InTimeTag → prate 不落
    （post-start 空串 179 例平铺案）。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    item = _ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert "prate" not in row, row


def test_ctrip_prate_still_landed():
    """classinfor.prate 有值照落。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    ci = {"cgrd": 0, "prate": 92}
    item = _ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("prate") == "92", row


# ---- qunar PC（binfo1.mealDesc 缺 → meal 空串平铺案） ----

def _pc_flight(b1=None, b2=None, **top):
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    return json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_qunar_pc_meal_absent_without_mealdesc():
    """binfo1 无 mealDesc → meal 不落（PC 路径同族残留；H5 路径
    r242 已收口）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([_pc_flight()]),
                                          "2026-10-05")
    assert rows, "样本应产出至少一行"
    assert "meal" not in rows[0], rows[0]


def test_qunar_pc_meal_still_landed():
    """mealDesc 有值照落（渠道显式词面「无餐食」是有值形态）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"mealDesc": "无餐食"})]), "2026-10-05")
    assert rows and rows[0].get("meal") == "无餐食", rows


# ---- tuniu（mealName 缺 → meal 空串平铺案） ----

def _tuniu_raw(flight_nos="MU8370", **detail_extra):
    detail = {"airlineCompany": "东航", "airlineIataCode": "MU",
              "departureTime": "20:20", "arrivalTime": "01:15",
              "departureDate": "2026-10-06", "arrivalDate": "2026-10-06",
              "flightTime": "295"}
    detail.update(detail_extra)
    return {"data": {"fareList": [
        {"flightOptions": [{"flightNos": flight_nos}],
         "flightPriceList": [{"fareBreakdownList": [
             {"baseFare": 2472, "psgType": "ADT"}],
             "priceJourneyCabinList": [
                 {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}]}],
        "flightList": {f"{flight_nos}#2026-10-06#URC#SHA": detail}}}


def test_tuniu_meal_absent_without_mealname():
    """detail 无 mealName → meal 不落（断供前旧代平铺案同族收口）。"""
    offers = TuniuCrawler._parse_offers(_tuniu_raw(), logger=_LOG)
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows, "样本应产出至少一行"
    assert "meal" not in rows[0], rows[0]


def test_tuniu_meal_still_landed():
    """mealName 有值照落。"""
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw(mealName="无餐"), logger=_LOG)
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and rows[0].get("meal") == "无餐", rows
