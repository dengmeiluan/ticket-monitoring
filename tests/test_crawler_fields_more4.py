# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r242_fields.py
- tests/test_v1590_fields.py

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
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r242_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r242")
_QC = QunarCrawler({}, _LOG)


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（data.flights 普通数组形态）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    return json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_qunar_pc_plane_fulltype_readable():
    """可读形态照落：带体量括号 '波音737(中)'（与 H5 plane 同形）；
    planeSize 体量正则同源不受扰。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "738",
                              "planeFullType": "波音737(中)"})]),
        "2026-10-05")
    assert rows[0]["plane"] == "波音737(中)", rows[0]
    assert rows[0]["planeSize"] == "中型机", rows[0]


def test_qunar_pc_plane_bare_form_kept():
    """裸机型照落（planeFullType 是结构化满勤字段，'737-800' 读者
    可读——与 H5 binfo.name[1] 的 fullmatch 锚定拒裸形不同域：
    PC 换源后裸形是干净真值非脏形态）；体量正则不命中 planeSize
    不落（宁缺勿错既有门）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "73M",
                              "planeFullType": "波音737MAX8"})]),
        "2026-10-05")
    assert rows[0]["plane"] == "波音737MAX8", rows[0]
    assert "planeSize" not in rows[0], rows[0]
    rows2 = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "738",
                              "planeFullType": "737-800"})]),
        "2026-10-05")
    assert rows2[0]["plane"] == "737-800", rows2[0]


def test_qunar_pc_plane_junk_words_dropped():
    """渠道垃圾占位词不落（调研值域实证两形态）；planeSize 本就
    正则不命中，零连带。"""
    for junk in ("机型未定", "其他机型"):
        rows = QunarCrawler._parse_pc_flights(
            _pc_text([_pc_flight({"planeType": "",
                                  "planeFullType": junk})]),
            "2026-10-05")
        assert "plane" not in rows[0], (junk, rows[0])
        assert "planeSize" not in rows[0], (junk, rows[0])


def test_qunar_pc_plane_missing_fulltype_never_falls_back():
    """planeFullType 缺席 → plane 键不落：机读码源随换源退役，
    不回落 planeType（机读码读者零增量，回落即垃圾复辟）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "73P"})]), "2026-10-05")
    assert "plane" not in rows[0], rows[0]


def test_qunar_pc_plane_transfer_row_same_source():
    """中转行同源换采（binfo1.planeFullType 首段机型，与既有
    plane 取数槽位一致）；二段信息不并（行级机型语义=首段执飞）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight({"planeType": "73P", "planeFullType": "空客320(中)"},
                   b2={"depTime": "13:30", "arrTime": "17:20",
                       "date": "2026-10-05", "arrDate": "2026-10-05",
                       "shortCarrier": "CZ", "airCode": "6940",
                       "planeType": "738",
                       "planeFullType": "波音737(中)"},
                   transCity="西安")]),
        "2026-10-05")
    assert rows[0]["plane"] == "空客320(中)", rows[0]
    assert rows[0]["planeSize"] == "中型机", rows[0]


# ---- H5 兜底路径同族收口（r242 after 观测 r1 抓漏：meal/baggage/plane
# 三键 H5 行构造器仍恒落空串——中转行 48/48 平铺，r241 收口 8 键的
# H5 侧余量；与 PC 出口同轮对齐为「无值不落键」）----

def _h5_row(**kw):
    """H5 行最小载体（无 addon/无机型词面的中转行形态）。"""
    f = {"minPrice": 1288, "code": "CZ3544/CZ6940", "transCity": "武汉",
         "binfo1": {"depTime": "21:40", "arrTime": "00:50",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"},
         "binfo2": {"depTime": "11:30", "arrTime": "14:00",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"}}
    f.update(kw)
    return json.dumps({"data": {"flights": [f]}}, ensure_ascii=False)


def test_qunar_h5_plane_meal_baggage_no_value_no_key():
    """H5 无值不落键：无 addon 信息且 binfo.name 无机型词面的行
    （生产中转行 48/48 实录形态），plane/meal/baggage 三键整键缺席
    （旧形为空串落库——与 PC 出口 walrus 门同口径）。"""
    rows = QunarCrawler._parse_response_flights(_h5_row())
    f = rows[0]
    for k in ("plane", "meal", "baggage"):
        assert k not in f, (k, f)


def test_qunar_h5_plane_meal_baggage_values_kept():
    """有值照落：机型词面（binfo.name[1] fullmatch 命中形态）与餐食/
    托运 addon 词面三键正常在位，词面与旧形一致。"""
    rows = QunarCrawler._parse_response_flights(_h5_row(
        binfo1={"depTime": "08:00", "arrTime": "10:00",
                "depDate": "2026-10-05", "arrDate": "2026-10-05",
                "name": ["春秋", "波音737(中)"]},
        flightAddInfoIntegration={"flightAdditionInfos": [
            {"name": "有餐", "icon": "x"},
            {"name": "免费托运20KG", "icon": "y"}]}))
    f = rows[0]
    assert f["plane"] == "波音737(中)", f
    assert f["planeSize"] == "中型机", f
    assert f["meal"] == "有餐", f
    assert f["baggage"] == "免费托运20KG", f


# ---- merged from tests/test_v1590_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t190")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip 构造器（沿用 v1589 形态，样本=生产 dump 实证） ----

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


def _ctrip_policy(price=1200, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


# dump 实证旗标串形态（notetype=31 notecnt 逗号分隔）
_FN_FREE_LUG = [{"notetype": 31,
                 "notecnt": "FreeRRE,MergeBooking,InterliningTag,"
                            "LowestPrice,ItineraryFloor,TS_RULE,"
                            "FreeLuggage"}]


def test_ctrip_free_luggage_transfer_direct():
    """中转政策带 nt=31 FreeLuggage：transferBaggage=direct 第二信号源
    （与 qunar flightMark.freeLuggage 推断律同律——免费托运→推断两段
    可直挂，非实测直挂证据）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0}, fnotelst=_FN_FREE_LUG)])
    assert _ctrip_one(item)["transferBaggage"] == "direct"


def test_ctrip_free_luggage_domestic_labels():
    """直飞行政策带 FreeLuggage：labels 加「含免费托运」观测词（直飞
    无直挂概念，transferBaggage 保持空——渠道口径该词=含免费托运额）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0}, fnotelst=_FN_FREE_LUG)])
    r = _ctrip_one(item)
    assert "含免费托运" in r["labels"].split("·")
    assert "transferBaggage" not in r


def test_ctrip_free_luggage_nonlowest_policy_ignored():
    """FreeLuggage 挂在非最低价政策：不采（随最低价政策配对，与 nt=10
    「行李直达」同律——该行价格才是用户看到的价）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0}),
         _ctrip_policy(price=1500, ci={"cgrd": 0},
                       fnotelst=_FN_FREE_LUG)])
    assert "transferBaggage" not in _ctrip_one(item)


def test_ctrip_free_luggage_absent_unchanged():
    """无 nt=31 旗标：行为不变（中转行保持空串、直飞行无观测词）。"""
    tr = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0})]))
    assert "transferBaggage" not in tr
    assert "含免费托运" not in tr.get("labels", "")
    dm = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0})]))
    assert "含免费托运" not in dm.get("labels", "")


def test_ctrip_luggage_direct_word_still_wins():
    """nt=10「行李直达」主源与 nt=31 并存：仍 direct（主源优先级不变，
    FreeLuggage 只是第二信号源）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0},
                       fnotelst=_FN_FREE_LUG
                       + [{"notetype": 10, "notecnt": "航变免费退改|行李直达"}])])
    assert _ctrip_one(item)["transferBaggage"] == "direct"


# ---- ctrip：Limited*Membership 会员专享资格价（agePolicy 词面扩两名） ----

def test_ctrip_member_price_airline():
    """nt=3 逗号串含 LimitedAirlineMembership（9C dump 实证）：agePolicy=
    「限航司会员」——非会员出不了票的硬性购买门槛。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LockPrice,BusinessPriority,"
                                        "LimitedAirlineMembership"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=2410, ci=ci)]))
    assert r["agePolicy"] == "限航司会员"


def test_ctrip_member_price_ctrip():
    """分元素形态 LimitedCtripMemberShip（CZ 中转 dump 实证）：agePolicy=
    「限携程会员」。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "AirlineMemberShip"},
                            {"notetype": 3, "notecnt": "LimitedCtripMemberShip"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci=ci)]))
    assert r["agePolicy"] == "限携程会员"


def test_ctrip_member_bare_flag_ignored():
    """裸 AirlineMemberShip（可购会员价?语义未证）：不落 agePolicy
    （宁缺勿错——只认 Limited* 两词）。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "AirlineMemberShip"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci=ci)]))
    assert "agePolicy" not in r


def test_ctrip_member_nonlowest_policy_ignored():
    """会员旗标挂非最低价政策：不采（随最低价政策配对同律）。"""
    lo = {"cgrd": 0}
    hi = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LimitedAirlineMembership"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci=lo),
         _ctrip_policy(price=1500, ci=hi)]))
    assert "agePolicy" not in r


# ---- ctrip：aset「经济舱售罄」白名单词（零成本） ----

def test_ctrip_economy_sellout_label():
    """tcode=EconomyClassSellOut tagcnt「经济舱售罄」（CA8564 全班仅剩
    头等实证）：aset 白名单加词入 labels。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=9900, ci={"cgrd": 2})],
        aset=[{"tagarea": [{"tcode": "EconomyClassSellOut",
                            "tagcnt": "经济舱售罄"}]}])
    assert "经济舱售罄" in _ctrip_one(item)["labels"].split("·")


# ---- qunar：mixCodeShare 二段实际承运 shareCarrier 兜底 ----

def _qn_f(**kw):
    f = {
        "minPrice": 1200, "code": "CZ6981",
        "binfo": {"depTime": "08:00", "arrTime": "14:30",
                  "depDate": "2026-10-06", "arrDate": "2026-10-06",
                  "codeShare": 1, "mainCarrierSimpleNameAndNo": ""},
        "extparams": "{}",
    }
    f.update(kw)
    return f


def _qn_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows
    return rows[0]


def test_qunar_mix_codeshare_second_leg_carrier():
    """mixCodeShare=1 且 mainCarrierSimpleNameAndNo 恒空（dump 5/288）：
    二段实际承运取 mixFlightName 第二行（「河北航NS8266\\n\\n东航MU2533」
    →「东航MU2533」）——现出口空转信息全丢。"""
    r = _qn_one(_qn_f(mixCodeShare=1,
                      mixFlightName="河北航NS8266\n\n东航MU2533"))
    assert r["shareCarrier"] == "东航MU2533"


def test_qunar_share_carrier_main_source_wins():
    """mainCarrierSimpleNameAndNo 有值：仍取主源（兜底只在主源空时）。"""
    f = _qn_f()
    f["binfo"]["mainCarrierSimpleNameAndNo"] = "上航FM9224"
    f["mixCodeShare"] = 1
    f["mixFlightName"] = "河北航NS8266\n\n东航MU2533"
    assert _qn_one(f)["shareCarrier"] == "上航FM9224"


def test_qunar_mix_share_absent_unchanged():
    """非 mixCodeShare 行为不变：codeShare 无 mainCarrier 仍空串
    （宁缺勿错，不凭空造源）。"""
    assert "shareCarrier" not in _qn_one(_qn_f())


# ---- tuniu：avgDelay 空串占位键卫生（观测 C 路建议修：无值不落键） ----

_TN_FLIGHT = {
    "airlineCompany": "东航",
    "departureTime": "20:20", "arrivalTime": "01:15",
    "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
    "flightTime": "295",
}


def _tn_row(avg_delay_time):
    d = dict(_TN_FLIGHT)
    if avg_delay_time is not None:
        d["avgDelayTime"] = avg_delay_time
    raw = {"data": {"fareList": [{
        "flightOptions": [{"flightNos": "MU8370"}],
        "flightPriceList": [{"fareBreakdownList": [
            {"baseFare": 3600, "psgType": "ADT"}]}],
    }], "flightList": {"MU8370#2026-10-06#URC#SHA": d}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows
    return rows[0]


def test_tuniu_avg_delay_absent_no_key():
    """avgDelayTime 空串/缺席：无值不落键（生产 44.2% 空串占位——
    消费端 None/空串等价、哨兵出勤统计不变，纯 DB 卫生）。"""
    assert "avgDelay" not in _tn_row("")
    assert "avgDelay" not in _tn_row(None)


def test_tuniu_avg_delay_digit_int():
    """数字形态 "29"：仍落 int 29（既有行为不变）。"""
    assert _tn_row("29")["avgDelay"] == 29


def test_tuniu_avg_delay_nondigit_dropped():
    """非数字脏值：不落键（原「非数字留空串」占位形态一并关闭）。"""
    assert "avgDelay" not in _tn_row("abc")
