# -*- coding: utf-8 -*-
"""渠道字段第六批回归：labels 层级修复 / tuniu 透传漏键 /
机场级定位三渠道 / 机型体量 planeSize 四渠道 / qunar PC 复活预案 /
同程共享双守卫 / ctrip 行李三态 / 恰达线剥注。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1554_fields.py
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from webui import _cluster_round_rows  # noqa: E402
from core.notifier import _alert_body  # noqa: E402


# ---- qunar H5 labels 层级修复（背书真值在 binfo 层，顶层恒占位） ----

def test_qunar_h5_labels_binfo_notice_takes_priority():
    f = {"transNotice": "转",
         "listLabel": {"priceBottomLabels": [{"text": "出票后2小时内错购退票"}]}}
    info = {"transNotice": "华夏联程"}
    out = QunarCrawler._h5_labels_of(f, info)
    assert "华夏联程" in out
    assert "出票后2小时内错购退票" in out


def test_qunar_h5_labels_placeholder_ting_excluded():
    # 「停」（经停标记，与 stopFlight 冗余）与「转」同为占位不落
    f = {"transNotice": "停"}
    assert QunarCrawler._h5_labels_of(f, {"transNotice": "停"}) == ""


def test_qunar_h5_labels_top_level_fallback():
    # binfo 层无 transNotice 时顶层兜底（旧链路兼容）
    f = {"transNotice": "华夏联程"}
    assert QunarCrawler._h5_labels_of(f, {}) == "华夏联程"


# ---- qunar H5 中转行 arrTerminal 语义修正 + transDepTerminal ----

_H5_TRANS = {
    "code": "GS7587", "price": 800, "minPrice": 800,
    "crossDayDesc": "+1天", "transCity": "石家庄", "transTime": "17时25分",
    "binfo1": {"depTime": "14:30", "arrTime": "00:20",
               "depDate": "2026-10-06", "arrDate": "2026-10-07",
               "codeShare": False,
               "depTerminal": "", "arrTerminal": "T2",
               "transInfo": {
                   "transCity": "石家庄", "transTime": "5h45m",
                   "firstArrInfo": {"airport": "正定", "terminal": "T2"},
                   "secondDepInfo": {"airport": "正定", "terminal": "T2",
                                     "time": "06:05"},
                   "secondArrInfo": {"airport": "虹桥", "terminal": "T1",
                                     "time": "07:55"}}},
}


def test_qunar_h5_transfer_arr_terminal_whole_journey():
    # binfo1.arrTerminal=T2（中转楼）须被 secondArrInfo.terminal=T1（整体
    # 到达楼）覆盖——与 arrTime 的整体口径对齐（漏网键）
    raw = json.dumps({"ret": True, "data": json.dumps(
        {"flights": [_H5_TRANS]})}
    )
    fl = QunarCrawler._parse_response_flights(raw)
    assert len(fl) == 1
    assert fl[0]["arrTerminal"] == "T1"
    assert fl[0]["arrAirport"] == "虹桥"


def test_qunar_h5_trans_dep_terminal_same_building_not_set():
    # secondDepInfo 与 firstArrInfo 同楼=无换乘增量，不落（宁缺勿错）
    raw = json.dumps({"ret": True, "data": json.dumps(
        {"flights": [_H5_TRANS]})}
    )
    fl = QunarCrawler._parse_response_flights(raw)
    assert fl[0]["transDepTerminal"] == ""


def test_qunar_h5_trans_dep_terminal_diff_building():
    h = json.loads(json.dumps(_H5_TRANS))
    h["binfo1"]["transInfo"]["secondDepInfo"]["terminal"] = "T5"
    raw = json.dumps({"ret": True, "data": json.dumps({"flights": [h]})})
    fl = QunarCrawler._parse_response_flights(raw)
    assert fl[0]["transDepTerminal"] == "正定T5"


# ---- qunar PC 复活预案（报文键在场而解析器未读的补读） ----

_PC_SAMPLE = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223", "minPrice": "2472", "transCity": "",
         "extparams": {"childPrice": 0, "infantPrice": None,
                       "refundChangeRule": '{"returnFee":0,"changeFee":0}'},
         "binfo": {"airCode": "FM9223", "shortName": "上航",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-10-04", "arrDate": "2026-10-05",
                   "flightTime": "5h30m",
                   "depTerminal": "", "arrTerminal": "T2",
                   "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
                   "planeFullType": "空客330(大)",
                   "piaoShao": True, "piaoShaoDesc": "票少",
                   "codeShare": True, "mainCarrier": "FM9224",
                   "pTrip": True, "pTripNote": "航变免费改、20Kg免费行李"}},
    ]}})


def test_qunar_pc_terminal_and_airport_keys():
    fl = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-10-04")
    f = fl[0]
    assert f["depTerminal"] == ""          # 出发侧空串如实留空
    assert f["arrTerminal"] == "T2"
    assert f["depAirport"] == "乌鲁木齐天山"
    assert f["arrAirport"] == "虹桥机场"


def test_qunar_pc_plane_size_and_sources():
    fl = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-10-04")
    f = fl[0]
    assert f["planeSize"] == "大型机"        # 「空客330(大)」括号体量
    assert f["fewTicket"] == "票少"          # piaoShaoDesc 真键换源
    assert f["shareCarrier"] == "FM9224"     # mainCarrier 真键换源
    assert f["ptripNote"] == "航变免费改、20Kg免费行李"
    assert f["refundChange"] == '{"returnFee":0,"changeFee":0}'
    assert "childPrice" not in f             # 0=未报价占位不落


def test_qunar_pc_plane_size_placeholder_not_set():
    # 「机型未定/其他机型/737-800」无体量形态不落（宁缺勿错）
    s = json.loads(_PC_SAMPLE)
    s["data"]["flights"][0]["binfo"]["planeFullType"] = "机型未定"
    fl = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl[0]["planeSize"] == ""


def test_qunar_pc_share_carrier_self_flight_guard():
    # 自飞防呆：mainCarrier 与本班 airCode 完全同号不落；
    # 同航司不同号（FM9223 营销/FM9224 执飞）是真共享保留
    s = json.loads(_PC_SAMPLE)
    b = s["data"]["flights"][0]["binfo"]
    b["airCode"] = "FM9223"
    b["mainCarrier"] = "FM9223"
    fl = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl[0]["shareCarrier"] == ""
    b["mainCarrier"] = "FM9224"
    fl2 = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl2[0]["shareCarrier"] == "FM9224"


# ---- tuniu：labels 透传漏键修复（宽体机空转根因）+ 新键 ----

_TUINU_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [], "labels": "宽体机",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "上航",
}


def test_tuniu_labels_passthrough_fix():
    # offer 层算好 labels 但 _offers_to_flights 白名单漏带，
    # DB 实锤全库 labels 键存在率 0%（宽体机功能空转根因）
    fs = TuniuCrawler._offers_to_flights([dict(_TUINU_OFFER)])
    assert fs[0]["labels"] == "宽体机"
    assert fs[0]["planeSize"] == "大型机"
    assert fs[0]["depAirport"] == "天山机场"
    assert fs[0]["arrAirport"] == "虹桥机场"
    assert fs[0]["cabinCode"] == "D"
    assert fs[0]["shareCarrier"] == "上航"


def test_tuniu_cabin_code_multi_cabin_guard():
    # 多舱位（与最低价 ADT 无法配对）不落——ctrip 舱位配对纪律先例
    fare = {"flightPriceList": [{"priceJourneyCabinList": [
        {"priceFlightCabinList": [{"cabinCode": "Y"}, {"cabinCode": "B"}]}]}]}
    assert TuniuCrawler._cabin_code(fare) == ""
    fare1 = {"flightPriceList": [{"priceJourneyCabinList": [
        {"priceFlightCabinList": [{"cabinCode": "M"}]}]}]}
    assert TuniuCrawler._cabin_code(fare1) == "M"


# ---- tongcheng：机场简称 / clct 白名单 / 共享双守卫 / afn 体量 ----

def _tc_flight(**over):
    f = {"fn": "GS7587", "dt": "2026-10-06 09:30:00",
         "at": "2026-10-06 14:05:00", "asn": "天津", "td": "4h35m",
         "afn": "空客320(中)", "dasn": "天山", "aasn": "虹桥",
         "dat": "", "aat": "T2", "icsf": True, "sfd": "flightId_CZ6993",
         "lps": [{"atp": "800", "brs": [{"al": 9}],
                  "pts": [{"td": "6.8折经济舱"}],
                  "clct": [{"tt": 1, "td": "大机型"},
                           {"tt": 2, "td": "到达准点率97%"},
                           {"tt": 3, "td": "座椅较宽"}]}]}
    f.update(over)
    return json.dumps({"success": True, "data": {"fl": [f]}})


def test_tongcheng_airport_and_labels():
    fs = TongchengCrawler._extract_flights(_tc_flight())
    f = fs[0]
    assert f["depAirport"] == "天山"
    assert f["arrAirport"] == "虹桥"
    assert f["labels"] == "大机型·座椅较宽"    # tt=2 准点率冗余不采
    assert f["planeSize"] == "中型机"           # afn 括号体量
    assert f["plane"] == "空客320"              # 原有清洗不受影响


def test_tongcheng_share_carrier_double_guard():
    # icsf=True 且 sfd 非自飞同号才落（剥 flightId_ 前缀）
    fs = TongchengCrawler._extract_flights(_tc_flight())
    assert fs[0]["shareCarrier"] == "CZ6993"
    # icsf=False 但 sfd 有值=假值不落（dump 实证 27 行）
    fs2 = TongchengCrawler._extract_flights(_tc_flight(icsf=False))
    assert fs2[0]["shareCarrier"] == ""
    # 自飞挂自身 id（完全同号 GS7587→GS7587）不落
    fs3 = TongchengCrawler._extract_flights(_tc_flight(fn="CZ6993",
                                                       sfd="flightId_CZ6993"))
    assert fs3[0]["shareCarrier"] == ""
    # 同航司不同号是真共享勿误杀（fn=CZ6993 营销 → CZ6990 执飞）
    fs4 = TongchengCrawler._extract_flights(_tc_flight(fn="CZ6993",
                                                       sfd="flightId_CZ6990"))
    assert fs4[0]["shareCarrier"] == "CZ6990"


# ---- ctrip：机场三字码 + aset 层行李三态（走真实解析入口） ----

def _ctrip_item(aset_words, transfer=True):
    seg = {"basinfo": {"flgno": "GS7587" if transfer else "MU5533"},
           "dateinfo": {"ddate": "2026-10-06 09:30:00",
                        "adate": "2026-10-06 14:05:00"},
           "dportinfo": {"city": "URC", "aport": "URC", "bsname": ""},
           "aportinfo": {"city": "SHA", "aport": "SHA", "bsname": "T2"}}
    return {"mutilstn": [seg] if not transfer else [seg, dict(seg)],
            "policyinfo": [{"tprice": 800, "quantity": 5}],
            "aset": [{"tagarea": [{"tagcnt": w} for w in aset_words]}]}


def _ctrip_parse(item):
    return CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))


def test_ctrip_transfer_baggage_recheck_from_aset():
    # 「行李代转运」=明确不直挂真值（transferBaggage 第三态）
    fs = _ctrip_parse(_ctrip_item(["行李代转运"]))
    assert len(fs) == 1 and fs[0]["transCity"]
    assert fs[0]["transferBaggage"] == "recheck"


def test_ctrip_transfer_baggage_direct_from_aset():
    # 「联程值机，行李直挂」=item 层直挂第二来源（政策级无信号时生效）
    fs = _ctrip_parse(_ctrip_item(["联程值机，行李直挂"]))
    assert fs[0]["transferBaggage"] == "direct"


def test_ctrip_transfer_baggage_direct_transfer_not_set_on_direct():
    # 行李词是中转行专属信号：直飞行 is_transfer 门不落
    fs = _ctrip_parse(_ctrip_item(["行李代转运", "联程值机，行李直挂"],
                                  transfer=False))
    assert len(fs) == 1 and not fs[0]["transCity"]
    assert fs[0]["transferBaggage"] == ""


def test_ctrip_airport_codes_landed():
    # 机场三字码（dportinfo/aportinfo.aport）入门； 起经
    # AIRPORT_NAME_CN 归一为机场短名（与 qunar/tuniu 中文名同形）
    fs = _ctrip_parse(_ctrip_item([], transfer=False))
    assert fs[0]["depAirport"] == "乌鲁木齐天山"
    assert fs[0]["arrAirport"] == "虹桥"


# ---- fliggy：planeSize 行首体量词 + 机场名 ----

def test_fliggy_plane_size_and_airport_name():
    txt = ("国航CA8564\n14:30\n18:45\n虹桥国际机场T2\n大型机 789 经停\n"
           "¥960 4.5折\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert fs[0]["planeSize"] == "大型机"
    assert fs[0]["plane"] == "789"
    assert fs[0]["depAirport"] == "虹桥国际机场"
    assert fs[0]["depTerminal"] == "T2"


# ---- webui 轮聚类 600s 收口（与曲线 _rounds 同序） ----

def _row(ts):
    from datetime import datetime
    return {"fetched_at": ts}


def test_cluster_round_rows_600s_aligns_curve():
    # 契约=倒序输入（最新在前）、时间戳=DB 形态空格分隔：
    # 8 分钟断口在 600s 阈值下仍同轮（300s 旧值会把 10:08/10:00 切出
    # 「本轮」=图有列无）
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:08:00",
            "2026-09-20 10:00:00"]
    out = _cluster_round_rows([_row(t) for t in rows], gap_s=600)
    assert len(out) == 3


def test_cluster_round_rows_splits_across_rounds():
    # 真轮界（倒序 14/8 分钟断口）：只有最新轮（10:16）保留
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:02:00",
            "2026-09-20 09:54:00"]
    out = _cluster_round_rows([_row(t) for t in rows], gap_s=600)
    assert len(out) == 1
    assert out[0]["fetched_at"] == "2026-09-20 10:16:00"


# ---- notifier：恰达线剥注 + 装饰符剥离 ----

def test_alert_body_strips_broken_line_word():
    # 恰达线（diff==0 非达标）「行情破线」与 🟩 转写「行情价 」同句
    # 双词面——转写前剥注同律（推送审校）
    body = _alert_body("🎯真达标 直飞 ￥1900 线￥1900 行情破线")
    assert "行情破线" not in body


def test_alert_body_strips_decorative_emoji():
    body = _alert_body(
        "#### 📋 明细总表 实绿=真达标·描绿=破线\n\n✈️ 乌→上 走势↑ ↓\n\n💡 建议")
    for w in ("📋", "✈", "💡"):
        assert w not in body
    assert "涨" in body and "跌" in body   # 箭头转可读词


def test_notify_page_raw_conversion_complete():
    # NOTIFY_PAGE 改 raw 消 DeprecationWarning——守护「半截转换」回归
    # （源码 `\\s` 在 raw 下浏览器实收字面「反斜杠+s」，
    # 档位方块行静默跌落普通段落）
    import webui
    assert r"/\\s/g" not in webui.NOTIFY_PAGE    # 不许残留双反斜杠形态
    assert "/\\s/g" in webui.NOTIFY_PAGE         # 解码态单反斜杠（空白类）
    assert "match(/\\(" in webui.NOTIFY_PAGE     # 图片链接正则解码态 \(


def test_ptrip_note_not_orphan():
    # 爬虫落键、渲染门必须下发（防 PC 复活当日静默丢失）
    src = open("webui.py", encoding="utf-8").read()
    assert '"ptripNote"' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
