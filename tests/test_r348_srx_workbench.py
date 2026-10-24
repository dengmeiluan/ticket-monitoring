# -*- coding: utf-8 -*-
"""r348 生产检索工作台：稳定行身份 / 日历诚实 / 三接口 / 单实现契约。"""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def _db(tmp_path, name="srx.db"):
    p = str(tmp_path / name)
    st = PriceStorage(p)
    return p, st


def _save(st, platform, frm, to, date, price, extra):
    st.save(FlightPrice(platform, frm, to, date, price,
                        extra=json.dumps(extra, ensure_ascii=False)))


def test_row_key_stable_across_rounds_and_price(tmp_path):
    a = {"rowId": 7, "rawIdx": 2, "price": 880, "depTime": "09:55",
         "arrTime": "13:40", "code": "MU541", "platKey": "ctrip",
         "from": "SHA", "to": "BKK", "date": "2026-11-20"}
    b = dict(a, rowId=8, rawIdx=0, price=901)
    assert webui._srx_row_key(a) == webui._srx_row_key(b)
    assert webui._srx_raw_key(a) == "r7:2"
    assert webui._srx_raw_key(b) == "r8:0"
    stale = {"rowId": None, "rawIdx": None, "price": 900, "depTime": "10:00",
             "arrTime": "14:00", "code": "MU541", "platKey": "ctrip",
             "from": "SHA", "to": "BKK", "date": "2026-11-20",
             "isStale": True}
    assert webui._srx_row_key(stale) == webui._srx_row_key(dict(stale, price=999))
    assert webui._srx_raw_key(stale) == ""


def test_flight_key_excludes_calendar_and_normalizes_composite():
    cal = {"isCal": True, "code": "", "depTime": "", "arrTime": "",
           "date": "2026-11-20"}
    assert webui._srx_flight_key(cal) == ""
    a = {"code": "SC2168/G56507", "depTime": "23:05", "arrTime": "22:00",
         "date": "2027-01-29", "trans": "厦门", "cross": "", "stop": False}
    b = dict(a, code="G56507/SC2168")
    assert webui._srx_flight_key(a) == webui._srx_flight_key(b)
    assert webui._srx_flight_key(a) != webui._srx_flight_key(
        dict(a, depTime="23:06"))


def test_calendar_rows_are_not_qualified(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-20", 719,
          [{"price": 719, "name": "日历最低价", "depDate": "2026-11-20"}])
    route = Route("SHA", "上海", "BKK", "曼谷", ["2026-11-20"],
                  alert_direct=1000, alert_transfer=0)
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "srx", "routes": [route]})
    finally:
        webui._State.cfg = old
    f = stt["flights"][0]
    assert f["isCal"] is True and f["cal"] is True
    assert f["qual"] is False
    assert stt["hit"] is False
    assert stt["roundUpdated"]


def test_best_and_route_calendar_exclude_thin_calendar_rows(tmp_path):
    dbp, st = _db(tmp_path)
    date = "2026-11-20"
    _save(st, "ctrip", "SHA", "BKK", date, 719,
          [{"price": 719, "name": "日历最低价", "depDate": date}])
    _save(st, "tuniu", "SHA", "BKK", date, 762,
          [{"price": 762, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": date, "totalDuration": "4时45分"}])
    route = Route("SHA", "上海", "BKK", "曼谷", [date],
                  alert_direct=900, alert_transfer=0)
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "srx", "routes": [route]})
    finally:
        webui._State.cfg = old
    assert stt["best"]["direct"]["price"] == 762
    assert "日历" not in (stt["best"]["direct"].get("name") or "")
    assert stt["minsArr"] == [["途牛", 762]]
    cal = stt["routesArr"][0]["cal"]
    assert cal and all(p != 719 for _d, p, _tier in cal)


def test_srx_links_five_and_intl_unsupported():
    dom = webui._srx_links("SHA", "HAK", "2027-01-29")
    assert dom["ok"] and len(dom["links"]) == 5
    assert all(x["ok"] for x in dom["links"]), dom
    intl = webui._srx_links("SHA", "BKK", "2026-11-20")
    by = {x["key"]: x for x in intl["links"]}
    assert by["tuniu"]["ok"] is True
    assert "m.tuniu.com/m2015/intlFlight/flight/list" in by["tuniu"]["url"]
    assert by["tongcheng"]["ok"] is False and by["tongcheng"]["url"] == ""
    assert by["qunar"]["ok"] and by["ctrip"]["ok"] and by["fliggy"]["ok"]


def test_srx_health_raw_key_rates(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-20", 880,
          [{"price": 880, "tax": 135, "depTime": "09:55",
            "arrTime": "13:40", "totalDuration": "4时45分"},
           {"price": 901, "tax": 135, "depTime": "18:10",
            "arrTime": "22:20"}])
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        j = webui._srx_health("SHA", "BKK", "2026-11-20")
    finally:
        webui._State.cfg = old
    ct = next(x for x in j["channels"] if x["key"] == "ctrip")
    assert j["measure"] == "raw_key_rate"
    assert ct["rows"] == 2
    assert ct["fields"]["price"] == {"n": 2, "total": 2, "rate": 100}
    assert ct["fields"]["cabin"]["n"] == 0
    assert ct["capturedAt"]


def test_srx_calendar_axes_are_distinct(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-16", 700,
          [{"price": 700, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": "2026-11-16"}])
    _save(st, "ctrip", "SHA", "BKK", "2026-11-17", 720,
          [{"price": 720, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": "2026-11-17"}])
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        j = webui._srx_calendar("SHA", "BKK", "2026-11-16", 14)
    finally:
        webui._State.cfg = old
    assert j["ok"]
    assert [x["date"] for x in j["departure"]] == ["2026-11-16", "2026-11-17"]
    assert "两轴" in j["note"] or "不可互换" in j["note"]
    assert all("-" in x["date"] and len(x["date"]) == 5 for x in j["observation"])


def test_search_page_single_implementation_and_capability_markers():
    src = webui.PAGE
    for name in ("renderSearch", "srxSelect", "srxSwitchUser", "srxDetailHTML",
                 "srxFetchRaw", "srxRawBoxHTML", "srxAll", "srxChAge",
                 "srxPairName", "srxPayload"):
        assert src.count("function %s(" % name) == 1, name
    for needle in ("srxBandDays", "srxBrief", "srxFacets", "srxMobilebar",
                   "srxViewBtn", "srxGallery", "SRX_HEALTH", "srx-health", "srxStateBox",
                   "srxSessions", "srxCompareHTML", "srxMatrixHTML",
                   "srxFieldTabHTML", "srxSavebar", "srxExportEvidence",
                   "非原站截图", "未供", "未采", "探针未评估"):
        assert needle in src, needle
    # 价差拼接必须加括号：裸 `'+Math.max(...)-mn` 会把整串转数字得 NaN
    assert "Math.max(...g.map(x=>Number(x.price)||0))-mn" in src
    assert "Math.max(...g.map(x=>x.price))-mn+' 元" not in src
