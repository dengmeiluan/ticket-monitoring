# -*- coding: utf-8 -*-
"""v1.5.295: auto radar runs seed once then alert on a real drop."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp="", **kw):
        self.sent.append((title, desp))
        return True


class _Alerter:
    user = "u"

    def __init__(self):
        self.notifier = _Notifier()

    def _in_quiet(self):
        return False


def _res(price, status="ok"):
    return {
        "dates": [{"date": "2026-11-01", "by_channel": {"ctrip": {
            "price": price, "to": "BJS", "basis": "bare",
            "kind": "calendar", "link": ""}}}],
        "channels": {"ctrip": {"status": status}},
        "query": {"user": "u", "from": "SHA", "to": "BJS",
                  "nationwide": False, "start": "2026-11-01",
                  "end": "2026-11-07", "channels": ["ctrip"]},
    }


def test_auto_seed_then_new_low_alerts_once(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "a.db")}}
    webui._State.alerters = [al]
    PriceStorage(str(tmp_path / "a.db")).set_radar_alert_config(
        "u", {"enabled": True, "drop_min": 50, "threshold": 0,
              "cooldown_h": 12})
    try:
        webui._radar_save_result(_res(500), source="auto")
        assert al.notifier.sent == []
        webui._radar_save_result(_res(450), source="auto")
        assert len(al.notifier.sent) == 1
        st = PriceStorage(str(tmp_path / "a.db"))
        assert len(st.radar_alerts("u")) == 1
        assert st.radar_alerts("u")[0]["kind"] == "new_low"
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_manual_and_cache_runs_never_alert(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "b.db")}}
    webui._State.alerters = [al]
    try:
        webui._radar_save_result(_res(500), source="manual")
        webui._radar_save_result(_res(400, status="cache_hit"), source="auto")
        assert al.notifier.sent == []       # cached run must not seed/alert
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_auto_uses_eligible_channels_only(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "c.db")}}
    webui._State.alerters = [al]
    try:
        hit = _res(500)
        hit["channels"]["ctrip"]["cache_hit"] = True
        webui._radar_save_result(hit, source="auto")
        st = PriceStorage(str(tmp_path / "c.db"))
        assert st.radar_alerts("u") == []
        assert st.radar_history("u")["last_run"]["status"] == "cache_hit"
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_alert_api_and_ui_source_pins():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    for s in ("/api/radar/alert-config", "/api/radar/alerts",
              "spRadarAlertOn", "spAlertSave", "提醒：",
              "_radar_eval_alerts", "no_notifier"):
        assert s in src, s
