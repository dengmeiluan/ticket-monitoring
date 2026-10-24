"""Current channel authentication follows dated evidence, not empty fares."""
import logging
import threading
import time
from datetime import datetime

import pytest

import webui
from crawlers import REGISTRY


@pytest.fixture
def channels(monkeypatch, tmp_path):
    saved_at = 1700001000.0

    class Channel:
        login_suspect = False

        def __init__(self, cfg, logger):
            self.user_data_root = cfg.get("user_data_dir", str(tmp_path))

        @property
        def session_saved_at(self):
            return saved_at

    for platform in REGISTRY:
        (tmp_path / platform).mkdir()
        (tmp_path / platform / "marker").write_text("profile")
        monkeypatch.setitem(REGISTRY, platform, Channel)
    monkeypatch.setattr(webui._State, "cfg", {"crawler": {"user_data_dir": str(tmp_path)}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("channel-test"))
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"rounds": [], "evidence": {}})
    return Channel


def stamp(value):
    return datetime.fromtimestamp(1700000000 + value).strftime("%Y-%m-%d %H:%M:%S")


def test_new_saved_session_does_not_inherit_previous_auth_failure(channels, monkeypatch):
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [{"plats": {"tongcheng": {"need_login": True}}}],
        "evidence": {"tongcheng": {"international": {
            "auth_at": stamp(900), "detail_at": "", "auth_reason": "需要登录"}}}})
    state = webui._login_state_view()["plats"]["tongcheng"]
    assert state["needs_login"] is False
    assert state["status"] == "saved"
    assert state["saved_at"] == 1700001000.0


def test_new_auth_failure_overrides_pending_and_is_scope_specific(channels, monkeypatch):
    webui._State.login_pending["tongcheng"] = time.time()
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"tongcheng": {
            "international": {"auth_at": stamp(1100), "detail_at": "", "auth_reason": "需要登录"},
            "domestic": {"auth_at": "", "detail_at": stamp(1200), "auth_reason": ""}}}})
    state = webui._login_state_view()["plats"]["tongcheng"]
    assert state["needs_login"] is True
    assert state["status"] == "login_required"
    assert state["scopes"]["international"]["needs_login"] is True
    assert state["scopes"]["domestic"]["needs_login"] is False


def test_latest_evidence_is_per_channel_not_global_last_round(channels, monkeypatch):
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [{"plats": {"ctrip": {"need_login": False}}}],
        "evidence": {"fliggy": {"domestic": {
            "auth_at": stamp(1100), "detail_at": "", "auth_reason": "需要登录"}}}})
    assert webui._login_state_view()["plats"]["fliggy"]["needs_login"] is True


def test_same_scope_later_details_resolve_previous_rejection(channels, monkeypatch):
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"ctrip": {"international": {
            "auth_at": stamp(1100), "detail_at": stamp(1200), "auth_reason": "需要登录"}}}})
    state = webui._login_state_view()["plats"]["ctrip"]
    assert state["needs_login"] is False
    assert state["status"] == "available"


def test_active_login_suppresses_duplicate_login_action(channels, monkeypatch):
    webui._State.login_sessions["fliggy"] = {"evt": threading.Event(), "saving": True}
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"fliggy": {"unknown": {
            "auth_at": stamp(1100), "detail_at": "", "auth_reason": "需要登录"}}}})
    state = webui._login_state_view()["plats"]["fliggy"]
    assert state["status"] == "saving"
    assert state["needs_login"] is False


def test_profile_and_no_fares_do_not_prove_authentication(channels):
    state = webui._login_state_view()["plats"]["tuniu"]
    assert state["saved"] is True
    assert state["status"] == "saved"
    assert state["needs_login"] is False


def test_finish_only_acknowledges_save_request_until_worker_completes(channels):
    session = {"evt": threading.Event(), "done": threading.Event()}
    webui._State.login_sessions["fliggy"] = session
    result = webui._finish_login("fliggy")
    assert result["ok"] is True
    assert result["saving"] is True
    assert result["saved"] is False
    assert session["evt"].is_set()
    assert "fliggy" not in webui._State.login_pending


def test_login_worker_failure_is_reported_instead_of_saved(channels, monkeypatch):
    def fail(self, event, *args, **kwargs):
        raise OSError("profile save failed")
    monkeypatch.setattr(channels, "_login_window", fail, raising=False)
    assert webui._start_login("fliggy")["ok"] is True
    deadline = time.monotonic() + 2
    while webui._State.login_sessions and time.monotonic() < deadline:
        time.sleep(0.01)
    state = webui._login_state_view()["plats"]["fliggy"]
    assert state["status"] == "save_error"
    assert state["error"]
    assert "fliggy" not in webui._State.login_pending


def test_web_login_uses_boot_profile_until_restart(channels, monkeypatch, tmp_path):
    monkeypatch.setattr(webui._State, "boot_cfg", {"crawler": {"user_data_dir": str(tmp_path)}})
    monkeypatch.setattr(webui._State, "cfg", {"crawler": {"user_data_dir": str(tmp_path / "future")}})
    assert webui._login_state_view()["plats"]["ctrip"]["saved"] is True


def test_new_rejection_allows_relogin_during_previous_pending_window(channels, monkeypatch):
    webui._State.login_pending["fliggy"] = time.time()
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"fliggy": {"international": {
            "auth_at": stamp(1100), "detail_at": "", "auth_reason": "需要登录"}}}})
    monkeypatch.setattr(channels, "_login_window", lambda self, evt, *args, **kwargs: evt.wait(2), raising=False)
    result = webui._start_login("fliggy")
    session = webui._State.login_sessions.get("fliggy")
    try:
        assert result["ok"] is True
    finally:
        if session:
            session["evt"].set()
            assert session["done"].wait(2)


def test_saved_session_stays_saved_if_cache_callback_fails(channels, monkeypatch):
    monkeypatch.setattr(channels, "_login_window", lambda self, evt, *args, **kwargs: evt.wait(2), raising=False)
    def failed_callback(platform):
        raise RuntimeError("cache reset failed")
    monkeypatch.setattr(webui._State, "login_saved_cb", failed_callback)
    assert webui._start_login("fliggy")["ok"] is True
    session = webui._State.login_sessions["fliggy"]
    webui._finish_login("fliggy")
    assert session["done"].wait(2)
    assert session["saved"] is True
    assert "fliggy" not in webui._State.login_errors
    assert "fliggy" in webui._State.login_pending


def test_future_saved_timestamp_cannot_mask_current_rejection(channels, monkeypatch):
    """未来 saved_at（快照恢复/错时钟）不能把所有认证拒绝压成旧证据。"""
    monkeypatch.setattr(channels, "session_saved_at",
                        property(lambda self: time.time() + 86400))
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"qunar": {"international": {
            "auth_at": stamp(1100), "detail_at": "",
            "auth_reason": "需要登录"}}}})
    state = webui._login_state_view()["plats"]["qunar"]
    assert state["saved_at"] == 0.0
    assert state["needs_login"] is True
    assert state["status"] == "login_required"


def test_current_rejection_outranks_stale_save_error(channels, monkeypatch):
    """旧保存失败不能盖住采集端最新的明确认证拒绝。"""
    webui._State.login_errors["qunar"] = "旧保存失败"
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "evidence": {"qunar": {"international": {
            "auth_at": stamp(1100), "detail_at": "",
            "auth_reason": "需要登录"}}}})
    state = webui._login_state_view()["plats"]["qunar"]
    assert state["status"] == "login_required"
    assert state["needs_login"] is True
