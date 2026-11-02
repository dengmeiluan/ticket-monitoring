# -*- coding: utf-8 -*-
"""r815h：同程国内往返走 book1/roundtrips 的产品 atp，不自己相加。"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

from crawlers.tongcheng import TongchengCrawler


def _payload(atp=1055, atpd=113, lp=942, fn="CA1835"):
    return {"success": True, "data": {
        "lp": lp,
        "fps": [{
            "fn": fn, "dt": "2026-11-06 07:55",
            "at": "2026-11-06 10:15", "asn": "国航",
            "atp": atp, "atpd": atpd,
        }],
    }}


def _crawler():
    return TongchengCrawler(
        {"user_data_dir": "user_data", "android": {"enabled": True}},
        logging.getLogger("t"))


def test_parse_uses_product_atp_not_sum():
    """接口 atp 就是产品总价；即使 atp 与 lp+atpd 不等也照用 atp。"""
    rows = TongchengCrawler._parse_rt_fps(
        _payload(atp=9999, atpd=113, lp=942)["data"]["fps"], 942,
        "2026-11-03", "2026-11-06")
    assert len(rows) == 1
    assert rows[0]["price"] == 9999.0
    assert rows[0]["return_price"] == 113.0
    assert rows[0]["trip_type"] == "RT"
    assert rows[0]["back_date"] == "2026-11-06"


def test_parse_skips_invalid_or_nonpositive():
    rows = TongchengCrawler._parse_rt_fps(
        [{"atp": 0, "atpd": 1}, {"atp": "x", "atpd": 1},
         {"atp": 1055, "atpd": 0, "fn": "MU5138"}],
        942, "2026-11-03", "2026-11-06")
    assert [r["price"] for r in rows] == [1055.0]


def test_fetch_dom_rt_returns_product_total(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return _payload()

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert len(rows) == 1
    f = rows[0]
    assert f.price == 1055.0
    ex = json.loads(f.extra)
    assert ex["tripType"] == "RT"
    assert ex["backDate"] == "2026-11-06"
    assert ex["outboundLowest"] == 942.0
    assert ex["flight"] == "CA1835"
    assert f.flight_no == "CA1835"
    assert f.depart_time == "07:55" and f.arrive_time == "10:15"
    assert any(p.get("path") == "往返" and p.get("status") == "ok"
               for p in c.paths), c.paths


def test_fetch_ret_date_dispatch_intl_vs_domestic(monkeypatch):
    """ret_date 分支只接管国内；国际仍走 _fetch_intl（不被国内接口劫持）。"""
    c = _crawler()
    seen = {}

    def dom(*a, **k):
        seen["dom"] = (a, k)
        return []

    def intl(*a, **k):
        seen["intl"] = (a, k)
        return []

    monkeypatch.setattr(c, "_fetch_dom_rt", dom)
    monkeypatch.setattr(c, "_fetch_intl", intl)
    c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert "dom" in seen, "国内 ret_date 没走 roundtrips 分支"
    c.fetch("SHA", "BKK", ["2026-11-16"], ret_date="2026-11-20")
    assert "intl" in seen, "国际 ret_date 被国内分支劫持"
    assert seen["intl"][1].get("ret_date") == "2026-11-20"


def test_fetch_dom_rt_http_error_is_error(monkeypatch):
    class R:
        status_code = 502

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert rows == []
    assert any(p.get("path") == "往返" and p.get("status") == "error"
               for p in c.paths), c.paths


def test_fetch_dom_rt_empty_has_reason(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"lp": 942, "fps": []}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert rows == []
    p = [x for x in c.paths if x.get("path") == "往返"][0]
    assert p["status"] == "empty" and "返程" in p["detail"], p
