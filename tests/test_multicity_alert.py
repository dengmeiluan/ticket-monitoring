# -*- coding: utf-8 -*-
"""多程整单提醒：只认渠道整单总价，按行程去抖，通知失败可重试。"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402
from core.multicity import segments_key  # noqa: E402
from core.storage import PriceStorage  # noqa: E402

SEGS = [{"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "TYO", "to": "OSA", "date": "2026-11-23"}]
LEGS = [{"flight_no": "9C8515", "from": "SHA", "to": "TYO",
         "date": "2026-11-20", "dep": "21:10", "arr": "01:05"},
        {"flight_no": "MM304", "from": "TYO", "to": "OSA",
         "date": "2026-11-23", "dep": "07:30", "arr": "09:10"}]
KEY = segments_key(SEGS)


class Notifier:
    def __init__(self, res=True):
        self.res = res
        self.sent = []

    def send(self, title, desp):
        self.sent.append((title, desp))
        return self.res


def _user(thr=1500):
    return {"name": "u", "routes": [{
        "from": "SHA", "to": "OSA", "dates": ["2026-11-20", "2026-11-23"],
        "alert_threshold": thr, "segments": SEGS}]}


def _db(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_itinerary("ctrip", KEY, SEGS, 1298.0, LEGS)
    return st


def test_alerts_once_then_only_on_further_drop(tmp_path):
    st, n = _db(tmp_path), Notifier()
    u = _user()
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 1
    title, desp = n.sent[0]
    assert "SHA→TYO→OSA" in title and "1298" in title
    assert "多程含税价" in desp and "9C8515" in desp and "MM304" in desp
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 0, "同价不得刷屏"

    st.save_itinerary("ctrip", KEY, SEGS, 1200.0, LEGS)
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 1, "继续下探应补推"
    assert len(n.sent) == 2


def test_above_threshold_resets_so_next_crossing_alerts(tmp_path):
    st, n = _db(tmp_path), Notifier()
    u = _user()
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 1
    st.save_itinerary("ctrip", KEY, SEGS, 1600.0, LEGS)
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 0
    assert st.get_alert_state("mc|u|%s|1500" % KEY) == 0
    st.save_itinerary("ctrip", KEY, SEGS, 1400.0, LEGS)
    assert webui._multicity_alert_round(
        u, n, st, logging.getLogger("mc")) == 1
    assert len(n.sent) == 2


def test_no_threshold_stale_and_rejected_are_silent(tmp_path):
    st, n = _db(tmp_path), Notifier()
    assert webui._multicity_alert_round(
        _user(0), n, st, logging.getLogger("mc")) == 0

    st.save_itinerary("ctrip", KEY, SEGS, 900.0, LEGS,
                      fetched_at="2020-01-01 00:00:00")
    assert webui._multicity_alert_round(
        _user(), n, st, logging.getLogger("mc")) == 0, "过期行不得提醒"

    st.save_itinerary("ctrip", KEY, SEGS, 1000.0, LEGS)
    bad = Notifier(res=False)
    assert webui._multicity_alert_round(
        _user(), bad, st, logging.getLogger("mc")) == 0
    assert len(bad.sent) == 1
    assert st.get_alert_state("mc|u|%s|1500" % KEY) is None, \
        "发送未被接受不得写去抖状态"
    ok = Notifier()
    assert webui._multicity_alert_round(
        _user(), ok, st, logging.getLogger("mc")) == 1
