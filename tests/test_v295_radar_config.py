# -*- coding: utf-8 -*-
"""v1.5.295 batch 1: radar config must survive runtime user build."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from main import build_users  # noqa: E402


def test_build_users_keeps_special_radar_without_routes():
    cfg = {"users": [{"name": "u", "special_radar": {
        "enabled": True, "from": "SHA", "start": "2026-11-01",
        "end": "2026-11-07", "channels": ["ctrip"]}}]}
    users = build_users(cfg)
    assert users and users[0]["special_radar"]["from"] == "SHA"


def test_build_users_legacy_single_user_keeps_special_radar():
    cfg = {"special_radar": {"enabled": True, "from": "SHA",
                             "start": "2026-11-01", "end": "2026-11-07"}}
    users = build_users(cfg)
    assert users and users[0]["special_radar"]["from"] == "SHA"


def test_start_web_exposes_alerters():
    assert "alerters" in inspect.signature(webui.start_web).parameters
    assert hasattr(webui._State, "alerters")
