# -*- coding: utf-8 -*-
"""v1.5.80 渠道字段调研落地钉（audit_v180 A/B 两篇）。

新增决策字段（三端同轮）：
 - tuniu bizPrice：flightPriceList[] 公务/商务/头等舱政策 ADT baseFare
   最低（B 篇候选#2，85% 在场；与 ctrip bizPrice 同键同协议，webui
   通道现成零改动）；与 _adt_fare 完全独立提取防串舱（次低价≠公务舱，
   ctrip「舱位随最低价政策配对」同律）
 - tongcheng bizPrice：lps[] 命中（公务|商务|头等舱）政策的 atp 最低
   （B 篇候选#1，69% 在场；_has_ticket 同守卫，无票公务价=幻影参考
   宁缺；明确不采 cfcps——E1 时段聚合价挂别家航班公务价实锤）
 - tongcheng discount：最低价政策 pts[].td「6.8折经济舱」同串复用
   （现只提舱位丢折扣；tuniu/fliggy discount 同键同态仅入 extra）
 - ctrip agePolicy：最低价政策 fnotelst nt=20「2767_LimitedYoungAgePolicy」
   → 限青年/限老年/限年龄（A 篇候选#1，青老年票硬性购买资格，误购
   无法值机；未知英文类型整段丢弃宁缺勿错；S-4 破案 nt=104 zstd 与
   nt=20 在 9/9 航班同现且 nt=20 自带细分与价格前缀，零新依赖取文案源）
 - ctrip prate 补源：classNoteList nt=1 兜底（dump 302/302 vs prate
   键 208/304，两源 208/208 零背离——覆盖率 68%→近100%，零新键）
 - tuniu plane 兜底：craftTypeName 缺失行落 craftType 原码（33/33 恒在，
   补 DB 11% 机型缺口；不建码表翻译，值形与 tongcheng 同域）
"""

import json

from crawlers.ctrip import CtripCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler


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
    """nt=1 非数字脏值弃（宁缺勿错）。"""
    fs = _ctrip_parse({"tprice": 800, "quantity": 5,
                       "classinfor": [{"classNoteList": [
                           {"notetype": 1, "notecnt": "--"}]}]})
    assert fs["prate"] == ""
