# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r246_fields.py
- tests/test_v1589_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r246_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t246")

# ---- D1 fliggy airlineCode ----

_FLIGGY_DIRECT = "\n".join([
    "东航MU8369", "中型机 737",
    "08:30", "11:45",
    "乌鲁木齐天山国际机场", "上海虹桥国际机场",
    "¥1200 5.5折", "订票",
])

_FLIGGY_TRANSFER = "\n".join([
    "奥凯BK2776", "中型机 738",
    "上航FM9402", "中型机 738",
    "10月05日 15:15", "10月05日 19:05",
    "10月06日 06:05", "10月06日 07:55",
    "乌鲁木齐天山国际机场", "长沙中转", "黄花国际机场T1",
    "¥2060 5.0折", "订票",
])


def test_fliggy_airline_code_derived_from_code():
    """D1：二字码从 code 首两字符派生（iata2 守卫），直飞行落键。"""
    rows = FliggyCrawler._parse_pc_text(_FLIGGY_DIRECT, "2026-10-06")
    assert rows and rows[0]["code"] == "MU8369", rows
    assert rows[0]["airlineCode"] == "MU"


def test_fliggy_airline_code_digit_head():
    """数字头二字码（9C 春秋/3U 川航形态）同律：9C8945 → 9C。"""
    rows = FliggyCrawler._parse_pc_text(
        _FLIGGY_DIRECT.replace("东航MU8369", "9C8945"), "2026-10-06")
    assert rows and rows[0]["airlineCode"] == "9C"


def test_fliggy_airline_code_transfer_first_leg():
    """中转定证行 code=「首段/二段」合串：airlineCode 随首段
    （与 qunar 中转 shortCarrier=首段承运语义对齐）。"""
    rows = FliggyCrawler._parse_pc_text(_FLIGGY_TRANSFER, "2026-10-05")
    assert rows and rows[0]["code"] == "BK2776/FM9402", rows
    assert rows[0]["airlineCode"] == "BK"


def test_fliggy_airline_code_guard_rejects_bad_shape():
    """iata2 守卫形态拒面直钉（原钉样本「测试X1Y2」被 _RE_FNO 整行
    拒、rows=[] 断言短路恒真，守卫删除也不报警——Soldier P1-1 纠偏
    为守卫出口直钉）：脏形（单字符/三位/小写/空）一律不派生；
    二字码（含数字头）照过。iata2 是全渠道 airlineCode 派生律的
    守卫单源，钉它即钉 fliggy code[:2] 派生路径。"""
    from crawlers.base import iata2
    assert iata2("MU") == "MU"
    assert iata2("9C") == "9C"
    assert iata2("M") == ""
    assert iata2("MU8") == ""
    assert iata2("mu") == ""
    assert iata2("") == ""


# ---- D3 qunar crossDayDesc binfo 层补源 ----

def _pc_flight(**kw):
    f = {"minPrice": 1200, "code": "G581O1J",
         "binfo": {"depTime": "20:35", "arrTime": "20:40",
                   "date": "2026-10-06", "arrDate": "2026-10-07"},
         "extparams": "{}"}
    f.update(kw)
    return f


def test_qunar_pc_cross_day_desc_from_binfo():
    """D3 PC：顶层缺席 + binfo 在场 → 落键（经停伪码族实证形态）。"""
    f = _pc_flight(binfo={"depTime": "20:35", "arrTime": "20:40",
                          "date": "2026-10-06", "arrDate": "2026-10-07",
                          "crossDayDesc": "+1天"})
    rows = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [f]}}), "2026-10-06")
    assert rows and rows[0].get("crossDayDesc") == "+1天", rows


def test_qunar_pc_cross_day_desc_top_level_wins():
    """顶层有值时顶层优先（既有行为不变——两处同值零分歧实证）。"""
    f = _pc_flight(crossDayDesc="+2天",
                   binfo={"depTime": "20:35", "arrTime": "20:40",
                          "date": "2026-10-06", "arrDate": "2026-10-08",
                          "crossDayDesc": "+1天"})
    rows = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [f]}}), "2026-10-06")
    assert rows and rows[0].get("crossDayDesc") == "+2天", rows


def test_qunar_h5_cross_day_desc_from_binfo():
    """D3 H5 兜底路径同款：_extract_flights_obj binfo 层补源。"""
    f = {"minPrice": 1200, "code": "FM9224",
         "binfo": {"depTime": "20:35", "arrTime": "20:40",
                   "depDate": "2026-10-06", "arrDate": "2026-10-07",
                   "crossDayDesc": "+1天"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows and rows[0].get("crossDayDesc") == "+1天", rows


def test_qunar_cross_day_desc_absent_when_nowhere():
    """两处皆无 → 键不落（无值不落键纪律不变）。"""
    rows = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [_pc_flight()]}}), "2026-10-06")
    assert rows and "crossDayDesc" not in rows[0], rows


# ---- D2 tongcheng trendHoliday ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def test_tongcheng_trend_holiday_landed():
    """D2：pc[] 节假日点位 → trendHoliday=[[MM-DD,词],…] 挂当轮
    最低价行（trendGo 第八批同构；词面=holidayName·tag）。"""
    data = {"fl": [_tc_flight()],
            "pc": [{"dd": "2026-09-27", "lp": 916,
                    "isHoliday": True, "holidayName": "中秋节", "tag": "休"},
                   {"dd": "2026-10-01", "lp": 880, "holidayName": "国庆节"},
                   {"dd": "2026-09-28", "lp": 900}]}
    rows = TongchengCrawler._extract_flights(json.dumps({"data": data}))
    assert rows and rows[0].get("trendGo"), rows
    assert rows[0]["trendHoliday"] == [["09-27", "中秋节·休"],
                                       ["10-01", "国庆节"]], rows[0]


def test_tongcheng_trend_holiday_absent_without_pc():
    """pc 缺席/无节假日点 → 键不落（无值不落键律）。"""
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [_tc_flight()]}}))
    assert rows and "trendHoliday" not in rows[0], rows
    data = {"fl": [_tc_flight()],
            "pc": [{"dd": "2026-09-28", "lp": 900}]}
    rows = TongchengCrawler._extract_flights(json.dumps({"data": data}))
    assert rows and "trendHoliday" not in rows[0], rows


def test_tongcheng_trend_holiday_ignores_bad_points():
    """坏点（dd 形态不正/价域外/非 dict）不进词条，健康点照落。"""
    data = {"fl": [_tc_flight()],
            "pc": ["junk",
                   {"dd": "bad", "lp": 916, "holidayName": "中秋节"},
                   {"dd": "2026-09-27", "lp": 9, "holidayName": "中秋节"},
                   {"dd": "2026-09-27", "lp": 916,
                    "holidayName": "中秋节", "tag": "休"}]}
    rows = TongchengCrawler._extract_flights(json.dumps({"data": data}))
    assert rows[0]["trendHoliday"] == [["09-27", "中秋节·休"]], rows[0]


# ---- W1 qunar 非标准航班号形态观测哨（dbobs 报告第 1 段 WATCH）----

def test_w1_odd_code_shape_sentinel():
    """非标形态（经停伪码 G581O1J 族，渠道本态）入哨；正常码/合串
    真码不扰；合串含伪码段整码入哨。"""
    from crawlers.qunar import _odd_code_shapes
    assert _odd_code_shapes([{"code": "G581O1J"}]) == ["G581O1J"]
    assert _odd_code_shapes([{"code": "CZ6981"}]) == []
    assert _odd_code_shapes([{"code": "9C8945"}]) == []
    assert _odd_code_shapes([{"code": "BK2776/FM9402"}]) == []
    assert _odd_code_shapes([{"code": "G581O1J/FM9402"}]) == [
        "G581O1J/FM9402"]
    assert _odd_code_shapes([{}]) == []


def test_w1_sentinel_wired_in_crawl():
    """调用点接线源码钉：crawl 轮内必须消费 _odd_code_shapes
    （漏接线=哨死代码）。"""
    src = open("crawlers/qunar.py", encoding="utf-8").read()
    assert src.count("_odd_code_shapes(") >= 2, "哨调用点未接线"


# ---- merged from tests/test_v1589_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t189")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip：老客专享资格标签 ----

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


def _ctrip_policy(price=1200, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_login_discount_label():
    """tcode=G_LoginMobileDiscount tagcnt「老客专享」：资格价标记入
    labels（该行价格非全民价——登录/老客才可买的决策信息）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})],
        aset=[{"tagarea": [{"tcode": "G_LoginMobileDiscount",
                            "tagcnt": "老客专享"}]}])
    assert "老客专享" in _ctrip_one(item)["labels"].split("·")


def test_ctrip_login_discount_absent_untouched():
    """无 aset 行照常产出（labels 其余词不回退）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})])
    assert "老客专享" not in _ctrip_one(item).get("labels", "")


# ---- ctrip：bizCabin 舱别词面随源 ----

def test_ctrip_biz_cabin_high_cabin_word():
    """胜出（最低 tprice）政策 cgrd=2：bizCabin 随渠道词面。r256
    勘误：cgrd 值域漂移 {0,1,2}→{0,2} 且现行代 2=公务舱（nt=4 词面
    69/69「公务舱」、「头等舱」全 dump 0 例；旧代 CA8564 曾实证
    2=头等——数字→词代际不稳定，以 nt=4 词面为唯一权威）。本用例
    原断言「头等」系旧代前提，随勘误对齐为「公务」。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0}),
         _ctrip_policy(price=9900, ci={"cgrd": 2}),
         _ctrip_policy(price=2730, ci={"cgrd": 2})]))
    assert r["bizPrice"] == 2730
    assert r["bizCabin"] == "公务"


def test_ctrip_biz_cabin_business_word():
    """cgrd=1=公务：bizCabin=「公务」。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0}),
         _ctrip_policy(price=2730, ci={"cgrd": 1})]))
    assert r["bizCabin"] == "公务"


def test_ctrip_biz_cabin_absent_without_biz_price():
    """无高档舱政策：bizPrice/bizCabin 双双不落。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})]))
    assert "bizPrice" not in r
    assert "bizCabin" not in r


def test_compare_rows_biz_cabin_carried():
    """比价组携 bizCab（与 biz 同一行取源——同律防跨行错配）。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="ctrip", bizPrice=2730,
                         bizCabin="头等")], "2026-10-06")]
    row = Alerter._compare_rows(cands)[0]
    assert row["biz"] == 2730
    assert row["bizCab"] == "头等"


def test_compare_rows_biz_cabin_legacy_empty():
    """存量行无 bizCabin：bizCab 空串（渲染端回退「公务」）。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="qunar", bizPrice=7870)],
              "2026-10-06")]
    assert Alerter._compare_rows(cands)[0]["bizCab"] == ""


def test_report_biz_word_follows_source():
    """report 链尾词条词面随 bizCab 单源（缺省回退「公务」）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert "line.get('bizCab')" in src, "report 链尾词条未随 bizCab 源"


def test_webui_biz_cabin_three_ends():
    """webui 三端同轮：API 白名单透传 + CSV/title 词面随源 + CSV
    列头如实（高档舱）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = webui_full_src()
    assert '"bizCabin": f.get("bizCabin")' in src, "API 白名单缺 bizCabin"
    assert "f.bizCabin||'公务'" in src, "CSV 词面未随源"
    assert "he(f.bizCabin||'公务')" in src, "title 词面未随源"
    assert "'机建燃油','高档舱','退改'" in src, "CSV 列头未如实"


# ---- tongcheng：connection fwbqs 第二段服务承诺 ----

def _tc_row(lps=None, doc=None):
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "MU5700", "aat": "T2"},
                 {"fn": "MU2301", "dat": "T3"}],
          "lps": lps or [{"atp": 1800, "brs": [{"al": 3}]}]}
    text = json.dumps({"data": {"fps": [fp], "doc": doc or {}}})
    rows = TongchengCrawler._extract_transfer_flights(text)
    assert rows
    return rows[0]


def test_tongcheng_fwbqs_second_leg_wifi():
    """最低价政策带 fwbqs 真值「第2程：免费上网」：落 labels（中转
    第二段机上 WiFi 服务承诺，sts tt=3 同族）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "第2程：免费上网"}]}])
    assert r["labels"] == "第2程：免费上网"


def test_tongcheng_fwbqs_unknown_td_dropped():
    """白名单外词面整段不并（宁缺勿错——渠道改文案即静默不采）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "神秘权益"}]}])
    assert "labels" not in r


def test_tongcheng_fwbqs_absent_no_labels():
    """fwbqs 缺席/空：不落 labels 键（零新键，行形态不漂移）。"""
    assert "labels" not in _tc_row()
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}], "fwbqs": []}])
    assert "labels" not in r


def test_tongcheng_fwbqs_pairs_with_min_price_policy():
    """多政策时随最低价政策配对（同 cabin/$tcTip 同律防政策错配）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}]},
                     {"atp": 2600, "brs": [{"al": 2}],
                      "fwbqs": [{"tt": 3, "td": "第2程：免费上网"}]}])
    assert "labels" not in r   # fwbqs 挂在非最低价政策上，不采


def test_tongcheng_fwbqs_first_leg_wifi():
    """渠道段序词面静默摆动（r228 代际「第2程」→r233 代际「第1程」，
    两代际稳定同值）：正则白名单收口后第一段 WiFi 承诺同样落 labels，
    零新键随既有渲染通道。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "第1程：免费上网"}]}])
    assert r["labels"] == "第1程：免费上网"


def test_tongcheng_fwbqs_seg_out_of_range_dropped():
    """中转两段结构界外词面（第3程）仍不采（正则放宽不破宁缺勿错）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "第3程：免费上网"}]}])
    assert "labels" not in r


# ---- 解析哨兵：discount 入列 ----

def _sent_rows(discount):
    return [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
             "prate": "", "plane": "波音737(中)", "discount": discount,
             "shareCarrier": "MU5700" if i % 3 == 0 else "",
             "fewTicket": "仅剩5张" if i % 5 == 0 else "",
             "arrTerminal": "T2", "depAirport": "乌鲁木齐天山",
             "planeSize": "中型机", "depAirportCode": "URC",
             "arrAirportCode": "SHA"} for i in range(30)]


def _sent(monkeypatch, tmp_path, prices, keep_supplied=False):
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    if not keep_supplied:
        _m._SENT_SUPPLIED.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

        def info(self, *a, **k):
            pass

    rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
    _m._field_sentinel(rows, _L())
    return seen


def test_sentinel_discount_attended_healthy(monkeypatch, tmp_path):
    """五渠道现役恒有源（「N.N折」/「全价」两形态）：出勤高且稳，
    健康轮零告警（入列不假火）。"""
    seen = _sent(monkeypatch, tmp_path,
                 [("qunar", _sent_rows("4.5折"))])
    assert seen == [], seen


def test_sentinel_discount_death_alarms(monkeypatch, tmp_path):
    """discount 整字段断链（命中率 <10%）：比率观测告警——词面代行
    断供（「全价」形态丢失）静默死亡从此有观测。供给基线语义
    （r316）：健康轮写供给，断链轮归零真警。"""
    seen0 = _sent(monkeypatch, tmp_path,
                  [("qunar", _sent_rows("4.5折"))])
    assert seen0 == [], seen0
    seen = _sent(monkeypatch, tmp_path, [("qunar", _sent_rows(""))],
                 keep_supplied=True)
    assert len(seen) == 1 and "discount" in str(seen[0]), seen
