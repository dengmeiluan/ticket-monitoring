# -*- coding: utf-8 -*-
"""P0 control-plane closure: shared channel gate, retry cooldown,
calendar-only/session_busy status, login-window close detection."""
import inspect
import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _log(name="p0c"):
    return logging.getLogger(name)


# ---------------- shared gate ----------------

def test_channel_slot_limits_global_and_platform():
    from crawlers.base import channel_slot
    state = {"active": 0, "max": 0, "plat": {}, "plat_max": {},
             "lock": threading.Lock()}

    def work(plat):
        with channel_slot(plat):
            with state["lock"]:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
                state["plat"][plat] = state["plat"].get(plat, 0) + 1
                state["plat_max"][plat] = max(
                    state["plat_max"].get(plat, 0), state["plat"][plat])
            time.sleep(0.04)
            with state["lock"]:
                state["active"] -= 1
                state["plat"][plat] -= 1

    threads = [threading.Thread(target=work, args=(p,))
               for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    assert state["max"] <= 2

    state2 = {"active": 0, "max": 0, "lock": threading.Lock()}

    def same(plat):
        with channel_slot(plat):
            with state2["lock"]:
                state2["active"] += 1
                state2["max"] = max(state2["max"], state2["active"])
            time.sleep(0.04)
            with state2["lock"]:
                state2["active"] -= 1

    ts = [threading.Thread(target=same, args=("ctrip",)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(3)
    assert state2["max"] == 1


def test_main_and_probe_use_shared_gate():
    import main
    import webui
    from crawlers.base import CHANNEL_GATE, platform_lock
    src = open(main.__file__, encoding="utf-8").read()
    assert src.count("with channel_slot(") >= 2
    assert webui._PROBE_CHANNEL_GATE is CHANNEL_GATE
    assert webui._probe_plat_lock("ctrip") is platform_lock("ctrip")


# ---------------- status semantics ----------------

def test_probe_calendar_only_status():
    import webui
    assert webui._probe_result_status(
        [{"price": 1}], [{"status": "calendar"}], cal=1) == "calendar_only"
    assert webui._probe_result_status(
        [{"price": 1}, {"price": 2}], [{"status": "calendar"}],
        cal=1) == "ok"


def test_probe_exc_status_maps_session_busy_and_parse_error():
    import webui
    from crawlers.base import SessionBusyError
    assert webui._probe_exc_status(
        SessionBusyError("busy")) == "session_busy"
    assert webui._probe_exc_status(
        json.JSONDecodeError("x", "", 0)) == "parse_error"
    assert webui._probe_exc_status(RuntimeError("x")) == "error"
    src = inspect.getsource(webui._probe_search)
    assert "_probe_exc_status(e)" in src


# ---------------- retry cooldown ----------------

def test_probe_retry_filters_challenge_cooling_channels():
    import webui
    webui._PROBE_CHALLENGE_TS.clear()
    webui._PROBE_CHALLENGE_TS["ctrip"] = 1000.0
    allowed, blocked = webui._probe_filter_want(
        ["ctrip", "qunar"], now=1001.0)
    assert allowed == ["qunar"]
    assert blocked == ["ctrip"]
    allowed, blocked = webui._probe_filter_want(["ctrip"], now=2000.0)
    assert allowed == ["ctrip"] and blocked == []
    src = inspect.getsource(webui._probe_search)
    assert "_probe_filter_want" in src
    assert "_PROBE_CHALLENGE_TS[p]" in src
    assert "_PROBE_CHALLENGE_TS.pop(p" in src


def test_retry_endpoint_filters_before_task_creation():
    import webui
    src = inspect.getsource(webui._Handler._do_POST)
    assert "_probe_filter_want(_want)" in src
    assert '"skipped"' in inspect.getsource(webui._probe_task_view)


def test_probe_retry_bypasses_global_cooldown():
    import webui
    src = inspect.getsource(webui._probe_search)
    assert "retry=False" in src
    assert "if not retry and _now0 - _PROBE_LAST" in src
    src2 = inspect.getsource(webui._probe_start_task)
    assert "retry=retry" in src2
    assert "retry:true" in webui.PAGE


# ---------------- login window ----------------

def test_finish_login_clears_challenge_cooldown():
    import webui
    webui._PROBE_CHALLENGE_TS["ctrip"] = time.time()
    sess = {"evt": threading.Event()}
    webui._State.login_sessions["ctrip"] = sess
    try:
        assert webui._finish_login("ctrip")["ok"] is True
        assert "ctrip" not in webui._PROBE_CHALLENGE_TS
    finally:
        webui._State.login_sessions.pop("ctrip", None)
        webui._PROBE_CHALLENGE_TS.clear()


def test_login_window_timeout(monkeypatch):
    from crawlers.base import BaseCrawler
    import crawlers.base as base

    class Page:
        def goto(self, *a, **k):
            pass

        def is_closed(self):
            return False

    class Ctx:
        pages = [object()]

    @contextmanager
    def fake_browser(*a, **k):
        yield Ctx()

    c = BaseCrawler({}, _log("p0lt"))
    c.login_url = lambda: "https://example.invalid/"
    c.browser = fake_browser
    c.new_page = lambda ctx: Page()
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="超时"):
        c._login_window(threading.Event(), timeout_s=0.01)


def test_login_window_detects_closed(monkeypatch):
    from crawlers.base import BaseCrawler
    import crawlers.base as base

    class Page:
        def goto(self, *a, **k):
            pass

        def is_closed(self):
            return True

    class Ctx:
        pages = [object()]

    @contextmanager
    def fake_browser(*a, **k):
        yield Ctx()

    c = BaseCrawler({}, _log("p0lw"))
    c.login_url = lambda: "https://example.invalid/"
    c.browser = fake_browser
    c.new_page = lambda ctx: Page()
    monkeypatch.setattr(
        base.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))
    with pytest.raises(RuntimeError, match="关闭"):
        c._login_window(threading.Event(), timeout_s=10)
