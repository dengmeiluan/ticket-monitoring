# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r241_fields.py
- tests/test_v184_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r241_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# ---- __main__ from tests/test_r241_fields.py ----

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---- merged from tests/test_v184_fields.py ----

# 生产冻结 dump 真实行（乌鲁木齐→上海 10-06 代）：transTime='9小时'
# 实为停留（b1.arr 12:20 → b2.dep 21:20），两段飞行 3h50+2h05
_PC_TRANS = json.loads(r'''{"binfo1":{"airCode":"GS7529","arrAirport":"武当山机场","arrAirportCode":"WDS","arrDate":"2026-10-06","arrTerminal":"","arrTime":"12:20","cabin":"M","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"乌鲁木齐天山","depAirportCode":"URC","depDate":"2026-10-06","depTerminal":"","depTime":"08:30","flightTime":"3小时50分钟","mealDesc":"无餐食","name":"新海航｜天津航空","planeFullType":"空客320(中)","planeType":"32C","shortCarrier":"GS","shortName":"新海航｜天津航空"},"binfo2":{"airCode":"FM9356","arrAirport":"浦东机场","arrAirportCode":"PVG","arrDate":"2026-10-06","arrTerminal":"T1","arrTime":"23:25","cabin":"L","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"武当山机场","depAirportCode":"WDS","depDate":"2026-10-06","depTerminal":"","depTime":"21:20","flightTime":"2小时5分钟","name":"上海航空","planeFullType":"波音737(中)","planeType":"73A","shortCarrier":"FM","shortName":"上航"},"minPrice":2550,"minbfPrice":0,"code":"GS7529/FM9356","flightType":"listMore","crossDayDesc":"","transCity":"十堰","transTime":"9小时","discountStr":"6.3折","priceLabel":[]}''')

# 跨天停留形态：transTime='1天55分钟'（b1.arr 21:55 → 次日 b2.dep
# 22:50，真停 24h55m）；span(b1.date→b2.arrDate)=2 天触发回绕存疑
# 守卫→停留不取、全程留空由 normalize 按起止时刻重算兜底
_PC_TRANS_WRAP = json.loads(r'''{"binfo1":{"airCode":"Y87570","arrAirport":"新郑机场","arrAirportCode":"CGO","arrDate":"2026-10-06","arrTerminal":"T2","arrTime":"21:55","cabin":"L","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"乌鲁木齐天山","depAirportCode":"URC","depDate":"2026-10-06","depTerminal":"","depTime":"17:55","flightTime":"4小时0分钟","mealDesc":"无餐食","name":"新海航｜金鹏航空","planeFullType":"737-800","planeType":"738","shortCarrier":"Y8","shortName":"新海航｜金鹏航空"},"binfo2":{"airCode":"Y87520","arrAirport":"浦东机场","arrAirportCode":"PVG","arrDate":"2026-10-08","arrTerminal":"T2","arrTime":"00:40","cabin":"L","codeShare":false,"crossDay":1,"crossDayDesc":"+1天","date":"2026-10-07","depAirport":"新郑机场","depAirportCode":"CGO","depDate":"2026-10-07","depTerminal":"T2","depTime":"22:50","flightTime":"1小时50分钟","name":"新海航｜金鹏航空","planeFullType":"737-800","planeType":"738","shortCarrier":"Y8","shortName":"新海航｜金鹏航空"},"minPrice":2700,"minbfPrice":0,"code":"Y87570/Y87520","flightType":"listMore","crossDayDesc":"+2天","transCity":"郑州","transTime":"1天55分钟","discountStr":"6.3折","priceLabel":[{"id":667,"name":"郑州机场中转权益","note":[]}],"transitServiceLabelName":"中转优享","transitServiceLabel":"中转优享：本服务包含免费休息区服务"}''')

# 直飞行（真实形态）：transTime=int 0，时长真值在 binfo.flightTime
_PC_DIRECT = {
    "binfo1": {"airCode": "9C6496", "arrTime": "21:30", "arrDate": "2026-10-06",
               "date": "2026-10-06", "depTime": "16:40", "flightTime": "4h35m",
               "name": "春秋航空", "shortName": "春秋航空"},
    "code": "9C6496", "crossDayDesc": "", "minPrice": 620,
    "transTime": 0,
}


def _one(raw):
    env = {"ret": True, "data": {"flights": [raw]}}
    fl = QunarCrawler._parse_pc_flights(json.dumps(env), "2026-10-06")
    assert fl, "夹具行被解析器整行丢弃（夹具结构与真实报文不符）"
    return fl[0]


class TestQunarPcTransferDuration:
    """中转行 totalDuration/layover 双字段源头重建。"""

    def test_transfer_totalduration_is_journey(self):
        f = _one(_PC_TRANS)
        # 全程=3h50 + 停9h + 2h05 = 14时55分（停留词面「9小时」不再冒充全程）
        assert f["totalDuration"] == "14时55分", \
            f"中转 totalDuration 仍落停留词面: {f['totalDuration']!r}"

    def test_transfer_layover_is_true_gap(self):
        f = _one(_PC_TRANS)
        # 停留权威=两段起降差 9h=540（一级公式曾误算 540−230−125=185）
        assert f["layover"] == 540, \
            f"中转 layover 偏离起降差真值: {f['layover']!r}"

    def test_transfer_wrap_longstay_pinned(self):
        f = _one(_PC_TRANS_WRAP)
        # r273 日期钉：真停 24h55m 不再被 span≥2 回绕守卫丢弃——
        # 二段起飞日(binfo2.date=10-07)相对首段到达日(binfo1.arrDate=
        # 10-06) 钉天数百位，layover=1440+55=1495 与渠道 transTime
        # 「1天55分钟」逐分一致（第三方信号互证）；全程随之重建
        # 4h+24h55m+1h50m=30时45分（normalize 起止重算 2*1440+00:40
        # −17:55=1845 同值自洽）
        assert f["layover"] == 1495, f"真停应按日期钉恢复: {f.get('layover')!r}"
        assert f["totalDuration"] == "30时45分"
        from core.flightnorm import normalize
        _t = normalize(dict(f), "2026-10-06")
        assert _t["layoverM"] == 1495 and _t["layoverT"] == "24:55", _t
        assert _t["durM"] == 1845

    def test_transfer_normalize_integration(self):
        from core.flightnorm import normalize
        f = normalize(_one(_PC_TRANS), "2026-10-06")
        assert f["totalDuration"] == "14时55分"
        assert f["durM"] == 895
        assert f["layoverM"] == 540
        assert f["layoverT"] == "9:00"

    def test_transfer_missing_segment_degrades(self):
        import copy
        row = copy.deepcopy(json.loads(json.dumps(_PC_TRANS)))
        row["binfo2"]["flightTime"] = ""
        f = _one(row)
        # 两段飞行缺一→重建不可为→留空（normalize 重算兜底），
        # 停留仍由起降差权威给出；全程无值不落键（r239 收口）
        assert "totalDuration" not in f
        assert f["layover"] == 540

    def test_direct_duration_unchanged(self):
        f = _one(_PC_DIRECT)
        assert f["totalDuration"] == "4时35分"
