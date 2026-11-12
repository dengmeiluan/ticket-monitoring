# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r916_tuniu_calendar.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import crawlers.special as special
import io
import logging

from core.channels import CHANNEL_DIMENSIONS, DIMENSION_NOTES, DIMENSION_SCOPE
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r916_tuniu_calendar.py ----

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
