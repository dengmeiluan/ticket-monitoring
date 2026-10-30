# -*- coding: utf-8 -*-
"""r246 渠道字段三案（调研 _scratch/r246_report_*.md）：

D1 fliggy airlineCode——五渠道唯一无航司二字码缺口（B-3，健康 dump
31/31 行 DOM 类钩子 pi-flightlogo-nl-XX 值域 ^[A-Z0-9]{2}$ 与 _RE_FNO
code 前缀同串）：从 code 派生 + iata2 守卫（qunar H5 flightMark.carrier
≡ code 前缀 146/146 同款派生律），落同名键 webui 白名单/CSV/搜索 hay
三消费面自动继承。

D2 tongcheng trendHoliday——改期日历节假日标注（B-1）：data.pc[] 同
点位 holidayName/tag（43% 点位在场；trendGo 第八批同构），独立键挂当
轮最低价行，消费端 webui 改期窗口柱图 title；hlp r254 翻案采入
（inHighCabin 三点全等推翻「语义未证」旧备案，见 test_r254_fields.py）。

D3 qunar crossDayDesc binfo 层补源（dbobs W2）：H5 健康 dump 70 行中
3 行（FM9224/MU8370/G581O1J）crossDayDesc 只在 binfo 层（顶层缺席、
值零分歧），现行两路径只取顶层——经停/共享跨天行「+1天」徽标漏采
（arrDate 已正确进位，仅显示层缺口）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r246_fields.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

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
