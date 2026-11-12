# -*- coding: utf-8 -*-
"""P1: challenge ticket + visible original-page takeover + verify.

默认路径：人工在真实窗口里完成挑战（本文件钉的就是这条链）。
自动处置属于可选外挂（``crawlers/slider.py::SliderHandler``，需显式注册 +
``crawler.slider.auto`` 打开，且只对几何滑块生效）；外部打码平台默认不接
打码服务、也不调用官方接口。
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
    """接管/挑战窗口打开的是**该端登录入口**，不是"查看详情"深链。

    r1063 T70：旧实现优先用 `Alerter._build_view_url`（那是给推送里的
    "查看详情"用的），它给 ctrip/qunar/tongcheng/tuniu 的都是 `m.*` 移动域——
    于是 PC 端弹窗弹成 H5，用户读作"弹错端"。现在统一走
    `channel_links.login_entry_url(plat, "pc")`，PC 就给 PC 页。
    """
    import webui
    from core.channel_links import login_entry_url
    args = ("SHA", "PEK", "上海", "北京", "2026-10-26")
    urls = {p: webui._probe_takeover_url(p, *args)
            for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")}
    for plat, got in urls.items():
        assert got.startswith("https://"), (plat, got)
        # 单一真源：与登录入口表逐字一致
        assert got == login_entry_url(plat, "pc"), (plat, got)
        # PC 入口不得是移动域（这正是用户报的那个 bug）
        assert "://m." not in got, (plat, got)


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
    # 开窗在后台线程里：等它把 url 落到 events（否则偶发读到 None）
    _dl = time.time() + 3
    while not events.get("url") and time.time() < _dl:
        time.sleep(0.02)
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
    # 读文件而非 getsource(_do_POST)：全套运行时 _Handler 可能被替换（r379）。
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
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
    # r379: closing the window is the intended "done" signal; it must
    # snapshot and return instead of raising (raising lost the session).
    assert c.open_challenge_window("https://example.invalid/",
                                   threading.Event(), timeout_s=10) is True
