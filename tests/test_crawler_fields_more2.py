# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r240_fields.py
- tests/test_v15127_fields.py
- tests/test_v15130_fields.py
- tests/test_v180_fields.py
- tests/test_v195_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import pytest
import sys

from core.alerter import Alerter
from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r240_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_v15127_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_v15130_fields.py ----

# ---- qunar H5 ----

def _h5_row(trans_info):
    b1 = {"depTime": "08:00", "arrTime": "11:00",
          "depDate": "2026-10-06", "arrDate": "2026-10-06"}
    if trans_info is not None:
        b1["transInfo"] = trans_info
    f = {"minPrice": 800, "code": "MU8369", "transCity": "西安",
         "binfo1": b1,
         "binfo2": {"depTime": "13:30", "arrTime": "17:20",
                    "depDate": "2026-10-06", "arrDate": "2026-10-06"}}
    rows = QunarCrawler._extract_flights_obj([f])
    return rows[0] if rows else {}


def test_qunar_h5_trans_terminal_absent_without_value():
    """firstArrInfo 缺席/terminal 空=无值不落键（旧行为空串照落）。"""
    assert "transTerminal" not in _h5_row({"transTime": "5时50分"})
    assert "transTerminal" not in _h5_row(None)


def test_qunar_h5_trans_dep_terminal_absent_same_building():
    """secondDepInfo 与 firstArrInfo 同楼=无换乘增量不落（宁缺勿错）。"""
    ti = {"transTime": "5h45m",
          "firstArrInfo": {"airport": "正定", "terminal": "T2"},
          "secondDepInfo": {"airport": "正定", "terminal": "T2",
                            "time": "06:05"}}
    assert "transDepTerminal" not in _h5_row(ti)


# ---- qunar PC ----

_PC_DATE = "2026-10-06"


def _pc(**kw):
    b2 = {"depTime": "06:50", "arrTime": "09:10",
          "arrDate": "2026-10-07",
          "depTerminal": "T5", "depAirport": "咸阳机场"}
    b2.update(kw.pop("b2", {}))
    flight = {"minPrice": 2000, "code": "GS7495/9C6178",
              "transCity": "西安",
              "binfo1": {"depTime": "19:25", "arrTime": "21:40",
                         "date": _PC_DATE, "arrTerminal": "T3",
                         "arrAirport": "咸阳机场"},
              "binfo2": b2}
    flight.update(kw)
    return json.dumps({"data": {"flights": [flight]}}, ensure_ascii=False)


def test_qunar_pc_trans_terminals_absent_without_value():
    """二段楼空串/同楼=不落；直飞行双键全不落。"""
    out = QunarCrawler._parse_pc_flights(_pc(b2={"depTerminal": ""}),
                                         _PC_DATE)
    assert "transDepTerminal" not in out[0]
    same = QunarCrawler._parse_pc_flights(_pc(b2={"depTerminal": "T3"}),
                                          _PC_DATE)
    assert "transDepTerminal" not in same[0]
    direct = json.dumps({"data": {"flights": [{
        "minPrice": 2000, "code": "9C8866",
        "binfo": {"depTime": "08:00", "arrTime": "11:30",
                  "date": _PC_DATE, "arrDate": _PC_DATE}}]}})
    d = QunarCrawler._parse_pc_flights(direct, _PC_DATE)[0]
    assert "transTerminal" not in d and "transDepTerminal" not in d


# ---- ctrip ----

def _ctrip_ci(**over):
    ci = {"cgrd": 0, "prate": 96, "meal": "", "extendinfos": []}
    ci.update(over)
    return ci


def _ctrip_direct():
    return {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                          "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                       "adate": "2026-10-06 11:30:00"},
                          "aportinfo": {"city": "上海"}}],
            "policyinfo": [{"tprice": 1200, "quantity": 3,
                            "classinfor": [_ctrip_ci()]}]}


def test_ctrip_trans_terminal_absent_on_direct():
    """直飞行不落中转航站楼键（旧行为空串照落）。"""
    obj = {"fltitem": [_ctrip_direct()]}
    rows = CtripCrawler._extract_ctrip_flights(
        CtripCrawler, json.dumps(obj, ensure_ascii=False))
    assert rows and "transTerminal" not in rows[0]


# ---- tongcheng ----

def _tc_fp():
    return {"dt": "2026-10-06 13:20", "at": "2026-10-06 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖",
            "ss": [{"fn": "CZ6981", "dt": "2026-10-06 13:20",
                    "at": "2026-10-06 16:05", "aat": "T3", "dac": "URC",
                    "aac": "YZY"},
                   {"fn": "MU5700", "dt": "2026-10-06 18:20",
                    "at": "2026-10-06 21:30", "dat": "T5", "dac": "YZY",
                    "aac": "PVG"}],
            "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}


def _tc_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


def test_tongcheng_trans_terminals_absent_without_value():
    """段级 aat/dat 缺失=无值不落键（有值照落不变）。"""
    fp = _tc_fp()
    del fp["ss"][0]["aat"]
    assert "transTerminal" not in _tc_rows(fp)
    fp2 = _tc_fp()
    del fp2["ss"][1]["dat"]
    assert "transDepTerminal" not in _tc_rows(fp2)


# ---- merged from tests/test_v180_fields.py ----

# ---- tuniu bizPrice：公务/商务/头等舱政策 ADT 最低价 ----

def _tj_pr(cabin, fare):
    return {"fareBreakdownList": [{"psgType": "ADT", "baseFare": fare}],
            "priceJourneyCabinList": [{"priceFlightCabinList":
                                        [{"cabinTypeName": cabin}]}]}


def test_tuniu_biz_fare_basic():
    """经济 731 + 公务 7310 → bizPrice=7310（与同程 MU8368 同值互证）。"""
    assert TuniuCrawler._biz_fare(
        [_tj_pr("经济舱", 731), _tj_pr("公务舱", 7310)]) == 7310.0


def test_tuniu_biz_fare_first_class_and_business():
    """头等舱/商务舱同词表（三渠道 bizPrice 判定词表一致）。"""
    assert TuniuCrawler._biz_fare([_tj_pr("头等舱", 9900)]) == 9900.0
    assert TuniuCrawler._biz_fare([_tj_pr("商务舱", 7310)]) == 7310.0


def test_tuniu_biz_fare_none_economy_only():
    """仅经济政策 → None（调用方不落键）。"""
    assert TuniuCrawler._biz_fare([_tj_pr("经济舱", 731)]) is None


def test_tuniu_biz_fare_min_across_policies():
    """多公务政策取最低。"""
    assert TuniuCrawler._biz_fare(
        [_tj_pr("公务舱", 8600), _tj_pr("头等舱", 7930)]) == 7930.0


def test_tuniu_biz_fare_domain_guard():
    """超域（>50000）脏值不算（_to_price 同域纪律）。"""
    assert TuniuCrawler._biz_fare(
        [_tj_pr("经济舱", 731), _tj_pr("公务舱", 60000)]) is None


def test_tuniu_biz_fare_empty():
    assert TuniuCrawler._biz_fare([]) is None


def test_tuniu_offer_row_carries_bizprice():
    """offer→row 透传：bizPrice 有值才落（无值不堆 extra）。"""
    rows = TuniuCrawler._offers_to_flights([{
        "airline": "东方航空", "flight_no": "MU5700",
        "depart_time": "08:30", "arrive_time": "11:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 1760.0, "bizPrice": 7310,
    }, {
        "airline": "东方航空", "flight_no": "MU5634",
        "depart_time": "09:30", "arrive_time": "12:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 4730.0,
    }])
    assert rows[0]["bizPrice"] == 7310
    assert "bizPrice" not in rows[1]


def test_tuniu_plane_fallback_crafttype():
    """craftTypeName 缺失行落 craftType 原码（「73M」与 tongcheng 同域）。"""
    rows = TuniuCrawler._offers_to_flights([{
        "airline": "南方航空", "flight_no": "CZ6993",
        "depart_time": "08:00", "arrive_time": "12:20",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 2000.0, "craftTypeName": "73M",
    }, {
        "airline": "南方航空", "flight_no": "CZ6995",
        "depart_time": "10:00", "arrive_time": "14:20",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 2100.0, "craftTypeName": "空客320",
    }])
    assert rows[0]["plane"] == "73M"
    assert rows[1]["plane"] == "空客320"


# ---- tongcheng bizPrice + discount：lps 公务政策 atp / pts 同串折扣 ----

def _tc_body(lps):
    f = {"fn": "GS7587", "dt": "2026-10-06 09:30:00",
         "at": "2026-10-06 14:05:00", "asn": "天津", "td": "4h35m",
         "afn": "空客320(中)", "dasn": "天山", "aasn": "虹桥",
         "dat": "", "aat": "T2", "icsf": False, "sfd": "", "lps": lps}
    return json.dumps({"success": True, "data": {"fl": [f]}})


_ECON = {"atp": "1760", "brs": [{"al": 9}], "pts": [{"td": "5.4折经济舱"}]}


def test_tc_bizprice_from_business_policy():
    fs = TongchengCrawler._extract_flights(_tc_body(
        [_ECON, {"atp": "8340", "brs": [{"al": 4}],
                 "pts": [{"td": "7.5折公务舱"}]}]))
    assert fs[0]["bizPrice"] == 8340
    assert fs[0]["cabin"] == "经济舱"      # 舱位仍随最低价政策，不被串舱
    assert fs[0]["discount"] == "5.4折"    # 折扣随最低价政策同串复用


def test_tc_bizprice_min_of_multi_business():
    """公务 8340 / 商务 7310 / 头等 12340 → 取最低 7310。"""
    fs = TongchengCrawler._extract_flights(_tc_body(
        [_ECON,
         {"atp": "8340", "brs": [{"al": 4}], "pts": [{"td": "公务舱"}]},
         {"atp": "7310", "brs": [{"al": 2}], "pts": [{"td": "商务舱"}]},
         {"atp": "12340", "brs": [{"al": 1}], "pts": [{"td": "头等舱"}]}]))
    assert fs[0]["bizPrice"] == 7310


def test_tc_bizprice_absent_when_economy_only():
    fs = TongchengCrawler._extract_flights(_tc_body([_ECON]))
    assert "bizPrice" not in fs[0]


def test_tc_bizprice_skips_unticketed_policy():
    """公务政策 al=0 无票不落（幻影参考价宁缺勿错）。"""
    fs = TongchengCrawler._extract_flights(_tc_body(
        [_ECON, {"atp": "8340", "brs": [{"al": 0}],
                 "pts": [{"td": "公务舱"}]}]))
    assert "bizPrice" not in fs[0]


def test_tc_discount_full_price_verbatim():
    """「全价经济舱」如实落「全价」（与 tuniu/fliggy 值域一致）。"""
    fs = TongchengCrawler._extract_flights(_tc_body(
        [{"atp": "1760", "brs": [{"al": 9}],
          "pts": [{"td": "全价经济舱"}]}]))
    assert fs[0]["discount"] == "全价"


def test_tc_discount_no_pts_no_key():
    """政策无 pts：discount 不落键（恒空键不堆 extra）。"""
    fs = TongchengCrawler._extract_flights(_tc_body(
        [{"atp": "1760", "brs": [{"al": 9}]}]))
    assert "discount" not in fs[0]


# ---- ctrip agePolicy + prate 补源（走真实解析入口） ----

def _ctrip_seg():
    return {"basinfo": {"flgno": "HO1256"},
            "dateinfo": {"ddate": "2026-10-06 09:30:00",
                         "adate": "2026-10-06 14:05:00"},
            "dportinfo": {"city": "URC", "aport": "URC", "bsname": ""},
            "aportinfo": {"city": "SHA", "aport": "SHA", "bsname": "T2"}}


def _ctrip_parse(policy):
    item = {"mutilstn": [_ctrip_seg()], "policyinfo": [policy],
            "aset": []}
    return CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))[0]


def test_ctrip_age_policy_young():
    fs = _ctrip_parse({"tprice": 2767, "quantity": 5,
                       "fnotelst": [{"notetype": 20,
                                     "notecnt": "2767_LimitedYoungAgePolicy"}]})
    assert fs["agePolicy"] == "限青年"


def test_ctrip_age_policy_old_and_plain():
    fs = _ctrip_parse({"tprice": 2278, "quantity": 5,
                       "fnotelst": [{"notetype": 20,
                                     "notecnt": "2278_LimitedOldAgePolicy"}]})
    assert fs["agePolicy"] == "限老年"
    fs2 = _ctrip_parse({"tprice": 2730, "quantity": 5,
                        "fnotelst": [{"notetype": 20,
                                      "notecnt": "2730_LimitedAgePolicy"}]})
    assert fs2["agePolicy"] == "限年龄"


def test_ctrip_age_policy_student():
    """第 5 类：学生专享价（dump 实证与 aset PT_PassengerAgeLimit
    「16-25周岁」同价 1:1 互证）——不入映射则最低价学生票丢「买不了」信号。"""
    fs = _ctrip_parse({"tprice": 2718, "quantity": 5,
                       "fnotelst": [{"notetype": 20,
                                     "notecnt": "2718_LimitedStudentPolicy"}]})
    assert fs["agePolicy"] == "限学生"


def test_ctrip_age_policy_unknown_type_discarded():
    """未知英文类型整段丢弃宁缺勿错（词表白名单外不落）。"""
    fs = _ctrip_parse({"tprice": 2767, "quantity": 5,
                       "fnotelst": [{"notetype": 20,
                                     "notecnt": "2767_LimitedSomethingElse"}]})
    assert "agePolicy" not in fs


def test_ctrip_age_policy_not_set_when_not_on_best():
    """受限政策非最低价政策不落（只标「你看到的最低价是受限价」强信号）。"""
    fs = _ctrip_parse({"tprice": 2600, "quantity": 5})
    item = {"mutilstn": [_ctrip_seg()],
            "policyinfo": [
                {"tprice": 2600, "quantity": 5},
                {"tprice": 2767, "quantity": 5,
                 "fnotelst": [{"notetype": 20,
                               "notecnt": "2767_LimitedYoungAgePolicy"}]}],
            "aset": []}
    fs2 = CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))[0]
    assert fs is not None and "agePolicy" not in fs2


def test_ctrip_prate_fallback_classnote():
    """prate 键缺失时 classNoteList nt=1 兜底（「97.0」→「97」）。"""
    fs = _ctrip_parse({"tprice": 800, "quantity": 5,
                       "classinfor": [{"classNoteList": [
                           {"notetype": 1, "notecnt": "97.0"},
                           {"notetype": 2, "notecnt": "H"}]}]})
    assert fs["prate"] == "97"
    assert fs["cabinCode"] == "H"   # nt=2 舱位字母不受影响


def test_ctrip_prate_primary_wins():
    """prate 键在场时优先（两源并存不回退）。"""
    fs = _ctrip_parse({"tprice": 800, "quantity": 5,
                       "classinfor": [{"prate": 98.0, "classNoteList": [
                           {"notetype": 1, "notecnt": "90.0"}]}]})
    assert fs["prate"] == "98"


def test_ctrip_prate_fallback_dirty_discarded():
    """nt=1 非数字脏值弃（宁缺勿错）。r311 起弃值连空串键一并
    不落（无值不落键收口，缺席≡空串消费端等价）。"""
    fs = _ctrip_parse({"tprice": 800, "quantity": 5,
                       "classinfor": [{"classNoteList": [
                           {"notetype": 1, "notecnt": "--"}]}]})
    assert "prate" not in fs


# ---- merged from tests/test_v195_fields.py ----

def _tc_flight(**over):
    """最小 book1 航班（形态照抄 tests/test_v1554_fields.py 同族构造，
    真值锚：CA8564 2026-10-06 16:50 ieso=True 第二代=公务 9900 al=30）。"""
    f = {"fn": "CA8564", "dt": "2026-10-06 16:50:00",
         "at": "2026-10-06 21:35:00", "asn": "国航",
         "dasn": "天山", "aasn": "虹桥",
         "amt": "中", "afn": "空客330(中)",
         "lps": [{"atp": "9900", "brs": [{"al": 30}],
                  "pts": [{"td": "公务舱"}]}],
         "ieso": True}
    f.update(over)
    return json.dumps({"success": True, "data": {"fl": [f]}})


def _one(text):
    fs = TongchengCrawler._extract_flights(text)
    assert len(fs) == 1
    return fs[0]


def test_tongcheng_ieso_sellout_label_second_gen():
    """第二代形态：经济舱政策整条消失、仅剩公务有票 → 挂「经济舱售罄」。"""
    f = _one(_tc_flight())
    assert f["price"] == 9900 and f["cabin"] == "公务舱"
    assert "经济舱售罄" in f["labels"].split("·")


def test_tongcheng_ieso_first_gen_eco_policy_without_ticket():
    """第一代形态：经济舱政策在场但 al=0（无票被既有守卫滤），
    公务舱有票幸存 → 仍挂词（两代通吃）。"""
    f = _one(_tc_flight(lps=[
        {"atp": "2770", "brs": [{"al": 0}],
         "pts": [{"td": "7折经济舱"}]},
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}]},
    ]))
    assert f["price"] == 9900 and f["cabin"] == "公务舱"
    assert "经济舱售罄" in f["labels"].split("·")


def test_tongcheng_ieso_contradiction_not_labeled():
    """矛盾态守卫：ieso=True 但经济舱政策有票（B 路两轮语料 0 例的
    幻想形态）→ 一律不挂，宁漏勿错。"""
    f = _one(_tc_flight(lps=[
        {"atp": "2770", "brs": [{"al": 9}],
         "pts": [{"td": "7折经济舱"}]},
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}]},
    ]))
    assert f["price"] == 2770 and f["cabin"] == "经济舱"
    assert "经济舱售罄" not in f.get("labels", "")


def test_tongcheng_ieso_eco_survivor_not_labeled():
    """防御：ieso=True 且幸存行自身就是(超级)经济舱 → 不挂
    （「经济舱售罄」挂经济舱行=语义自相矛盾）。"""
    f = _one(_tc_flight(
        lps=[{"atp": "2770", "brs": [{"al": 30}],
              "pts": [{"td": "7折经济舱"}]}]))
    assert f["cabin"] == "经济舱"
    assert "经济舱售罄" not in f.get("labels", "")


@pytest.mark.parametrize("ieso", [False, None, "", "true", 1])
def test_tongcheng_ieso_non_strict_true_ignored(ieso):
    """类型守卫：严格 `is True`——False/缺失/空串/字符串"true"/1
    都不是渠道售罄声明（-1/1 类真值会误挂常态行）。"""
    f = _one(_tc_flight(ieso=ieso))
    assert "经济舱售罄" not in f.get("labels", "")


def test_tongcheng_ieso_cabin_parse_fail_not_labeled():
    """舱位名解析失败（pts.td 无舱位词）→ 不挂，宁漏勿错。"""
    f = _one(_tc_flight(
        lps=[{"atp": "9900", "brs": [{"al": 30}],
              "pts": [{"td": "6.8折"}]}]))
    # cabin 无值不落键（r239 空串落键收口：钉面从空串值改写为键缺席）
    assert "cabin" not in f
    assert "经济舱售罄" not in f.get("labels", "")


def test_tongcheng_ieso_labels_join_order():
    """既有标签共存：clct 舒适词在前、售罄词殿后，「·」join 单串。"""
    f = _one(_tc_flight(lps=[
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}],
         "clct": [{"tt": 1, "td": "大机型"},
                  {"tt": 3, "td": "座椅较宽"}]}]))
    assert f["labels"] == "大机型·座椅较宽·经济舱售罄"


def test_tongcheng_ieso_absent_flight_unchanged():
    """回归锚：报文无 ieso 键的常态航班 labels 组装零变化。"""
    f = _one(_tc_flight(ieso=None))
    assert "labels" not in f


# ---- demo 演示面：tongcheng 售罄词目检覆盖（同 v191 meal 演示先例） ----

def test_demo_covers_ieso_sellout_label(tmp_path):
    """tongcheng 演示行 labels 含「经济舱售罄」（演示目检面与生产
    值域对齐——真实形态挂公务舱幸存行）。"""
    import sqlite3
    import core.demo as demo
    db = str(tmp_path / "demo.db")
    demo.build_demo_db(db)
    conn = sqlite3.connect(db)
    labels = set()
    for (extra,) in conn.execute(
            "SELECT extra FROM flight_prices WHERE platform='tongcheng' "
            "AND extra != ''"):
        for f in json.loads(extra):
            if f.get("labels"):
                labels.update(f["labels"].split("·"))
    conn.close()
    assert "经济舱售罄" in labels, "tongcheng 售罄词无演示目检面"
