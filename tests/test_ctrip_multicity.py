# -*- coding: utf-8 -*-
"""携程 PC 多程 URL/结果解析（真实结果夹具）。"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.multicity import MultiCityError  # noqa: E402
from crawlers.ctrip_multicity import (build_multi_url,  # noqa: E402
                                      parse_multi_text)

SEGS = [{"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "TYO", "to": "OSA", "date": "2026-11-23"}]


def _text():
    return io.open(os.path.join(ROOT, "tests", "fixtures",
                                "ctrip_multicity_result.txt"),
                   encoding="utf-8").read()


def test_build_multi_url_matches_observed_form():
    assert build_multi_url(SEGS) == (
        "https://flights.ctrip.com/online/list/multi-sha-tyo-tyo-osa"
        "?depdate=2026-11-20_2026-11-23&cabin=y_s"
        "&adult=1&child=0&infant=0")


def test_parse_real_combo_card_takes_page_total_and_two_legs():
    got = parse_multi_text(_text(), SEGS)
    assert got["price"] == 1298.0
    assert got["total_basis"] == "page_multicity_total"
    assert [x["flight_no"] for x in got["legs"]] == ["9C8515", "MM304"]
    assert got["legs"][0]["dep"] == "21:10"
    assert got["legs"][0]["arr"] == "01:05"
    assert got["legs"][1]["dep"] == "07:30"
    assert got["legs"][1]["arr"] == "09:10"
    assert got["extra"]["tripType"] == "MC"
    assert all("price" not in x for x in got["extra"]["legs"])


def test_parse_rejects_missing_page_total():
    txt = _text().replace("多程含税价", "含税价")
    with pytest.raises(MultiCityError):
        parse_multi_text(txt, SEGS)


def test_parse_rejects_leg_count_mismatch():
    segs3 = SEGS + [{"from": "OSA", "to": "SHA", "date": "2026-11-26"}]
    with pytest.raises(MultiCityError):
        parse_multi_text(_text(), segs3)


def test_fetch_multi_wires_parser_and_returns_flight_price(monkeypatch):
    import logging
    from crawlers.ctrip import CtripCrawler

    class Page:
        def goto(self, *a, **k):
            pass

        def wait_for_timeout(self, *a):
            pass

        def inner_text(self, *a):
            return _text()

    class Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(CtripCrawler, "browser", lambda self, *a, **k: Ctx())
    monkeypatch.setattr(CtripCrawler, "new_page", lambda self, ctx: Page())
    c = CtripCrawler({}, logging.getLogger("mc"))
    c.paths = []
    rows = c.fetch_multi(SEGS)
    assert len(rows) == 1
    row = rows[0]
    assert row.price == 1298.0
    assert row.from_city == "SHA" and row.to_city == "OSA"
    assert '"tripType": "MC"' in row.extra
    assert any(x.get("path") == "多程" and x.get("status") == "ok"
               for x in c.paths)
