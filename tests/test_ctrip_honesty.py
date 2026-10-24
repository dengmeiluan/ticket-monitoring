# -*- coding: utf-8 -*-
"""携程数据诚实门（INTL_DESIGN §5/§10）：三处「不装懂」回归钉。

- 往返（ret_date）：Ctrip 无回程查询，不得用单程价冒充往返总价，
  不发查询、落 unsupported 证据、返回空；
- 机场级航线（PVG/NRT）：城市日历（SHA/TYO）无机场维度，机场级
  缺口不得用城市日历价回填（跨机场串价），城市级航线行为不变；
- 国内 H5 起飞日门：滚动/推荐位行（ddate 非请求日）剔除；仅在行内
  确有日期字段时过滤，无日期字段不臆造。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_ctrip_honesty.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import FlightPrice  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_ctrip_honesty")


def _crawler():
    return CtripCrawler({}, _LOG)


def _cal_row(date="2026-11-16", price=1100):
    return FlightPrice(platform="ctrip", from_city="SHA", to_city="TYO",
                       depart_date=date, price=price, flight_no="",
                       depart_time="", arrive_time="", extra="[]")


# ---- 1. 往返诚实：不发单程查询 ----

def test_fetch_ret_date_unsupported_no_oneway_query(monkeypatch):
    c = _crawler()

    def boom(*_a, **_k):
        raise AssertionError("往返请求不得发起单程查询/浏览器")

    monkeypatch.setattr(c, "browser", boom)
    # 国内、国际两条分流都必须在浏览器前短路
    for frm, to in (("SHA", "CAN"), ("SHA", "TYO")):
        out = c.fetch(frm, to, ["2026-11-10"], ret_date="2026-11-15")
        assert out == []
        notes = [p for p in c.paths if p["path"] == "TRIP"]
        assert len(notes) == 1, c.paths
        assert notes[0]["status"] == "unsupported"
        assert notes[0]["detail"] == "往返明细暂不支持，未发起单程查询"


def test_fetch_single_trip_reaches_query_paths(monkeypatch):
    """ret_date 为空时正常分流查询，且不落 TRIP 短路证据。"""
    c = _crawler()
    seen = {}

    def fake_intl(frm, to, dates):
        seen["args"] = (frm, to, list(dates))
        return []

    monkeypatch.setattr(c, "_fetch_intl", fake_intl)
    assert c.fetch("SHA", "TYO", ["2026-11-10"]) == []
    assert seen["args"] == ("SHA", "TYO", ["2026-11-10"])
    assert [p for p in c.paths if p["path"] == "TRIP"] == []


# ---- 2. 机场级航线不回填城市日历 ----

def test_airport_level_route_skips_city_calendar(monkeypatch):
    c = _crawler()
    calls = {"list": 0, "cal": 0}

    def fake_list(*_a):
        calls["list"] += 1
        return []

    def fake_cal(*_a):
        calls["cal"] += 1
        return [_cal_row()]

    monkeypatch.setattr(c, "_fetch_intl_list", fake_list)
    monkeypatch.setattr(c, "_fetch_intl_calendar", fake_cal)

    c.path_reset()
    out = c._fetch_intl("PVG", "NRT", ["2026-11-16"])
    assert out == []
    assert calls == {"list": 1, "cal": 0}
    notes = [p for p in c.paths if p["path"] == "日历"]
    assert len(notes) == 1, c.paths
    assert notes[0]["date"] == "2026-11-16"
    assert notes[0]["status"] == "empty"
    assert notes[0]["detail"] == "机场级航线不回填城市日历价"

    # 单端机场级（SHA→NRT）同判：城市日历只覆盖城市对，不能补
    calls.update(list=0, cal=0)
    assert c._fetch_intl("SHA", "NRT", ["2026-11-16"]) == []
    assert calls == {"list": 1, "cal": 0}


def test_city_level_route_still_backfills_calendar(monkeypatch):
    """城市级（SHA→TYO）缺日仍走日历兜底，存量行为不变。"""
    c = _crawler()
    calls = {"cal": 0}

    monkeypatch.setattr(c, "_fetch_intl_list", lambda *_a: [])
    monkeypatch.setattr(c, "_fetch_intl_calendar",
                        lambda *_a: (calls.update(cal=calls["cal"] + 1),
                                     [_cal_row()])[1])
    c.path_reset()
    out = c._fetch_intl("SHA", "TYO", ["2026-11-16"])
    assert calls["cal"] == 1
    assert len(out) == 1 and out[0].price == 1100
    assert [p for p in c.paths if p["path"] == "日历"] == []


# ---- 3. 国内 H5 起飞日门 ----

def test_filter_date_scope_only_filters_rows_with_date():
    rows = [
        {"code": "MU1", "depDate": "2026-11-10"},   # 匹配
        {"code": "MU2", "depDate": "2026-11-09"},   # 滚动行，剔
        {"code": "MU3"},                             # 无日期字段，保留
        {"code": "MU4", "date": "2026-11-11"},      # 异名日期字段，剔
        {"code": "MU5", "depDate": "未知"},          # 非法日期，不硬判
    ]
    kept, dropped = CtripCrawler._filter_date_scope(rows, "2026-11-10")
    assert dropped == 2
    assert [r["code"] for r in kept] == ["MU1", "MU3", "MU5"]
    assert CtripCrawler._filter_date_scope([], "2026-11-10") == ([], 0)


def test_domestic_parser_rows_carry_date_field_and_filter():
    """解析器原生输出 depDate；请求日不同即被门剔除（非臆造字段）。"""
    item = {"mutilstn": [{
                "basinfo": {"flgno": "MU5101"},
                "dateinfo": {"ddate": "2026-11-09 08:00:00",
                             "adate": "2026-11-09 10:30:00"},
                "dportinfo": {"aport": "SHA", "bsname": "T2"},
                "aportinfo": {"aport": "CAN", "bsname": "T1"}}],
            "policyinfo": [{"quantity": 3, "tprice": 800.0, "drate": 5.0}]}
    rows = _crawler()._extract_ctrip_flights(
        json.dumps({"fltitem": [item]}))
    assert rows and rows[0]["depDate"] == "2026-11-09"
    kept, dropped = CtripCrawler._filter_date_scope(rows, "2026-11-10")
    assert kept == [] and dropped == 1
    kept2, dropped2 = CtripCrawler._filter_date_scope(rows, "2026-11-09")
    assert len(kept2) == 1 and dropped2 == 0
