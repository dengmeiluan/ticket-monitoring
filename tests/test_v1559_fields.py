# -*- coding: utf-8 -*-
"""渠道字段第十一批回归：H1 机场 IATA 码三源接入（qunar H5
binfo/binfo1.depAirportId + binfo2.arrAirportId、tuniu detail.dPort/
aPortIataCode、ctrip 归一前原码第三源，iata3 ^[A-Z]{3}$ 守卫）+
fliggy _RECHECK_JS 选择器必修（data-content 实际挂内层 div.body.
J_Content，首版读 dd 自身恒 null 自上线零生效）+
_propagate_fields 码键入列（物理属性跨渠道互补）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1559_fields.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import iata3  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from core.alerter import Alerter  # noqa: E402

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
