# -*- coding: utf-8 -*-
"""v1.5.295: radar alert config/state/history persistence."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def test_alert_config_defaults_and_upsert(tmp_path):
    st = PriceStorage(str(tmp_path / "cfg.db"))
    assert st.radar_alert_config("u") == {
        "enabled": False, "drop_min": 50.0, "threshold": 0.0,
        "cooldown_h": 12.0}
    st.set_radar_alert_config("u", {
        "enabled": False, "drop_min": 80, "threshold": 450,
        "cooldown_h": 6})
    assert st.radar_alert_config("u") == {
        "enabled": False, "drop_min": 80.0, "threshold": 450.0,
        "cooldown_h": 6.0}


def test_alert_state_upsert_and_history(tmp_path):
    st = PriceStorage(str(tmp_path / "st.db"))
    st.save_radar_alert_state("u", "q", "2026-11-01", 500,
                              "2026-10-24T10:00:00", "ctrip", "bare")
    got = st.get_radar_alert_state("u", "q", "2026-11-01")
    assert got["low_price"] == 500 and got["armed"] == 1
    st.save_radar_alert_state("u", "q", "2026-11-01", 450,
                              "2026-10-24T12:00:00", "fliggy", "bare",
                              450, "2026-10-24T12:00:00", 0)
    got = st.get_radar_alert_state("u", "q", "2026-11-01")
    assert got["low_price"] == 450 and got["armed"] == 0
    assert got["low_channel"] == "fliggy"
    rid = st.record_radar_alert(
        "u", "q", "2026-11-01", 450, 500, "fliggy", "bare", "new_low",
        "", "[]", "sent")
    assert rid > 0
    alerts = st.radar_alerts("u")
    assert alerts[0]["kind"] == "new_low" and alerts[0]["status"] == "sent"
