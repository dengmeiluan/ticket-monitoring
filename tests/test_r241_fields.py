# -*- coding: utf-8 -*-
"""r241 数据层：五渠道「属性不适用即落空串」残留键无值不落键收口。

r241 观测立案 35 键（重启后新代口径，_scratch/r241_observe.md）：
ctrip 10 / qunar 8 / tongcheng 7 / tuniu 8 / fliggy 2——空串占位
平铺入库，消费端缺席≡空串等价（.get falsy 门），哨兵非空出勤口径
等价（main._field_sentinel 全 get 形态）；写点统一条件展开
（r239 十写点/r240 planeAge 同款家族律），同轮 alerter 直查点改
.get 防缺席键 KeyError（alerter 行不经 normalize，crossDayDesc
恒写前提不成立）。

样本夹具形态取自既有渠道测试（test_v1555/test_r240 同构）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r241_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("r241")
_CT = CtripCrawler({}, _LOG)

# 观测立案收口键面（按渠道）
CTRIPT_KEYS = ("stopCitys", "stopTime", "crossDayDesc", "transferBaggage",
               "transCity", "shareCarrier", "labels", "plane",
               "planeSize", "meal")
QUNAR_KEYS = ("transferBaggage", "stopCitys", "crossDayDesc", "fewTicket",
              "shareCarrier", "labels", "transCity", "planeSize")
TONGCHENG_KEYS = ("crossDayDesc", "transCity", "stopCitys", "stopTime",
                  "labels", "shareCarrier", "planeSize")
TUNIU_KEYS = ("transCity", "stopCitys", "stopTime", "stopWin",
              "crossDayDesc", "labels", "shareCarrier", "planeSize")
FLIGGY_KEYS = ("transCity", "crossDayDesc")


# ---- ctrip：10 键 ----

def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, craft=None, flgno="CZ6981"):
    s = {"dateinfo": {"ddate": dd, "adate": ad},
         "basinfo": {"flgno": flgno},
         "dportinfo": {"bsname": "", "aport": "URC"},
         "aportinfo": {"bsname": "T2", "aport": "SHA"}}
    if craft is not None:
        s["craftinfo"] = craft
    return s


def _ctrip_policy(price=1200, ci=None):
    p = {"tprice": price, "quantity": 5, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def test_ctrip_direct_ten_keys_absent():
    """直飞最小行：10 键全部不落（空串=属性不适用，缺席与空串在
    消费端 .get falsy 门下等价）。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    item = _ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    for k in CTRIPT_KEYS:
        assert k not in row, (k, sorted(row))


def test_ctrip_valued_keys_still_landed():
    """有值照落：craft 双源 plane/planeSize + ci.meal。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    ci = {"cgrd": 0, "prate": 92, "meal": "有餐食"}
    item = _ctrip_item(
        [_ctrip_seg(dd, ad, craft={"kind": 2, "cdisname": "737(中)"})],
        [_ctrip_policy(ci=ci)])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row["planeSize"] == "中型机"
    assert row["meal"] == "有餐食"
    assert row.get("plane"), row


def test_ctrip_cabin_code_absent_without_note():
    """政策无 classinfor → cabinCode 不落（after 观测 r1 抓产中转行
    空串 1 例：classNoteList nt=2 缺席即无值，同族不落键）。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    item = _ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert "cabinCode" not in row, row


def test_ctrip_cabin_code_valued_note_still_landed():
    """classNoteList notetype=2 单字母在案 → cabinCode 照落
    （退改等级之根，tuniu 同键协议）。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    item = _ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("cabinCode") == "Y", row


# ---- qunar PC：8 键 ----

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


def test_qunar_pc_direct_eight_keys_absent():
    """直飞行：8 键全部不落（r239 已收 layover/lay2dep/discount 族，
    本轮收齐残留 8 键）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([_pc_flight()]),
                                          "2026-10-05")
    assert rows, "直飞样本应产出至少一行"
    for k in QUNAR_KEYS:
        assert k not in rows[0], (k, sorted(rows[0]))


def test_qunar_pc_transfer_and_stops_still_landed():
    """中转/经停/票少有值照落：transCity 随中转行（binfo2 在场即
    中转，缺城市时落「中转」占位词——456 行门逻辑）、stopCitys 随
    binfo.stopCitys、fewTicket 随 piaoShaoDesc。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight(b1={"stopCitys": ["庆阳"], "piaoShaoDesc": "票少"},
                   b2={"arrTime": "18:20", "arrDate": "2026-10-05",
                       "depTime": "14:00"}),
    ]), "2026-10-05")
    assert rows, "中转样本应产出至少一行"
    r = rows[0]
    assert r.get("transCity") == "中转", r
    assert r.get("stopCitys") == "庆阳", r
    assert r.get("fewTicket") == "票少", r


# ---- qunar H5：8 键（兜底路径同族收口，防软拒期复潮） ----

def _h5_direct(**binfo):
    f = {"minPrice": 1200, "code": "9C8846", "mixFlightName": "春秋9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_direct_eight_keys_absent():
    """H5 直飞行：8 键全部不落（与 PC 同键缺席口径对齐）。"""
    rows = QunarCrawler._extract_flights_obj([_h5_direct()])
    assert rows, "H5 直飞样本应产出至少一行"
    for k in QUNAR_KEYS:
        assert k not in rows[0], (k, sorted(rows[0]))


def test_qunar_h5_transfer_still_landed():
    """H5 中转照落：transCity 随中转行（与 PC 占位词口径同）。"""
    f = {"minPrice": 1500, "code": "GS7581/9C6402", "transCity": "西安",
         "binfo1": {"depTime": "06:30", "arrTime": "15:15",
                    "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "binfo2": {"depTime": "13:00"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows and rows[0].get("transCity") == "西安", rows


# ---- tongcheng：7 键 ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def test_tongcheng_direct_seven_keys_absent():
    """直飞行：7 键全部不落（transCity 恒空串键随族退役——中转
    重构路径 _extract_transfer_flights 有值照落不变）。"""
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight()]}}))
    assert rows, "同程直飞样本应产出至少一行"
    for k in TONGCHENG_KEYS:
        assert k not in rows[0], (k, sorted(rows[0]))


def test_tongcheng_valued_keys_still_landed():
    """有值照落：amt 结构化体量（既有主源行为不变）。"""
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight(amt="大")]}}))
    assert rows[0]["planeSize"] == "大型机"


# ---- tongcheng 中转路径同族收口（Soldier P2-2） ----

def _tc_fps_text(fp):
    return json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False)


def _tc_trans_fp(**kw):
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    fp.update(kw)
    return fp


def test_tongcheng_transfer_sameday_crossday_absent():
    """中转当日达行 crossDayDesc 不落（直飞路径已收口，中转重构
    路径同族漏随）；sc 有值 transCity 照落。"""
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(_tc_trans_fp()), "")
    assert rows, "中转样本应产出至少一行"
    assert rows[0].get("transCity") == "张掖", rows[0]
    assert "crossDayDesc" not in rows[0], rows[0]


def test_tongcheng_transfer_crossday_and_city_placeholder():
    """跨天中转 +1天 照落；sc 缺席 transCity 落「中转」占位词
    （qunar PC 先例：中转行恒带转移标识，防下游误分直飞）。"""
    fp = _tc_trans_fp()
    fp["at"] = "2026-10-06 01:30"
    del fp["sc"]
    rows = TongchengCrawler._extract_transfer_flights(_tc_fps_text(fp), "")
    assert rows, "跨天中转样本应产出至少一行"
    assert rows[0].get("transCity") == "中转", rows[0]
    assert rows[0].get("crossDayDesc") == "+1天", rows[0]


def test_tongcheng_transfer_planesize_absent_without_amn():
    """中转行段级 amn 无括号体量 → planeSize 不落（中转路径同族
    漏随第二案：after 观测 r1 抓产 4 行空串，直飞路径已收口）。"""
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(_tc_trans_fp()), "")
    assert rows, "中转样本应产出至少一行"
    assert "planeSize" not in rows[0], rows[0]


def test_tongcheng_transfer_planesize_valued_with_amn():
    """段级 amn 括号体量在场 → planeSize 照落（首个命中段取值）。"""
    fp = _tc_trans_fp()
    fp["ss"] = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                 "at": "2026-10-05 16:05", "amn": "空客320N(中)"},
                {"fn": "MU5700", "dt": "2026-10-05 18:20",
                 "at": "2026-10-05 21:30"}]
    rows = TongchengCrawler._extract_transfer_flights(_tc_fps_text(fp), "")
    assert rows and rows[0].get("planeSize") == "中型机", rows[0]


# ---- tuniu：8 键 ----

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


def test_tuniu_direct_eight_keys_absent():
    """直飞行（当日达）：8 键全部不落（offer 层到行层透传键同族
    收口）。"""
    from crawlers.tuniu import TuniuCrawler
    offers = TuniuCrawler._parse_offers(_tuniu_raw(), logger=_LOG)
    assert offers, "样本应产出至少一 offer"
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows, "样本应产出至少一行"
    for k in TUNIU_KEYS:
        assert k not in rows[0], (k, sorted(rows[0]))


def test_tuniu_cross_day_desc_still_landed():
    """跨天标识有值照落（+1天），当日达不落——辨识信息保留律。"""
    from crawlers.tuniu import TuniuCrawler
    offers = TuniuCrawler._parse_offers(_tuniu_raw(), logger=_LOG)
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and "crossDayDesc" not in rows[0]
    offers2 = TuniuCrawler._parse_offers(
        _tuniu_raw(arrivalDate="2026-10-07"), logger=_LOG)
    rows2 = TuniuCrawler._offers_to_flights(offers2)
    assert rows2 and rows2[0].get("crossDayDesc") == "+1天", rows2


def test_tuniu_transfer_still_landed():
    """中转行 transCity=「中转」照落（行层 is_transfer=航班号串含
    逗号；_parse_offers 只跳连字符多段 offer——明细首段口径守卫）。"""
    from crawlers.tuniu import TuniuCrawler
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw(flight_nos="MU8370,9C8946"), logger=_LOG)
    assert offers, "中转样本应产出至少一 offer"
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and rows[0].get("transCity") == "中转", rows


# ---- fliggy：2 键 ----

def test_fliggy_direct_two_keys_absent():
    """直飞当日卡：transCity/crossDayDesc 不落（跨天/中转覆写路径
    有值照落，既有 test_fliggy_crossday_parse 断言兼容）。"""
    txt = ("东航MU8369\n\n中型机 737\n\n19:55\n\n23:30\n\n"
           "浦东T1\n\n乌鲁木齐\n\n86%\n\n¥2522 5.4折\n1张\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 1
    for k in FLIGGY_KEYS:
        assert k not in fs[0], (k, sorted(fs[0]))


# ---- alerter 直查点防回归（收口键缺席不再 KeyError） ----

def test_alerter_direct_index_reads_retired():
    """alerter 行虽经 normalize，但 normalize 缺起降时刻的早退路径
    不写 crossDayDesc（flightnorm 早退分支）+ r241 爬虫侧无值不落，
    直查下标在键缺席行上会 KeyError：四处读点改 .get 形态后源码
    零直查残留（best_direct/best_transfer/cheapest 三受体）。"""
    import core.alerter as _a
    src = open(_a.__file__, encoding="utf-8").read()
    for frag in ('best_direct["crossDayDesc"]',
                 'best_transfer["crossDayDesc"]',
                 'best_transfer["transCity"]',
                 'cheapest["crossDayDesc"]'):
        assert frag not in src, frag


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
