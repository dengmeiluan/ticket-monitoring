# -*- coding: utf-8 -*-
"""r916：途牛官方 H5 日历接入与矩阵纠偏。

2026-11-03 真实 H5 搜索流点「查询/日历」触发
`query/flight/v1/calendar`（type=1），返回 125 个逐日价
（2026-11-03..2027-08-25，¥360–1790，11-05 ¥420，裸价不含税）。
r805z 只扫了 `crawlers/tuniu.py`，漏掉 `crawlers/special.py`
里特价雷达已在用的同名接口，把 calendar 误记 n。
"""
import io
import logging

import crawlers.special as special
from crawlers.tuniu import TuniuCrawler
from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                           DIMENSION_SCOPE)


def _crawler():
    return TuniuCrawler({}, logging.getLogger("test_r916"))


def test_calendar_calls_official_h5_api_and_records_path(monkeypatch):
    calls = []

    def fake(fc, tc, date, logger, **kw):
        calls.append((fc, tc, date))
        return [{"date": "2026-11-05", "price": 420},
                {"date": "2026-11-06", "price": 380}]

    monkeypatch.setattr(special, "fetch_tuniu_calendar", fake)
    c = _crawler()
    rows = c.calendar("SHA", "BJS", "2026-11-05")
    assert len(rows) == 2 and rows[0]["price"] == 420
    assert calls == [("SHA", "BJS", "2026-11-05")]
    rec = c.paths[-1]
    assert rec["path"] == "日历" and rec["status"] == "calendar"
    assert rec["rows"] == 2 and "裸价" in rec["detail"]


def test_calendar_intl_is_unsupported_without_network(monkeypatch):
    called = []
    monkeypatch.setattr(special, "fetch_tuniu_calendar",
                        lambda *a, **k: called.append(1) or [])
    c = _crawler()
    assert c.calendar("SHA", "BKK", "2026-11-05") == []
    assert not called
    rec = c.paths[-1]
    assert rec["path"] == "日历" and rec["status"] == "unsupported"


def test_calendar_none_and_empty_are_not_ok(monkeypatch):
    c = _crawler()
    monkeypatch.setattr(special, "fetch_tuniu_calendar",
                        lambda *a, **k: None)
    assert c.calendar("SHA", "BJS", "2026-11-05") == []
    assert c.paths[-1]["status"] == "error"
    monkeypatch.setattr(special, "fetch_tuniu_calendar",
                        lambda *a, **k: [])
    assert c.calendar("SHA", "BJS", "2026-11-05") == []
    assert c.paths[-1]["status"] == "empty"


def test_official_endpoint_is_the_one_the_page_calls():
    src = io.open("crawlers/special.py", encoding="utf-8").read()
    assert "flight-api.tuniu.com/query/flight/v1/calendar" in src
    assert '"type": "1"' in src


def test_matrix_and_special_capability_expose_tuniu_calendar():
    assert CHANNEL_DIMENSIONS["tuniu"]["calendar"] == "y"
    assert DIMENSION_SCOPE.get(("tuniu", "calendar")) == "仅国内"
    assert ("tuniu", "calendar") in DIMENSION_NOTES
    from core.specials import SPECIAL_CAPABILITY
    srcs = SPECIAL_CAPABILITY["tuniu"]["sources"]
    assert "tuniucal" in srcs and "tuniu" in srcs