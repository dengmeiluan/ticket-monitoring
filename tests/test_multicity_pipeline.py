# -*- coding: utf-8 -*-
"""多程轮尾采集接线：去重、只 Ctrip、只落渠道整单总价。"""
import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.multicity import build_mc_extra, segments_key  # noqa: E402

SEGS = [{"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "TYO", "to": "OSA", "date": "2026-11-23"}]
LEGS = [{"flight_no": "9C8515", "airline": "春秋航空", "from": "SHA",
         "to": "TYO", "date": "2026-11-20", "dep": "21:10",
         "arr": "01:05"},
        {"flight_no": "MM304", "airline": "日本乐桃航空", "from": "TYO",
         "to": "OSA", "date": "2026-11-23", "dep": "07:30",
         "arr": "09:10"}]


class C:
    name = "ctrip"

    def __init__(self):
        self.calls = []

    def fetch_multi(self, segs):
        self.calls.append(segs)
        return [FlightPrice(
            platform="ctrip", from_city="SHA", to_city="OSA",
            depart_date="2026-11-20", price=1298.0,
            extra=json.dumps(build_mc_extra(LEGS), ensure_ascii=False))]


class S:
    def __init__(self):
        self.rows = []

    def save_itinerary(self, *a, **k):
        self.rows.append((a, k))
        return segments_key(SEGS)


def _route():
    return Route("SHA", "上海", "OSA", "大阪", [], segments=SEGS)


def test_collect_multicity_dedups_and_saves_page_total():
    c, s = C(), S()
    users = [{"platforms": ["ctrip"], "routes": [_route()]},
             {"platforms": ["ctrip"], "routes": [_route()]}]
    n = main.collect_multicity(users, [c], s, logging.getLogger("mc"),
                               today="2026-11-01")
    assert n == 1
    assert len(c.calls) == 1
    assert len(s.rows) == 1
    args, kw = s.rows[0]
    assert args[0] == "ctrip" and args[1] == segments_key(SEGS)
    assert args[3] == 1298.0
    assert kw["depart_date"] == "2026-11-20"


def test_collect_multicity_skips_without_ctrip_or_after_expiry():
    s = S()
    users = [{"platforms": ["ctrip"], "routes": [_route()]}]
    assert main.collect_multicity(users, [], s, logging.getLogger("mc"),
                                  today="2026-11-01") == 0
    assert main.collect_multicity(users, [C()], s, logging.getLogger("mc"),
                                  today="2026-12-01") == 0
    no_ctrip = [{"platforms": ["qunar"], "routes": [_route()]}]
    c = C()
    assert main.collect_multicity(no_ctrip, [c], s, logging.getLogger("mc"),
                                  today="2026-11-01") == 0
    assert c.calls == [], "用户没勾携程不得替他采"
    assert s.rows == []
