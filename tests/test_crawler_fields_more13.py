# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v15123_fields.py
- tests/test_v1559_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from core.alerter import Alerter
from core.flightnorm import cabin_clean, cabin_text
from crawlers.base import iata3
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_v15123_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15123")
_CT = CtripCrawler({}, _LOG)


def _ctrip_one(item):
    rows = CtripCrawler._extract_ctrip_flights(_CT, json.dumps([item]))
    assert rows
    return rows[0]


def _ctrip_seg(dd="2026-10-06 16:40:00", ad="2026-10-06 21:30:00",
               flgno="MU5633"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _policy(price=2410, qty=5, nt3=None):
    """政策 fixture：classinfor 单元素（直飞 1 段==1 元素，全元素
    扫描结构门成立），nt3=词表串（notecnt 原样，逗号形态同 dump）。"""
    ci = {"cgrd": 0}
    if nt3:
        ci["classNoteList"] = [{"notetype": 3, "notecnt": nt3}]
    return {"tprice": price, "quantity": qty, "drate": 5.2,
            "classinfor": [ci]}


# ---- ctrip riskPolicy 第二源：nt=3 HighRisk 旗标 ----

def test_ctrip_riskpolicy_nt3_flag_lands():
    """最低价政策带 nt=3 HighRisk 旗标且 nt=104 空转：riskPolicy=
    「高风险政策」——词面复用零新键，第二源补齐 nt=104 载体缺席行。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="HighRisk")]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_nt3_comma_form_lands():
    """逗号串形态（dump 实证「SplicingNfd,PremiumEcoProduct」同族
    载体）同落：split 归一后词表成员判定。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="SplicingNfd,HighRisk")]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_nt3_nonbest_policy_not_set():
    """旗标挂非最低价政策：不落——配对门唯一判据（最低价未必是
    高风险价，挂行级即误导，nt=104 价门同律）。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(price=2410),
                                   _policy(price=3600, nt3="HighRisk")]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_nt104_precedence_word_stable():
    """双源同价在场：词面恒「高风险政策」单值（riskPolicy 是字符串
    出口，双源同词面无重复拼接面）。"""
    import base64
    import zstandard
    payload = {"items": {"priceInfoList": json.dumps([
        {"aggSalePrice": 2410.0, "engineFareCode": "", "flags": ["PHISHING"],
         "grade": "Y", "limitTag": "HighRiskPolicy", "policyId": "p1",
         "price": 2410.0, "priceType": "normal"}])}}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="HighRisk")],
                    "notes": [{"notetype": 104,
                               "notecnt": base64.b64encode(blob).decode()}]})
    assert r.get("riskPolicy") == "高风险政策"


# ---- ctrip labels「超级经济舱」：nt=3 PremiumEcoProduct ----

def test_ctrip_premeco_label_lands():
    """最低价政策带 PremiumEcoProduct：labels 收「超级经济舱」——
    S 舱+座椅倾斜 100°+深折扣的档位语义，既有出口零承载。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="SplicingNfd,"
                                           "PremiumEcoProduct")]})
    assert "超级经济舱" in (r.get("labels") or "").split("·")


def test_ctrip_premeco_nonbest_policy_not_labeled():
    """旗标挂非最低价政策：不落——超级经济舱标签随最低价政策配对，
    行价不是超经产品价时挂行级即误导。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(price=2410),
                                   _policy(price=3190,
                                           nt3="PremiumEcoProduct")]})
    assert "超级经济舱" not in (r.get("labels") or "").split("·")


# ---- qunar PC cabin 撤伪：binfo1.cabin 不落（H5 cabinDegree 同案） ----

def _pc_sample(binfo_extra=None, top=None):
    b1 = {"airCode": "FM9223", "shortName": "上航", "shortCarrier": "FM",
          "depTime": "19:55", "arrTime": "01:25",
          "date": "2026-10-04", "arrDate": "2026-10-05"}
    if binfo_extra:
        b1.update(binfo_extra)
    row = {"code": "FM9223", "minPrice": "2472", "transCity": "",
           "extparams": {}, "binfo": b1}
    row.update(top or {})
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [row]}})


def test_qunar_pc_cabin_not_landed():
    """PC binfo1.cabin（首段折扣桶/两字符漂移 'R3' 已在场）不落：
    与 H5 cabinDegree 撤伪同案——伪语义出口两侧同收。"""
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"cabin": "L"}), "2026-10-04")
    assert fl and "cabin" not in fl[0]


def test_qunar_pc_row_intact_after_cabin_removal():
    """撤伪不伤邻键：同舱位行的折扣词面照常落（信息由 discount
    承载，cabin 键冗余既判）。"""
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"cabin": "L"}, top={"discountStr": "9折"}),
        "2026-10-04")
    # 折扣词面有值照落（无值不落键缺席语义，r239 空串落键收口）
    assert fl and fl[0].get("discount") == "9折"


# ---- cabin_clean 复合高档词：查纯域词族子串化 ----

def test_cabin_clean_compound_high_word_guarded():
    """「豪华公务舱」含高档词族子串：价格硬证（price<bizPrice）成立
    即清污——等值匹配对复合高档词留缺口。"""
    assert cabin_clean({"cabin": "豪华公务舱", "price": 1000,
                        "bizPrice": 3000}) == ""


def test_cabin_clean_compound_high_word_kept_with_evidence():
    """price>=bizPrice（真高档选中）：复合词照常保留。"""
    assert cabin_clean({"cabin": "豪华公务舱", "price": 3000,
                        "bizPrice": 3000}) == "豪华公务舱"


def test_cabin_clean_super_economy_unaffected():
    """「超级经济舱」不含高档词子串：不受守卫影响（既有钉保持）。"""
    assert cabin_clean({"cabin": "超级经济舱", "price": 1000,
                        "bizPrice": 3000}) == "超级经济舱"


# ---- cabin_text cabinName 分支接守卫（上轮 P2-3） ----

def test_cabin_text_cabinname_high_word_guarded():
    """cabinName 高档词 × price<bizPrice：清污不进描述串——与 cabin
    分支同门，未来渠道直出高档 cabinName 不得绕过价格硬证。"""
    assert cabin_text({"cabinName": "头等舱", "price": 1000,
                       "bizPrice": 3000}) == ""


def test_cabin_text_cabinname_without_bizprice_kept():
    """无 bizPrice 不可内证：维持原值（与 cabin 分支口径一致）。"""
    assert cabin_text({"cabinName": "头等舱"}) == "头等舱"


def test_cabin_text_cabinname_economy_kept():
    """经济舱词面照常透传（既有钉保持）。"""
    assert cabin_text({"cabinName": "经济舱", "price": 1000,
                       "bizPrice": 3000}) == "经济舱"


# ---- fliggy._via 存储层脏键收口（r223 观测 P2-1，qunar._via 同族） ----

def test_fliggy_stopover_direct_lands_without_via():
    """经停语义直落 stopover，_via 内部哨兵不再入库——机型行「共享|
    经停|」形态（dump 实证）经 _parse_pc_text 后行内应有 stopover=True
    且无 _via 键（normalize 同判幂等：bool(stopover) 短路结果不变，
    DB raw schema 净化，qunar DOM 路径同族先例）。"""
    from crawlers.fliggy import FliggyCrawler
    rows = FliggyCrawler._parse_pc_text(
        "\n".join(["东航MU5137", "中型机 737 共享|经停|", "08:00", "11:30",
                   "虹桥国际机场T1", "浦东国际机场T2", "¥2320"]),
        "2026-10-05")
    assert rows and rows[0].get("stopover") is True
    assert "_via" not in rows[0]


# ---- qunar|cabin 哨兵退役（r223 观测 P2-2：键故意退场非站点改版） ----

def test_field_sentinel_qunar_cabin_retired_no_false_fire(monkeypatch, tmp_path):
    """qunar 60 行 cabin 全灭（撤伪后新轮常态）不告警：cabin 入结构性
    死键表（H5 cabinDegree 与 PC binfo1.cabin 两路撤伪定谳，跨源同一
    伪语义出口）——「站点改版键名失效」语义不再适用，观测即天天假火
    （表成员语义=skip，main._SENT_DEAD_KEYS 消费点）。share/few/term
    等白名单字段的伴生告警不在本钉范围，只钉 cabin 静默。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    # plane/discount 非死键、比率观测，带命中值防伴生假火干扰判读
    rows = [{"price": 1000, "cabin": "", "meal": "", "prate": "",
             "plane": "波音737", "discount": "4.5折"} for _ in range(60)]
    _m._field_sentinel(
        [_NS(platform="qunar", extra=json.dumps(rows))], _L())
    assert not any("cabin" in " ".join(map(str, a)) for a in seen), seen


# ---- merged from tests/test_v1559_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t1559")
_CT = CtripCrawler({}, _LOG)


# ---- iata3 守卫（三源同律） ----

def test_iata3_guard():
    assert iata3("URC") == "URC"
    assert iata3(" SHA ") == "SHA"     # 首尾空白容忍
    assert iata3("") == ""
    assert iata3(None) == ""
    assert iata3("urc") == ""          # 小写挡
    assert iata3("URCS") == ""         # 超长挡
    assert iata3("UR") == ""           # 不足挡
    assert iata3(123) == ""            # 数字内部 id 形态挡（挂起期担忧）
    assert iata3("乌鲁木齐") == ""      # 中文挡


# ---- qunar H5：binfo/binfo1.depAirportId + binfo2.arrAirportId ----

def _h5_direct(**binfo):
    f = {"minPrice": 1200, "code": "9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_iata_direct():
    """直飞行 binfo.depAirportId/arrAirportId（调研 138/138）→ 码键。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(depAirportId="URC", arrAirportId="SHA")])
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "SHA"


def test_qunar_h5_iata_transfer_arr_binfo2_only():
    """中转行 dep 取 binfo1.depAirportId（首段出发=整体出发）、arr 只认
    binfo2.arrAirportId（整体到达）——binfo1.arrAirportId 是首段中转场
    码（陷阱键， 在案），混入即脏。"""
    f = {"minPrice": 800, "code": "GS7587", "transCity": "石家庄",
         "crossDayDesc": "+1天",
         "binfo1": {"depTime": "14:30", "arrTime": "00:20",
                    "depDate": "2026-10-06", "arrDate": "2026-10-07",
                    "depAirportId": "URC",
                    "arrAirportId": "CGO",   # 陷阱：首段中转场码
                    "transInfo": {"transCity": "石家庄",
                                  "transTime": "5h45m",
                                  "firstArrInfo": {"airport": "正定",
                                                   "terminal": "T2"},
                                  "secondDepInfo": {"airport": "正定",
                                                    "terminal": "T5",
                                                    "time": "06:05"},
                                  "secondArrInfo": {"airport": "虹桥",
                                                    "terminal": "T1",
                                                    "time": "07:55"}}},
         "binfo2": {"depTime": "06:05", "arrTime": "07:55",
                    "arrAirportId": "SHA"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "SHA"
    assert rows[0]["arrAirportCode"] != "CGO"


def test_qunar_h5_iata_guard_dirty():
    """脏形态（小写/数字 id/缺键）→ 空串（str 空串口径同邻键）。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(depAirportId="urc", arrAirportId=1234)])
    assert rows[0]["depAirportCode"] == ""
    assert rows[0]["arrAirportCode"] == ""


# ---- qunar PC：复活预案搭车（binfo1.depAirportCode/arrAirportCode） ----

_PC = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223", "minPrice": "2472", "transCity": "",
         "extparams": {},
         "binfo1": {"airCode": "FM9223", "shortName": "上航",
                    "depTime": "19:55", "arrTime": "01:25",
                    "date": "2026-10-04", "arrDate": "2026-10-05",
                    "flightTime": "5h30m",
                    "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
                    "depAirportCode": "URC", "arrAirportCode": "SHA"}}]}})


def test_qunar_pc_iata_rider():
    """PC 键名 depAirportCode/arrAirportCode 与 H5 出口天然对齐；软拒
    期间零产出，随复活预案生效。"""
    fl = QunarCrawler._parse_pc_flights(_PC, "2026-10-04")
    assert fl[0]["depAirportCode"] == "URC"
    assert fl[0]["arrAirportCode"] == "SHA"


# ---- tuniu：detail.dPortIataCode/aPortIataCode ----

_T_FLIGHT = {
    "MU8370#2026-10-06#URC#SHA": {
        "airlineCompany": "东航",
        "departureTime": "20:20", "arrivalTime": "01:15",
        "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
        "flightTime": "295",
        "dPortName": "天山机场", "aPortName": "浦东机场",
        "dPortIataCode": "URC", "aPortIataCode": "SHA",
    },
}

_T_FARE = {
    "flightOptions": [{"flightNos": "MU8370"}],
    "flightPriceList": [
        {"fareBreakdownList": [
            {"baseFare": 3600, "discount": "7.7折", "psgType": "ADT"}],
         "priceJourneyCabinList": [
             {"priceFlightCabinList": [
                 {"cabinClass": "Y", "cabinCode": "M",
                  "cabinTypeName": "经济舱"}]}]}],
}


def test_tuniu_iata_end_to_end():
    """offer 层采集 + offers_to_flights 透传（决策字段必须随 offer
    透传教训 / 两次在案）。"""
    offers = TuniuCrawler._parse_offers(
        {"data": {"fareList": [_T_FARE], "flightList": _T_FLIGHT}})
    assert offers[0]["depAirportCode"] == "URC"
    assert offers[0]["arrAirportCode"] == "SHA"
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "SHA"


def test_tuniu_iata_guard_dirty():
    """脏形态与城市码键（dCityIataCode 同串不同义）不混入 Port 键。"""
    fl = json.loads(json.dumps(_T_FLIGHT))
    d = fl["MU8370#2026-10-06#URC#SHA"]
    d["dPortIataCode"] = "urc"
    d["aPortIataCode"] = ""
    d["dCityIataCode"] = "URC"      # 城市码键：SHA 机场/城市双义警告在案
    offers = TuniuCrawler._parse_offers(
        {"data": {"fareList": [_T_FARE], "flightList": fl}})
    assert offers[0]["depAirportCode"] == ""
    assert offers[0]["arrAirportCode"] == ""


# ---- ctrip：AIRPORT_NAME_CN 归一前原码第三源 ----

def _ctrip_item(aport_dep="URC", aport_arr="SHA"):
    seg = {"dateinfo": {"ddate": "2026-10-06 16:40:00",
                        "adate": "2026-10-06 21:30:00"},
           "basinfo": {"flgno": "CZ6981"},
           "dportinfo": {"bsname": "", "aport": aport_dep},
           "aportinfo": {"bsname": "T2", "aport": aport_arr}}
    return {"mutilstn": [seg],
            "policyinfo": [{"tprice": 1200, "quantity": 5, "drate": 5.2}]}


def test_ctrip_iata_raw_code():
    r = _CT._extract_ctrip_flights(json.dumps([_ctrip_item()]))[0]
    assert r["depAirportCode"] == "URC"
    assert r["arrAirportCode"] == "SHA"


def test_ctrip_iata_guard_dirty_name_key_passthrough():
    """码键守卫挡小写；中文名键维持既有「未收录保留码」透传不动
    （两键口径刻意不同：码键机器可读必须净，名键渲染端已有兜底）。"""
    r = _CT._extract_ctrip_flights(
        json.dumps([_ctrip_item(aport_dep="urc")]))[0]
    assert r["depAirportCode"] == ""
    assert r["depAirport"] == "urc"


# ---- fliggy：_RECHECK_JS 选择器必修钉子 ----

def test_fliggy_recheck_selector_reads_inner_attribute():
    """必修：data-content 挂内层 div.body.J_Content，选择器必须
    下钻到 dd.transfer_note [data-content]——首版读 dd 自身恒 null，
    自上线零生效（单测注入文本覆盖不到 JS 采集侧，此钉防选择器回退）。"""
    js = FliggyCrawler._RECHECK_JS
    assert "dd.transfer_note [data-content]" in js
    assert "querySelector('dd.transfer_note')" not in js
    # 页面 2 个同构图例 dd：首个非空语义（循环取值）必须在场
    assert "for (const el of els)" in js


# ---- _propagate_fields：码键物理属性跨渠道互补 ----

def test_propagate_iata_codes_fill_missing():
    base = {"code": "MU8370", "depDate": "2026-10-06",
            "depTime": "20:20", "arrTime": "01:15",
            "arrDate": "2026-10-07"}
    a = dict(base, platform="ctrip", price=1200,
             depAirportCode="URC", arrAirportCode="SHA")
    b = dict(base, platform="tuniu", price=1250)
    Alerter._propagate_fields([a, b])
    assert b["depAirportCode"] == "URC"
    assert b["arrAirportCode"] == "SHA"


def test_propagate_iata_codes_conflict_no_fill():
    """码值冲突（不该发生，防御性）：不补不覆盖（vals!=1 语义）。"""
    base = {"code": "MU8370", "depDate": "2026-10-06",
            "depTime": "20:20", "arrTime": "01:15",
            "arrDate": "2026-10-07"}
    a = dict(base, platform="ctrip", price=1200, depAirportCode="URC")
    b = dict(base, platform="tuniu", price=1250, depAirportCode="XIY")
    Alerter._propagate_fields([a, b])
    assert a["depAirportCode"] == "URC"
    assert b["depAirportCode"] == "XIY"
