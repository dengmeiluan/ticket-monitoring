# -*- coding: utf-8 -*-
"""渠道字段第十八批回归：ctrip FreeLuggage 行李旗标（中转 transferBaggage
direct 第二源 + 直飞 labels 观测词）/ ctrip Limited*Membership 会员专享
资格价（agePolicy 词面扩两名）/ ctrip aset「经济舱售罄」白名单词 /
qunar mixCodeShare 二段实际承运 shareCarrier 兜底源。

样本形态全部取自生产 dump 实证（_scratch/research_v190_a.md）：
- FreeLuggage：fnotelst notetype=31 notecnt 逗号旗标串（中转政策
  74/75≈100%、直飞 71/312≈23%；9C/3U/FM/HO 恒 0=廉航不含托运自洽）。
  ctrip 是五渠道唯一无行李出口的渠道——「最低价不含免费托运」比价
  失真主因。中转行并入 transferBaggage 三态作 direct 第二信号源（与
  qunar flightMark.freeLuggage 推断律同律）；直飞行以 labels 白名单词
  「含免费托运」观测，不新增键。nt=10「行李直达」主源优先级不变。
- LimitedCtripMemberShip / LimitedAirlineMembership：classNoteList
  nt=3 旗标（12 政策/230 行，与老客专享零交集）——非会员出不了票的
  硬性购买门槛，并入既有 agePolicy 词面零新键；裸 AirlineMemberShip
  语义未证不采（宁缺勿错）。
- mixCodeShare：H5 行 mixCodeShare=1（5/288）时 binfo1.codeShare=1 但
  mainCarrierSimpleNameAndNo 恒空——二段实际承运在 mixFlightName
  第二行，作 shareCarrier 兜底源（同键加源，现出口空转）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1590_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

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
    assert r["transferBaggage"] == ""


def test_ctrip_free_luggage_nonlowest_policy_ignored():
    """FreeLuggage 挂在非最低价政策：不采（随最低价政策配对，与 nt=10
    「行李直达」同律——该行价格才是用户看到的价）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0}),
         _ctrip_policy(price=1500, ci={"cgrd": 0},
                       fnotelst=_FN_FREE_LUG)])
    assert _ctrip_one(item)["transferBaggage"] == ""


def test_ctrip_free_luggage_absent_unchanged():
    """无 nt=31 旗标：行为不变（中转行保持空串、直飞行无观测词）。"""
    tr = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 18:30:00"),
         _ctrip_seg("2026-10-06 20:10:00", "2026-10-06 23:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0})]))
    assert tr["transferBaggage"] == ""
    assert "含免费托运" not in tr["labels"]
    dm = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0})]))
    assert "含免费托运" not in dm["labels"]


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
    assert _qn_one(_qn_f())["shareCarrier"] == ""


# ---- tuniu：avgDelay 空串占位键卫生（观测 C 路建议修：无值不落键） ----

from crawlers.tuniu import TuniuCrawler  # noqa: E402

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
