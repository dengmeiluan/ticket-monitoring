# -*- coding: utf-8 -*-
"""r368: probe login refusal must reach the session slot (not only ticket)."""
import logging
import time
from datetime import datetime

import crawlers
import webui


def _setcfg(tmp_path):
    return {"crawler": {"user_data_dir": str(tmp_path)}}


def test_probe_login_refusal_marks_login_required(tmp_path, monkeypatch):
    """A real 1999 login wall must flip the session to 需登录, not stay 可用."""
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    old_reg = crawlers.REGISTRY.get("qunar")
    webui._State.cfg = _setcfg(tmp_path)
    webui._State.logger = logging.getLogger("test-r368")
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    webui._State.login_sessions.clear()
    webui._State.login_pending.clear()

    class _Wall:
        name = "qunar"

        def __init__(self, cfg, logger):
            self.paths = []
            self.probe_mode = False
            self.on_path = None

        def login_url(self):
            return ""

        def fetch(self, fc, tc, dates):
            self.paths = [{
                "path": "H5", "status": "login", "rows": 0,
                "date": dates[0],
                "detail": "国际列表 1999/8 未登录硬拒",
            }]
            return []

    crawlers.REGISTRY["qunar"] = _Wall
    webui._PROBE_LAST = 0
    try:
        webui._probe_search(None, None, None, ["qunar"], legs=[{
            "from": "上海", "to": "曼谷", "date": "2026-10-24"}])
        per = webui._PROBE_AUTH["qunar"]["international"]
        assert per.get("auth_ts")
        assert per["auth_reason"].startswith("国际列表")
        view = webui._login_state_view()["plats"]["qunar"]
        scope = view["scopes"]["international"]
        assert scope["needs_login"] is True, "登录墙未进入会话证据"
        assert scope["detail_available"] is False
        assert "1999" in scope["reason"]
        assert view["needs_login"] is True
        assert view["status"] == "login_required"
    finally:
        if old_reg is None:
            crawlers.REGISTRY.pop("qunar", None)
        else:
            crawlers.REGISTRY["qunar"] = old_reg
        webui._State.cfg = old_cfg
        webui._State.logger = old_logger
        webui._PROBE_AUTH.clear()
        webui._PROBE_LAST = 0
        webui._State.login_sessions.clear()
        webui._State.login_pending.clear()


def test_newer_probe_detail_clears_login_refusal(tmp_path, monkeypatch):
    """After a real detail arrives, the same scope must go back to available."""
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    webui._State.cfg = _setcfg(tmp_path)
    webui._State.logger = logging.getLogger("test-r368b")
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    webui._State.login_sessions.clear()
    webui._State.login_pending.clear()
    try:
        now = time.time()
        webui._record_probe_auth_reject(
            "qunar", "international", "国际列表 1999/8 未登录硬拒",
            "SHA", "BKK", "2026-10-24", "H5")
        view = webui._login_state_view()["plats"]["qunar"]
        assert view["needs_login"] is True
        webui._record_probe_auth(
            "qunar", "international", 9, "SHA", "BKK", "2026-10-25")
        # force the new detail to be strictly newer than the refusal
        webui._PROBE_AUTH["qunar"]["international"]["detail_ts"] = now + 5
        webui._PROBE_AUTH["qunar"]["international"]["detail_at"] = (
            datetime.fromtimestamp(now + 5).strftime("%Y-%m-%d %H:%M:%S"))
        view = webui._login_state_view()["plats"]["qunar"]
        scope = view["scopes"]["international"]
        assert scope["needs_login"] is False
        assert scope["detail_available"] is True
        assert view["status"] == "available"
    finally:
        webui._State.cfg = old_cfg
        webui._State.logger = old_logger
        webui._PROBE_AUTH.clear()
        webui._State.login_sessions.clear()
        webui._State.login_pending.clear()


def test_empty_or_timeout_never_marks_login(tmp_path, monkeypatch):
    """Empty/calendar/timeout paths must not be recorded as auth evidence."""
    old_cfg = getattr(webui._State, "cfg", None)
    webui._State.cfg = _setcfg(tmp_path)
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    try:
        webui._record_probe_auth_reject("qunar", "international", "", "SHA", "BKK", "2026-10-24")
        assert not webui._PROBE_AUTH
    finally:
        webui._State.cfg = old_cfg
        webui._PROBE_AUTH.clear()
