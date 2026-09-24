# -*- coding: utf-8 -*-
"""渠道字段第七批回归：qunar H5 机场级定位漏读修复（depAirport
/arrAirport/totalDuration）/ 经停 transInfo 换源 / bizPrice 公务舱价 /
ctrip planeSize craftinfo.kind + cabinCode nt=2 + 机场码归一 /
tongcheng amt 换源 + 中转行机场体量 + sts 四键 + wifi 并 labels /
flightnorm lcc 派生 + stopTime「N时」形态 / 哨兵第七批扩容。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1555_fields.py
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from core.flightnorm import (normalize, AIRPORT_NAME_CN,  # noqa: E402
                             AIRLINE_LCC, _is_lcc)

_LOG = logging.getLogger("t1555")
_CT = CtripCrawler({}, _LOG)


# ---- qunar H5：机场级定位漏读修复 ----

def _h5_direct(**binfo):
    f = {"minPrice": 1200, "code": "9C8846", "mixFlightName": "春秋9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_dep_airport_direct():
    """直飞行 binfo.depAirport/arrAirport 全量在场而解析器从未读
    （DB depAirport 11.6% 全来自 PC 行的根因）。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(depAirport="乌鲁木齐天山", arrAirport="虹桥")])
    assert rows[0]["depAirport"] == "乌鲁木齐天山"
    assert rows[0]["arrAirport"] == "虹桥"


def test_qunar_h5_transfer_dep_and_secondarr_priority():
    """中转行 depAirport=binfo1 层；arrAirport secondArrInfo（中文
    「虹桥」）优先——binfo1.arrAirport 是三字码「SHA」宁缺不落码。"""
    f = {"minPrice": 1500, "code": "GS7581/9C6402", "transCity": "西安",
         "binfo1": {"depTime": "06:30", "arrTime": "15:15",
                    "depDate": "2026-10-06", "arrDate": "2026-10-06",
                    "depAirport": "乌鲁木齐天山", "arrAirport": "SHA",
                    "transInfo": {"firstArrInfo": {"terminal": "T3"},
                                  "secondArrInfo": {"airport": "虹桥",
                                                    "terminal": "T1"}}},
         "binfo2": {"depTime": "13:00"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["depAirport"] == "乌鲁木齐天山"
    assert rows[0]["arrAirport"] == "虹桥"


def test_qunar_h5_transfer_no_secondarr_no_fallback():
    """中转行缺 secondArrInfo 时 arrAirport 留空（不回退三字码）。"""
    f = {"minPrice": 1500, "code": "GS7581/9C6402", "transCity": "西安",
         "binfo1": {"depTime": "06:30", "arrTime": "15:15",
                    "depDate": "2026-10-06", "arrDate": "2026-10-07",
                    "depAirport": "乌鲁木齐天山", "arrAirport": "SHA"},
         "binfo2": {"depTime": "13:00"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["depAirport"] == "乌鲁木齐天山"
    assert rows[0]["arrAirport"] == ""


def test_qunar_h5_totalduration_direct_fallback():
    """直飞行全程时长在 binfo.totalDuration（f.transTime 仅中转行有）。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(totalDuration="4时50分")])
    assert rows[0]["totalDuration"] == "4时50分"
    # 中转行 f.transTime 优先（原有行为不回退）
    f = {"minPrice": 1500, "code": "GS7581/9C6402", "transCity": "西安",
         "transTime": "8h45m",
         "binfo1": {"depTime": "06:30", "arrTime": "15:15",
                    "depDate": "2026-10-06", "arrDate": "2026-10-06",
                    "totalDuration": "8h45m"},
         "binfo2": {"depTime": "13:00"}, "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["totalDuration"] == "8h45m"


def test_qunar_h5_stopover_transinfo_gate():
    """经停城市/时长换源：stopFlight=true 行采 transInfo 真值；
    普通直飞行 transInfo 空占位不落；中转行不进经停分支。"""
    f = _h5_direct(
        transInfo={"transCity": "西安", "transTime": "1小时5分"})
    f["extparams"] = json.dumps({"stopFlight": True})
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["stopCitys"] == "西安"
    assert rows[0]["stopTime"] == "1小时5分"
    assert rows[0]["stopFlight"] is True

    f2 = _h5_direct(transInfo={"transCity": "", "transTime": ""})
    rows2 = QunarCrawler._extract_flights_obj([f2])
    assert rows2[0]["stopCitys"] == ""
    assert "stopTime" not in rows2[0]

    f3 = {"minPrice": 1500, "code": "GS7581/9C6402", "transCity": "西安",
          "binfo1": {"depTime": "06:30", "arrTime": "15:15",
                     "depDate": "2026-10-06", "arrDate": "2026-10-07",
                     "transInfo": {"transCity": "误入", "transTime": "99"}},
          "binfo2": {"depTime": "13:00"},
          "extparams": json.dumps({"stopFlight": True})}
    rows3 = QunarCrawler._extract_flights_obj([f3])
    assert "stopTime" not in rows3[0]
    assert rows3[0]["stopCitys"] == ""


def test_qunar_h5_biz_price_positive_only():
    """公务舱最低价：正数落 bizPrice，0/缺占位不落键（_pos_num 同律）。"""
    f = _h5_direct()
    f["extparams"] = json.dumps({"businessClassMinPrice": 7870})
    assert QunarCrawler._extract_flights_obj([f])[0]["bizPrice"] == 7870
    f2 = _h5_direct()
    f2["extparams"] = json.dumps({"businessClassMinPrice": 0})
    assert "bizPrice" not in QunarCrawler._extract_flights_obj([f2])[0]


# ---- ctrip：planeSize / cabinCode / 机场码归一 ----

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


def test_ctrip_plane_size_kind_and_bracket_fallback():
    """craftinfo.kind 渠道结构化真值（1=大型机/2=中型机）；kind 缺失
    时 cdisname「(中)」括号兜底；两者皆缺不落。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    for kind, want in ((1, "大型机"), (2, "中型机")):
        item = _ctrip_item([_ctrip_seg(dd, ad, craft={"kind": kind,
                                                      "cdisname": "波音787"})],
                           [_ctrip_policy()])
        assert _CT._extract_ctrip_flights(json.dumps([item]))[0][
            "planeSize"] == want
    item = _ctrip_item(
        [_ctrip_seg(dd, ad, craft={"cdisname": "空客330(中)"})],
        [_ctrip_policy()])
    assert _CT._extract_ctrip_flights(json.dumps([item]))[0][
        "planeSize"] == "中型机"
    item = _ctrip_item(
        [_ctrip_seg(dd, ad, craft={"cdisname": "波音737"})],
        [_ctrip_policy()])
    assert _CT._extract_ctrip_flights(json.dumps([item]))[0][
        "planeSize"] == ""


def test_ctrip_cabin_code_nt2_single_letter():
    """classNoteList notetype=2 notecnt 单字母随最低价政策配对；
    非单字母不落（宁缺勿错）；nt=1（恒等 prate）不采。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    ci = {"cgrd": 0, "prate": 92, "meal": "有餐食",
          "classNoteList": [{"notetype": 1, "notecnt": "92"},
                            {"notetype": 2, "notecnt": "Q"}]}
    item = _ctrip_item([_ctrip_seg(dd, ad, craft={"kind": 2,
                                                  "cdisname": "737(中)"})],
                       [_ctrip_policy(ci=ci)])
    assert _CT._extract_ctrip_flights(json.dumps([item]))[0][
        "cabinCode"] == "Q"
    ci2 = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "YB"}]}
    item2 = _ctrip_item([_ctrip_seg(dd, ad, craft={"kind": 2,
                                                   "cdisname": "737"})],
                        [_ctrip_policy(ci=ci2)])
    assert _CT._extract_ctrip_flights(json.dumps([item2]))[0][
        "cabinCode"] == ""


def test_ctrip_airport_cn_normalization():
    """机场码 AIRPORT_NAME_CN 归一为机场短名（与渲染端 _apt 剥后缀
    形态对齐）；未收录码原样保留。"""
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    item = _ctrip_item([_ctrip_seg(dd, ad, craft={"kind": 2,
                                                  "cdisname": "737"})],
                       [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row["depAirport"] == "乌鲁木齐天山"
    assert row["arrAirport"] == "虹桥"
    assert AIRPORT_NAME_CN.get("XXX", "XXX") == "XXX"


# ---- tongcheng：amt 换源 / sts 四键 / 中转行机场体量 ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def test_tongcheng_amt_primary_afn_fallback():
    """fl.amt 结构化体量为主源（95/95 恒在）；afn 括号兜底（渠道仅
    ~66% 下发是第六批 45.5% 半缺根因）。"""
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight(amt="大")]}}))
    assert rows[0]["planeSize"] == "大型机"
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": [_tc_flight(afn="空客A320(中)")]}}))
    assert rows[0]["planeSize"] == "中型机"
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight()]}}))
    assert rows[0]["planeSize"] == ""


def test_tongcheng_sts_seven_keys():
    """sts tt=2/6/7/9 四键提取（tuniu/ctrip 同协议）+ tt=3 WiFi 并
    labels + tt=8 廉价航空不采（flightnorm lcc 派生全渠道）。"""
    f = _tc_flight(sts=[
        {"tt": 1, "td": "到达准点率97%"},
        {"tt": 2, "td": "机龄14.6年"},
        {"tt": 4, "td": "无餐食"},
        {"tt": 6, "td": "航班廊桥率93%"},
        {"tt": 7, "td": "平均延误10分钟"},
        {"tt": 9, "td": "航班取消率3%"},
        {"tt": 3, "td": "机上WiFi"},
        {"tt": 8, "td": "廉价航空"},
    ])
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [f]}}))
    r = rows[0]
    assert r["planeAge"] == "14.6"
    assert r["avgDelay"] == 10
    assert r["cancelRate"] == 3
    assert r["bridgeRate"] == 93
    assert "机上WiFi" in r["labels"]
    assert "廉价航空" not in r["labels"]


def test_tongcheng_sts_absent_empty():
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight()]}}))
    r = rows[0]
    assert r["planeAge"] == "" and r["avgDelay"] == ""
    assert r["cancelRate"] == "" and r["bridgeRate"] == ""


def test_tongcheng_transfer_airport_and_plane_size():
    """中转行 depAirport/arrAirport=fp.dasn/aasn（两日 dump 24/24 恒在，
    DB 174 行全缺根因=漏读）；机型体量取 ss[].amn 括号。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "dasn": "天山", "aasn": "浦东", "dat": "", "aat": "T2",
          "ss": [{"fn": "CZ6981", "amn": "空客320(中)"},
                 {"fn": "MU5700", "amn": "波音787(大)"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}],
                   "pts": [{"td": "5.2折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert len(rows) == 1
    assert rows[0]["depAirport"] == "天山"
    assert rows[0]["arrAirport"] == "浦东"
    assert rows[0]["planeSize"] == "中型机"


# ---- flightnorm：lcc 派生 / stopTime「N时」形态 ----

def test_flightnorm_lcc_derived_true_only():
    """AIRLINE_LCC 命中落 f["lcc"]=True（仅 True 落键）；非廉航不落；
    code 命中同样生效（ctrip 中转行 name 只含首段）。"""
    f = normalize({"name": "春秋9C8866", "price": 1000})
    assert f.get("lcc") is True
    f2 = normalize({"name": "南航CZ6981", "price": 1000})
    assert "lcc" not in f2
    f3 = normalize({"name": "CZ6981", "code": "MU5533/9C8796",
                    "price": 1000})
    assert f3.get("lcc") is True


def test_flightnorm_stoptime_shi_form():
    """stopTime「18时30分」形态（qunar H5 transTime 真值）与「1小时5分」
    同产时刻式 stopTimeT。"""
    assert normalize({"price": 1, "stopTime": "18时30分"})["stopTimeT"] \
        == "18:30"
    assert normalize({"price": 1, "stopTime": "1小时5分"})["stopTimeT"] \
        == "1:05"
    assert normalize({"price": 1, "stopTime": "45分"})["stopTimeT"] \
        == "0:45"


def test_is_lcc_table_intact():
    """AIRLINE_LCC 二字码表既有语义不变（transferBaggage 直挂兜底
    判据共用）。"""
    assert _is_lcc("春秋9C8866") and _is_lcc("9C8866")
    assert not _is_lcc("南航CZ6981")
    assert "9C" in AIRLINE_LCC and "KN" in AIRLINE_LCC


# ---- 哨兵第七批扩容 ----

class TestSentinelBatch7:
    """psize/apt 比率观测 + tongcheng 四键/ctrip bridge/page/ccode
    白名单恒 0 观测；qunar|psize 入死键表（PC 软拒期间结构性无源）。"""

    def _sent(self, monkeypatch, tmp_path, prices):
        from types import SimpleNamespace as _NS
        import main as _m
        monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
        monkeypatch.setattr(_m, "_ROW_HIST", {})
        _m._SENT_LAST.clear()
        _m._SENT_CNT.clear()
        seen = []

        class _L:
            def warning(self, *a, **k):
                seen.append(a)

        class _I:
            def info(self, *a, **k):
                pass

        rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
        _m._field_sentinel(rows, _L())
        return seen

    def test_healthy_no_warning(self, monkeypatch, tmp_path):
        rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "prate": "96", "plane": "737", "planeSize": "中型机",
                 "depAirport": "咸阳", "avgDelay": 21,
                 "cancelRate": 3, "bridgeRate": 80,
                 "planeAge": "6.3", "cabinCode": "Y",
                 # aptc 入比率观测（排他断言同律：缺值=假键死）；
                 # discount 同律（「全价」并入后恒有源）
                 "discount": "4.5折",
                 "depAirportCode": "URC", "arrAirportCode": "SHA",
                 "arrTerminal": "T1", "layover": 90,
                 "transCity": "西安", "transTerminal": "咸阳T3",
                 "transferService": "转机免安检",
                 "leftTickets": 5, "fewTicket": "少量",
                 "shareCarrier": "MU5700"} for _ in range(30)]
        assert self._sent(monkeypatch, tmp_path,
                          [("ctrip", rows), ("tongcheng", rows)]) == []

    def test_dead_psize_apt_warns(self, monkeypatch, tmp_path):
        rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "prate": "96", "plane": "737"}
                for _ in range(30)]
        seen = self._sent(monkeypatch, tmp_path, [("ctrip", rows)])
        flat = " ".join(str(a) for w in seen for a in w)
        assert "psize" in flat
        assert "apt" in flat

    def test_qunar_psize_dead_key_silent(self, monkeypatch, tmp_path):
        """qunar planeSize 死键表静默（定律）。 起 psize
        随 plane 移出死键表（binfo.name 括号同源）转比率观测：夹具须带
        命中值才静默，缺值=假键死会红——语义从「死键免观测」翻转为
        「活体观测」。"""
        rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "prate": "96", "plane": "波音737(中)",
                 "planeSize": "中型机",
                 "depAirport": "乌鲁木齐天山",
                 # aptc 入比率观测：夹具同律带命中值防假键死；
                 # discount 同律（「全价」并入后恒有源）
                 "discount": "4.5折",
                 "depAirportCode": "URC", "arrAirportCode": "SHA",
                 "arrTerminal": "T1",
                 "shareCarrier": "MU5700" if i % 4 == 0 else "",
                 "fewTicket": "少量" if i % 5 == 0 else ""}
                for i in range(30)]
        assert self._sent(monkeypatch, tmp_path, [("qunar", rows)]) == []

    def test_tongcheng_new_keys_zero_hit_warns(self, monkeypatch, tmp_path):
        rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "prate": "96", "plane": "737", "planeSize": "中型机",
                 "depAirport": "咸阳"} for _ in range(30)]
        seen = self._sent(monkeypatch, tmp_path, [("tongcheng", rows)])
        flat = " ".join(str(a) for w in seen for a in w)
        for name in ("cancelRate", "bridgeRate", "planeAge"):
            assert name in flat, (name, flat)


# ---- 推送层：剥注单源 / compare biz / 总表次行第七批词面 ----

def test_notifier_mkt_note_single_source():
    """行情注剥除词表收口 _MKT_NOTE_DUPS 单源（审校）：
    手抄两份清零，定义+双消费在位；_alert_body 剥注行为不回退。
     收编投影：尾两位改挂 TIER_TRANSCRIBE/TIER_FULL（前两位
    标点变体留本地），行为等价由 _alert_body 断言守护。"""
    import core.notifier as _n
    from core.notifier import _alert_body, _MKT_NOTE_DUPS
    src = open(_n.__file__, encoding="utf-8").read()
    assert src.count("_MKT_NOTE_DUPS") >= 3
    # 投影等价：四元组值面与 定版逐字节一致
    assert _MKT_NOTE_DUPS == ("（行情价）", "*行情", "行情价", "行情破线")
    assert "行情破线" not in _alert_body("差￥570 行情破线")


def test_notifier_tts_tail_no_ellipsis():
    """TTS 绑定通道（ntfy/短信）截断尾注去 …（审校）：
    U+2026 播报成「。。。」定律同族。"""
    import core.notifier as _n
    src = open(_n.__file__, encoding="utf-8").read()
    assert '"…（已截断"' not in src
    assert '"…（已截断）"' not in src


def test_cancel_rate_alert_constant_single_source():
    """取消率阈值单源 core.alerter.CANCEL_RATE_ALERT，report import
    消费、本地字面量清零。"""
    from core.alerter import CANCEL_RATE_ALERT
    src = open(os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))),
        "report.py"), encoding="utf-8").read()
    assert "CANCEL_RATE_ALERT" in src
    import re as _re
    assert not _re.search(r"取消率.*?>=\s*1[0-9]", src)
    assert 10 <= CANCEL_RATE_ALERT <= 30


def test_compare_rows_biz_field():
    """公务舱价随行入比价组（_compare_rows 单源组装，实时推送/日报
    /预览三端同享）；无值不落。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="qunar", bizPrice=7870),
                    dict(base, price=2340, _platform="ctrip")],
             "2026-10-06")]
    rows = Alerter._compare_rows(cands)
    assert rows[0]["biz"] == 7870
    rows2 = Alerter._compare_rows(
        [(140, [dict(base, _platform="ctrip")], "2026-10-06")])
    assert rows2[0]["biz"] == ""


def test_render_table_batch7_smoke(tmp_path):
    """总表渲染烟测：第七批词面（廊桥/取消率门控/廉航/舱位括注/
    compare 公务词条）真实 PIL 渲染无异常。"""
    from PIL import Image
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("渲染烟测依赖 Windows 中文字体度量（CI 无雅黑）")
    from report import render_flights_table
    f = {"price": 2200, "code": "9C8846", "name": "春秋9C8846",
         "depTime": "16:40", "arrTime": "21:30", "depDate": "2026-10-06",
         "arrDate": "2026-10-06", "transCity": "", "crossDayDesc": "",
         "totalDuration": "4时50分", "cabin": "经济舱", "cabinCode": "Y",
         "plane": "空客321", "planeSize": "中型机", "bridgeRate": 80,
         "cancelRate": 27, "lcc": True, "prate": "92", "meal": "",
         "baggage": "无托运行李", "discount": "5.1折", "fewTicket": "少量",
         "shareCarrier": "", "depTerminal": "", "arrTerminal": "T1",
         "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥",
         "_platform": "qunar", "stopover": False}
    comp = {"label": "春秋9C8846", "dep": "16:40", "arr": "21:30",
            "trans": "", "cross": "", "lay": "", "stopCity": "",
            "chain": [("去哪儿", 2200, "经济舱"), ("携程", 2340, "经济舱")],
            "biz": 7870, "save": 140, "outlier": False}
    out = str(tmp_path / "t.png")
    render_flights_table([("direct", [f]), ("compare", [comp])],
                         "测试标题", out_path=out)
    assert os.path.exists(out) and os.path.getsize(out) > 20000
    Image.open(out).verify()


def test_render_table_cancel_gate_low_no_word(tmp_path):
    """cancelRate 常态值（<CANCEL_RATE_ALERT）不出词——门控防次行
    容量回退率系统性抬升（教训）。"""
    from PIL import Image
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("渲染烟测依赖 Windows 中文字体度量（CI 无雅黑）")
    from report import render_flights_table
    f = {"price": 2200, "code": "CZ6981", "name": "南航CZ6981",
         "depTime": "16:40", "arrTime": "21:30", "depDate": "2026-10-06",
         "arrDate": "2026-10-06", "transCity": "", "crossDayDesc": "",
         "totalDuration": "4时50分", "cabin": "经济舱",
         "plane": "空客321", "planeSize": "中型机",
         "cancelRate": 3, "bridgeRate": 90, "prate": "97",
         "meal": "正餐", "baggage": "免费托运20KG",
         "depTerminal": "", "arrTerminal": "T2",
         "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥",
         "_platform": "tongcheng", "stopover": False}
    out = str(tmp_path / "t.png")
    render_flights_table([("direct", [f])], "t", out_path=out)
    assert Image.open(out).size[0] > 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
