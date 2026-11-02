# -*- coding: utf-8 -*-
"""Pure radar alert decision rules."""
from datetime import datetime, timedelta

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.radar_alerts import RadarAlertCfg, evaluate  # noqa: E402

NOW = datetime(2026, 10, 24, 12, 0, 0)


def test_seed_new_low_cooldown_and_threshold():
    cfg = RadarAlertCfg(drop_min=30, cooldown_h=12)
    d = evaluate(None, "", 500, "bare", 1, None, NOW, cfg)
    assert d.action == "seed" and d.armed == 1
    d = evaluate(500, "bare", 460, "bare", 1, None, NOW, cfg)
    assert d.action == "new_low" and d.prev_low == 500
    d = evaluate(460, "bare", 420, "bare", 1,
                 (NOW - timedelta(hours=2)).isoformat(), NOW, cfg)
    assert d.action == "none"
    d = evaluate(460, "bare", 420, "bare", 1,
                 (NOW - timedelta(hours=13)).isoformat(), NOW, cfg)
    assert d.action == "new_low"


def test_small_drop_does_not_alert():
    cfg = RadarAlertCfg(drop_min=50)
    d = evaluate(500, "bare", 480, "bare", 1, None, NOW, cfg)
    assert d.action == "none"


def test_basis_switch_never_alerts():
    d = evaluate(500, "bare", 400, "tax_included", 1, None, NOW,
                 RadarAlertCfg(drop_min=10))
    assert d.action == "basis_reset"


def test_threshold_disarms_and_rearms():
    cfg = RadarAlertCfg(threshold=450, drop_min=10, cooldown_h=1)
    d = evaluate(500, "bare", 440, "bare", 1, None, NOW, cfg)
    assert d.action == "threshold" and d.armed == 0
    d = evaluate(440, "bare", 430, "bare", 0, NOW.isoformat(), NOW, cfg)
    assert d.action == "none"
    d = evaluate(430, "bare", 480, "bare", 0, NOW.isoformat(), NOW, cfg)
    assert d.action == "rearm" and d.armed == 1


def test_disabled_never_alerts():
    d = evaluate(None, "", 500, "bare", 1, None, NOW,
                 RadarAlertCfg(enabled=False))
    assert d.action == "none"
