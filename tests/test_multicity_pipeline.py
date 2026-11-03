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
            extra=json.dumps(build_mc_extra(LEGS), ensure_ascii=False),
            prov=json.dumps({"path": "多程",
                             "url": "https://flights.ctrip.com/online/list/"
                                    "multi-sha-tyo-tyo-osa"},
                            ensure_ascii=False))]


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
    assert "flights.ctrip.com" in kw["prov"], "来源页必须随行落库"


def test_collect_multicity_holds_ctrip_channel_slot(monkeypatch):
    """多程轮尾也必须走渠道闸门，不能与主扫描/预热叠开浏览器。"""
    from contextlib import contextmanager

    seen = []

    @contextmanager
    def _slot(name):
        seen.append(name)
        yield

    monkeypatch.setattr(main, "channel_slot", _slot)
    s = S()
    users = [{"platforms": ["ctrip"], "routes": [_route()]}]
    assert main.collect_multicity(users, [C()], s, logging.getLogger("mc"),
                                  today="2026-11-01") == 1
    assert seen == ["ctrip"]


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


def test_multi_wait_polls_until_total_appears_with_deadline():
    """组合卡异步渲染：固定等 9s 会假空（开口程实测 12s 才出总价）。

    以「多程含税价」为就绪锚轮询；始终没有总价时受 deadline 约束返回
    最后一次文本，不能死等。
    """
    from crawlers.ctrip import _multi_text_with_total

    class Page:
        def __init__(self, texts):
            self.texts = texts
            self.calls = 0

        def wait_for_timeout(self, ms):
            self.calls += 1

        def inner_text(self, sel):
            return self.texts[min(self.calls, len(self.texts) - 1)]

    p = Page(["多程超低价", "多程超低价", "¥2184\n多程含税价"])
    got = _multi_text_with_total(p, "多程超低价", extra_s=1.0, step_ms=1)
    assert "多程含税价" in got
    assert p.calls == 2, "总价出现后必须停轮询"

    empty = Page(["多程超低价"])
    got = _multi_text_with_total(empty, "多程超低价", extra_s=0.01,
                                 step_ms=1)
    assert "多程含税价" not in got
    assert empty.calls >= 1, "没有总价时也要实际等过一轮"
