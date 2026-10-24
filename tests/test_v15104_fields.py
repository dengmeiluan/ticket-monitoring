# -*- coding: utf-8 -*-
"""渠道三案：fliggy 日历邻日价 trendGo（v177 弃采备案三腿复验推翻——
跨渠道协议归一第三源）/ qunar 中转二段出发日期 transGoDate（跨天中转
辨识信息，现有 lay2dep 只有 HH:MM 无日期）/ tuniu prate 空串占位
卫生改（同族 avgDelay/discount 无值不落键律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15104_fields.py
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402


# ---- fliggy 日历邻日最低价：trendGo 同协议归一（qunar goFTrend /
#      tongcheng pc[] 同族，消费端 webui 改期胶囊现成） ----

def test_fliggy_cal_points_protocol():
    # JS 采集器原始返回 [[YYYY-MM-DD,价],…] → 协议形态 [["MM-DD",价],…]
    raw = [["2026-10-03", 930], ["2026-10-04", 1190], ["2026-10-06", 3070]]
    assert FliggyCrawler._parse_cal_points(raw) == [
        ["10-03", 930], ["10-04", 1190], ["10-06", 3070]]


def test_fliggy_cal_points_guards():
    # 逐点校验宁缺勿错（同 qunar _parse_trend_go）：日期形不正/价越界
    # （价带 100-50000）/非数值，坏点逐点弃；全坏与非 list 输入→None
    raw = [["2026-10-03", 930], ["bad", 100], ["2026-10-04", 99],
           ["2026-10-05", 60000], ["2026-10-07", "abc"], [None, 500]]
    assert FliggyCrawler._parse_cal_points(raw) == [["10-03", 930]]
    assert FliggyCrawler._parse_cal_points([["bad", 1]]) is None
    assert FliggyCrawler._parse_cal_points([]) is None
    assert FliggyCrawler._parse_cal_points(None) is None
    assert FliggyCrawler._parse_cal_points("x") is None


_FLIGGY_TXT = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
               "9C6927\n06:40\n11:55\n¥900\n订票")


def test_fliggy_trendgo_attached_to_min_row():
    # 日历 7 点挂当轮最低价行（qunar/tongcheng 同律「仅挂当轮最低价
    # 行」——逐行重复=extra 膨胀）；高价行不挂
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-06",
        cal_pts=[["10-03", 930], ["10-09", 900]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["trendGo"] == [["10-03", 930], ["10-09", 900]]
    hi = max(fs, key=lambda f: f["price"])
    assert "trendGo" not in hi


def test_fliggy_trendgo_absent_without_cal():
    # 无日历数据（页面异形/采集失败）不落键——行 schema 与既有轮全等
    fs = FliggyCrawler._parse_pc_text(_FLIGGY_TXT, "2026-10-06")
    assert fs and all("trendGo" not in f for f in fs)


# ---- qunar 中转二段出发日期 transGoDate ----

def _pc_trans_sample(tgd):
    s = json.loads(_PC_BASE)
    row = s["data"]["flights"][0]
    row["transCity"] = "兰州"
    b1 = {"depTime": "08:00", "arrTime": "11:00", "date": "2026-10-04",
          "depTerminal": "", "arrTerminal": "T2",
          "depAirport": "天山", "arrAirport": "地窝堡"}
    if tgd is not None:
        b1["transCityDepDate"] = tgd
    row["binfo1"] = b1
    row["binfo2"] = {"depTime": "15:30", "arrTime": "18:00",
                     "arrDate": "2026-10-05"}
    return json.dumps(s)


_PC_BASE = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223/FM9224", "minPrice": "2472", "transCity": "",
         "extparams": {},
         "binfo": {"airCode": "FM9223", "shortName": "上航",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-10-04", "arrDate": "2026-10-05"}}]}})


def test_qunar_pc_trans_go_date_cross_day():
    # 跨天中转二段起飞日（binfo1.transCityDepDate，WA 调研 23/23 在场）
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-05"), "2026-10-04")
    assert fl and fl[0]["transGoDate"] == "2026-10-05"


def test_qunar_pc_trans_go_date_guards():
    # 同日（无增量不落，同 transDepTerminal 纪律）/早于出发日（不合理）/坏格式
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-04"), "2026-10-04")
    assert fl and "transGoDate" not in fl[0]
    fl2 = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-03"), "2026-10-04")
    assert fl2 and "transGoDate" not in fl2[0]
    fl3 = QunarCrawler._parse_pc_flights(_pc_trans_sample("10-05"), "2026-10-04")
    assert fl3 and "transGoDate" not in fl3[0]
    # 直飞行（无中转）即使报文带键也不落——键语义=中转二段
    s = json.loads(_PC_BASE)
    s["data"]["flights"][0]["binfo1"] = {
        "depTime": "08:00", "arrTime": "11:00", "date": "2026-10-04",
        "transCityDepDate": "2026-10-05"}
    fl4 = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl4 and "transGoDate" not in fl4[0]


def test_qunar_h5_trans_go_date_both_extparams_shapes():
    # H5 源 extparams.transGoDate（JSON 串/dict 双形态，_stopflight 同律）
    row = {"code": "GS7587", "price": 800, "minPrice": 800,
           "transCity": "石家庄",
           "binfo1": {"depTime": "14:30", "arrTime": "00:20",
                      "depDate": "2026-10-06", "arrDate": "2026-10-07"},
           "binfo2": {"depTime": "06:05", "arrTime": "07:55"}}
    ep_dict = dict(row, extparams={"transGoDate": "2026-10-07"})
    fl = QunarCrawler._extract_flights_obj([ep_dict])
    assert fl and fl[0]["transGoDate"] == "2026-10-07"
    ep_str = dict(row, extparams=json.dumps({"transGoDate": "2026-10-07"}))
    fl2 = QunarCrawler._extract_flights_obj([ep_str])
    assert fl2 and fl2[0]["transGoDate"] == "2026-10-07"
    # 同日不落
    ep_same = dict(row, extparams={"transGoDate": "2026-10-06"})
    fl3 = QunarCrawler._extract_flights_obj([ep_same])
    assert fl3 and "transGoDate" not in fl3[0]


# ---- tuniu prate 空串占位卫生改（无值不落键同族律） ----

_TUINU_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [], "labels": "宽体机",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "上航",
}


def test_tuniu_prate_real_value_still_set():
    fs = TuniuCrawler._offers_to_flights([dict(_TUINU_OFFER)])
    assert fs[0]["prate"] == "96"


def test_tuniu_prate_placeholder_and_empty_not_set():
    # 渠道「20%」占位（_prate 置空）与无值空串均不落键——
    # 生产 20.2% 行 prate='' 空串常态化（WC 观测），同族 avgDelay/
    # discount 无值不落键律收口
    o = dict(_TUINU_OFFER, onTimeRate="20")
    assert "prate" not in TuniuCrawler._offers_to_flights([o])[0]
    o2 = dict(_TUINU_OFFER, onTimeRate="")
    assert "prate" not in TuniuCrawler._offers_to_flights([o2])[0]
    o3 = dict(_TUINU_OFFER, onTimeRate=None)
    assert "prate" not in TuniuCrawler._offers_to_flights([o3])[0]


# ---- webui 白名单与渲染门（源码钉：字符串在场锚；行为面归 uitest） ----

def test_webui_trans_go_date_whitelist_and_gate():
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    assert '"transGoDate": (f.get("transGoDate") or "").strip(),' in src
    # 渲染门：二段行携带日期形态（MM-DD 由 JS slice 产出）——
    # 钉门卫开关字面（任意提及即过=锚定力弱）
    assert "(f.lay2dep||f.transGoDate)" in src
