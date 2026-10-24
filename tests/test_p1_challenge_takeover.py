# -*- coding: utf-8 -*-
"""P1: challenge ticket + visible original-page takeover + verify.

Recognition only: the operator completes the challenge in a real window.
No auto-solving, no third-party solver, no official API.
"""
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _log(name="p1"):
    return logging.getLogger(name)


@pytest.fixture(autouse=True)
def _clean_state():
    import webui
    webui._PROBE_CHALLENGES.clear()
    webui._PROBE_CHALLENGE_SESSIONS.clear()
    webui._PROBE_CHALLENGE_TS.clear()
    webui._PROBE_LAST = 0.0
    yield
    webui._PROBE_CHALLENGES.clear()
    webui._PROBE_CHALLENGE_SESSIONS.clear()
    webui._PROBE_CHALLENGE_TS.clear()
    webui._PROBE_LAST = 0.0


def _ticket(plat="ctrip", task_id="t1", leg=0):
    import webui
    plan = {"from": "SHA", "from_name": "上海", "to": "PEK",
            "to_name": "北京", "date": "2026-10-26"}
    paths = [{"path": "H5", "status": "blocked",
              "detail": "滑块验证（code 7）", "date": plan["date"]}]
    return webui._probe_challenge_ticket(task_id, leg, plat, plan, paths)


def test_takeover_urls_for_five_channels():
    import webui
    args = ("SHA", "PEK", "上海", "北京", "2026-10-26")
    urls = {p: webui._probe_takeover_url(p, *args)
            for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")}
    assert "m.ctrip.com" in urls["ctrip"]
    assert "m.flight.qunar.com" in urls["qunar"]
    assert "sjipiao.fliggy.com" in urls["fliggy"]
    assert "m.ly.com" in urls["tongcheng"]
    assert "m.tuniu.com" in urls["tuniu"]
    assert all(u.startswith("https://") for u in urls.values())


def test_ticket_created_for_blocked_path_and_visible_in_task():
    import webui
    t = _ticket()
    assert t["status"] == "open"
    assert t["task_id"] == "t1" and t["plat"] == "ctrip"
    assert "滑块" in t["detail"] and t["url"]
    task = {
        "id": "t1", "status": "done", "created": 1, "started": 1,
        "updated": 2, "finished": 2, "total": 1, "done": 1,
        "legs": [{"leg": 0, "from": "SHA", "from_name": "上海",
                  "to": "PEK", "to_name": "北京", "date": "2026-10-26",
                  "status": "error", "rows": 0,
                  "channels": {"ctrip": {"status": "challenge"}}}],
        "rows": [], "events": [], "plans": [{
            "from": "SHA", "from_name": "上海", "to": "PEK",
            "to_name": "北京", "date": "2026-10-26"}],
        "want": ["ctrip"], "truncated": False, "err": "",
    }
    with webui._PROBE_TASK_LOCK:
        webui._PROBE_TASKS["t1"] = task
    try:
        view = webui._probe_task_view("t1")
        assert view["challenges"] and view["challenges"][0]["plat"] == "ctrip"
    finally:
        with webui._PROBE_TASK_LOCK:
            webui._PROBE_TASKS.pop("t1", None)


def test_normal_empty_creates_no_ticket():
    import webui
    plan = {"from": "SHA", "from_name": "上海", "to": "PEK",
            "to_name": "北京", "date": "2026-10-26"}
    assert webui._probe_challenge_ticket(
        "t2", 0, "ctrip", plan,
        [{"path": "H5", "status": "empty", "detail": ""}]) is None
    assert not webui._PROBE_CHALLENGES


def test_open_challenge_window_and_skip(monkeypatch):
    import webui
    import crawlers
    events = {}
    class FakeCrawler:
        def __init__(self, cfg, logger):
            pass
        def open_challenge_window(self, url, evt, timeout_s=300, idx=0):
            events["url"] = url
            events["idx"] = idx
            evt.wait(2)
    monkeypatch.setitem(crawlers.REGISTRY, "ctrip", FakeCrawler)
    t = _ticket()
    r = webui._probe_open_challenge(t["id"])
    assert r["ok"] is True
    assert t["status"] == "window_open"
    assert t["expires_at"] > time.time()
    assert events.get("url") == t["url"]
    r2 = webui._probe_skip_challenge(t["id"])
    assert r2["ok"] is True and t["status"] == "skipped"
    assert t["expires_at"] == 0
    # 窗口线程应已收到 evt 并结束
    deadline = time.time() + 2
    while t["id"] in webui._PROBE_CHALLENGE_SESSIONS and time.time() < deadline:
        time.sleep(0.01)
    assert t["id"] not in webui._PROBE_CHALLENGE_SESSIONS


def test_verify_pass_returns_resume_payload(monkeypatch):
    import webui
    import crawlers
    class FakeCrawler:
        def __init__(self, cfg, logger):
            self.paths = []
        def fetch(self, fc, tc, dates):
            self.paths = [{"path": "H5", "status": "ok", "rows": 2,
                           "detail": ""}]
            return [{"price": 1000}, {"price": 1100}]
    monkeypatch.setitem(crawlers.REGISTRY, "ctrip", FakeCrawler)
    t = _ticket()
    webui._PROBE_CHALLENGE_TS["ctrip"] = time.time()
    r = webui._probe_verify_challenge(t["id"])
    assert r["ok"] and r["passed"] is True
    assert t["status"] == "passed" and t["rows"] == 2
    assert r["plats"] == ["ctrip"]
    assert r["legs"][0]["from"] == "SHA"
    assert "ctrip" not in webui._PROBE_CHALLENGE_TS


def test_verify_fail_keeps_ticket_failed(monkeypatch):
    import webui
    import crawlers
    class FakeCrawler:
        def __init__(self, cfg, logger):
            self.paths = []
        def fetch(self, fc, tc, dates):
            self.paths = [{"path": "H5", "status": "blocked",
                           "detail": "滑块验证"}]
            return []
    monkeypatch.setitem(crawlers.REGISTRY, "ctrip", FakeCrawler)
    t = _ticket()
    r = webui._probe_verify_challenge(t["id"])
    assert r["ok"] and r["passed"] is False
    assert t["status"] == "failed"
    assert "滑块" in t["detail"]


def test_challenge_endpoints_are_guarded():
    import inspect
    import webui
    src = inspect.getsource(webui._Handler._do_POST)
    assert "/api/challenge/open" in src
    assert "/api/challenge/verify" in src
    assert "/api/challenge/skip" in src
    assert "跨站验证请求已拒绝" in src
    assert "Content-Type 必须为 application/json" in src


def test_p1_ui_wiring():
    import webui
    src = webui.PAGE
    for needle in ("srxTaskChallenges", "srxRenderChallenges",
                   "srxChOpen", "srxChVerify", "srxChSkip", "srxChReplay",
                   "/api/challenge/open", "/api/challenge/verify",
                   "/api/challenge/skip", "data-chact"):
        assert needle in src, needle


def test_visible_window_detects_close(monkeypatch):
    from crawlers.base import BaseCrawler
    import crawlers.base as base
    class Page:
        def goto(self, *a, **k):
            pass
        def is_closed(self):
            return True
    class Ctx:
        pages = [object()]
    from contextlib import contextmanager
    @contextmanager
    def fake_browser(*a, **k):
        yield Ctx()
    c = BaseCrawler({}, _log("p1w"))
    c.browser = fake_browser
    c.new_page = lambda ctx: Page()
    monkeypatch.setattr(
        base.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))
    with pytest.raises(RuntimeError, match="关闭"):
        c.open_challenge_window("https://example.invalid/", threading.Event(),
                                timeout_s=10)
