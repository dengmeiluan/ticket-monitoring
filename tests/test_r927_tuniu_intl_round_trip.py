# -*- coding: utf-8 -*-
"""r927：途牛 H5 国际往返只取 productList.avgTotalPrice（渠道含税总价）。"""
import json
import logging
import os

from crawlers.tuniu import TuniuCrawler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tuniu_intl_rt.json")


def _payload():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


def test_parser_uses_channel_total_not_sum():
    p = _payload()
    date, ret = "2026-11-05", "2026-11-08"
    rows = TuniuCrawler._parse_intl_rt_products(
        p["productList"], date, ret)
    assert len(rows) == 35
    best = min(rows, key=lambda r: r["price"])
    assert best["price"] == 3010.0
    assert best["basis"] == "product_round_trip_total"
    assert best["tripType"] == "RT" and best["backDate"] == ret
    assert best["intl"] is True and best["date"] == date
    assert best["depTime"] == "15:25"
    assert best["code"] and best["name"]
    from core.alerter import _flights_from_extra
    fl = _flights_from_extra(rows, date, "tuniu")
    assert len(fl) == len(rows)
    assert fl[0]["depTime"] and fl[0]["intl"] is True


def test_parser_rejects_missing_or_out_of_band_price():
    p = _payload()
    bad = dict(p["productList"][0])
    bad.pop("avgTotalPrice", None)
    assert TuniuCrawler._parse_intl_rt_products(
        [bad], "2026-11-05", "2026-11-08") == []
    bad2 = dict(p["productList"][0])
    bad2["avgTotalPrice"] = 1
    assert TuniuCrawler._parse_intl_rt_products(
        [bad2], "2026-11-05", "2026-11-08") == []


def test_intl_ret_date_dispatches_to_rt():
    c = TuniuCrawler({"headless": True}, logging.getLogger("r927"))
    seen = {}

    def fake(from_city, to_city, dates, ret_date):
        seen["args"] = (from_city, to_city, dates, ret_date)
        return []

    c._fetch_intl_rt = fake
    c.fetch("SHA", "NRT", ["2026-11-05"], ret_date="2026-11-08")
    assert seen["args"] == ("SHA", "NRT", ["2026-11-05"], "2026-11-08")
