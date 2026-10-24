# -*- coding: utf-8 -*-
"""tuniu stopPoints 经停段起降时刻 stopWin：

渠道 stopPoints[].arrivalTime / departrueTime（departrue 为渠道原始
拼写）是五渠道唯一经停段时刻源，与已采 duration 精确互证（调研
9/9：19:20→20:05 = duration 45 分）——「停多久」之外给出经停窗口
绝对时刻，可判经停段红眼/晚间滞留（决策信息：清晨经停与深夜滞留
是两种出行体验）。键形态恒落（与 stopCitys/stopTime 同族：空串
不占位、normalize 通道零依赖）；消费端 webui 明细 stoptag/brief
括注 + CSV 经停列；推送面不接（行宽预算内属二阶信息，备案）。
"""
import os

from crawlers.tuniu import TuniuCrawler, _stop_window

# 生产 dump 逐字实证形态（tuniu_raw_2026-10-06.json CA8564 行）
_SP = {"airPortCode": "XNN", "airPortName": "曹家堡机场",
       "arrivalTime": "2026-10-06 19:20:00", "cityCode": "XNN",
       "cityName": "西宁", "departrueTime": "2026-10-06 20:05:00",
       "duration": "45"}

_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [_SP], "labels": "",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "",
}


def test_stop_window_single_leg():
    assert _stop_window([_SP]) == "19:20-20:05"


def test_stop_window_multi_legs_joined():
    sp2 = dict(_SP, arrivalTime="2026-10-06 21:10:00",
               departrueTime="2026-10-06 21:55:00")
    assert _stop_window([_SP, sp2]) == "19:20-20:05/21:10-21:55"


def test_stop_window_partial_missing_pair_skipped():
    # 单段缺任一时刻 → 该段不成对（宁缺勿错），余段照出
    half = dict(_SP, departrueTime=None)
    assert _stop_window([half, _SP]) == "19:20-20:05"


def test_stop_window_empty_and_dirty_input():
    assert _stop_window([]) == ""
    assert _stop_window(None) == ""
    assert _stop_window(["x", 7, {}]) == ""
    # 脏时刻（无 HH:MM 可提）不成对
    dirty = dict(_SP, arrivalTime="TBD", departrueTime="")
    assert _stop_window([dirty]) == ""


def test_offers_row_carries_stopwin():
    fs = TuniuCrawler._offers_to_flights([dict(_OFFER)])
    assert fs[0]["stopWin"] == "19:20-20:05"


def test_offers_row_without_stops_keeps_empty_key():
    # 无值不落键（r241 残留族收口）：无经停行 stopWin/stopCitys/
    # stopTime 整族缺席（有值照落见上例 19:20-20:05）
    o = dict(_OFFER, stopPoints=[])
    row = TuniuCrawler._offers_to_flights([o])[0]
    assert "stopWin" not in row and "stopCitys" not in row
    assert "stopTime" not in row


# ---- webui 三端透传（源码钉：载荷出口与消费词面在场；行为面归 uitest） ----

def test_webui_stopwin_payload_and_gate():
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    # Python 载荷两处出口（KPI brief + 明细行，与 stopTimeT 同位同构）
    assert src.count('"stopWin": (f.get("stopWin") or "").strip(),') == 2
    # 前端消费：brief 与明细 stoptag 括注 + CSV 经停列
    assert "brief.stopWin" in src
    assert "f.stopWin" in src
