# -*- coding: utf-8 -*-
"""qunar 诚实性回归：无指纹绕过 / 失败分类 / 雷达冷却 / 往返不支持。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_qunar_honesty.py -q
"""
import logging
import os
import sys
import types
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawlers.base as base_mod  # noqa: E402
import crawlers.qunar as qunar_mod  # noqa: E402
from crawlers.base import BaseCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("test_qunar_honesty")
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
LATER = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture(autouse=True)
def _reset_qunar_radar_state():
    import core.special_radar as sr
    sr._QUNAR_CACHE.clear()
    sr._QUNAR_COOLDOWN_UNTIL = 0.0
    yield
    sr._QUNAR_CACHE.clear()
    sr._QUNAR_COOLDOWN_UNTIL = 0.0


@pytest.fixture
def crawler(monkeypatch):
    monkeypatch.setattr(QunarCrawler, "_MIN_GAP_S", 0)
    monkeypatch.setattr(QunarCrawler, "_BACKOFF_S", (0,))
    monkeypatch.setattr(QunarCrawler, "_cooldown_until", 0.0)
    monkeypatch.setattr(QunarCrawler, "_last_done_ts", 0.0)
    monkeypatch.setattr(QunarCrawler, "login_suspect", False)
    return QunarCrawler({"delay_min": 0, "delay_max": 0}, _LOG)


# ---------------- 1. NO-BYPASS ----------------

def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_no_fingerprint_spoofing_source_left():
    qsrc = _read(os.path.join("crawlers", "qunar.py"))
    bsrc = _read(os.path.join("crawlers", "base.py"))
    for needle in ("_STEALTH_JS", "navigator, 'webdriver'",
                   "navigator,'webdriver'", "navigator.webdriver",
                   "add_init_script", "WebGLRenderingContext",
                   "Apple GPU", "AutomationControlled"):
        assert needle not in qsrc, needle
    for needle in ("navigator,'webdriver'", "navigator.webdriver",
                   "add_init_script", "WebGLRenderingContext",
                   "AutomationControlled"):
        assert needle not in bsrc, needle


def test_browser_context_installs_no_init_scripts(monkeypatch, tmp_path):
    class _Ctx:
        def __init__(self):
            self.scripts = []

        def add_init_script(self, script=None, path=None):
            self.scripts.append(script if script is not None else path)

        def cookies(self):
            return []

        def storage_state(self):
            return {}

        def close(self):
            pass

    class _Chromium:
        def __init__(self, ctx):
            self.ctx = ctx
            self.kwargs = None

        def launch_persistent_context(self, *a, **k):
            self.kwargs = k
            return self.ctx

    class _PW:
        def __init__(self, chromium):
            self.chromium = chromium

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    ctx = _Ctx()
    chromium = _Chromium(ctx)
    monkeypatch.setattr(base_mod, "sync_playwright", lambda: _PW(chromium))
    c = BaseCrawler({"user_data_dir": str(tmp_path)}, _LOG)
    with c._browser_context(True, False, 0, None) as got:
        assert got is ctx
    assert ctx.scripts == []
    assert chromium.kwargs.get("user_agent")
    assert chromium.kwargs.get("viewport")
    assert "AutomationControlled" not in " ".join(chromium.kwargs["args"])


# ---------------- 2. FAILURE CLASSIFICATION ----------------

def test_fetch_timeout_is_not_login_evidence(crawler, monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(crawler, "_fetch_inner", _boom)
    assert crawler.fetch("SHA", "PEK", ["2026-11-01"]) == []
    assert QunarCrawler.login_suspect is False
    assert [(p["path"], p["status"]) for p in crawler.paths] == [
        ("QUERY", "timeout")]


def test_fetch_network_error_maps_to_error(crawler, monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("dns failure")

    monkeypatch.setattr(crawler, "_fetch_inner", _boom)
    assert crawler.fetch("SHA", "PEK", ["2026-11-01"]) == []
    assert QunarCrawler.login_suspect is False
    assert [(p["path"], p["status"]) for p in crawler.paths] == [
        ("QUERY", "error")]


def test_inner_timeout_records_per_date_path(crawler, monkeypatch):
    def _one(from_city, to_city, day):
        raise TimeoutError("browser timeout")

    monkeypatch.setattr(crawler, "_fetch_one", _one)
    assert crawler.fetch("SHA", "PEK", ["2026-11-01", "2026-11-02"]) == []
    assert QunarCrawler.login_suspect is False
    hits = [p for p in crawler.paths if p["status"] == "timeout"]
    assert hits and {p["date"] for p in hits} == {"2026-11-01", "2026-11-02"}
    assert "empty" not in [p["status"] for p in crawler.paths]


def test_empty_without_evidence_keeps_login_suspect_semantics(
        crawler, monkeypatch):
    monkeypatch.setattr(crawler, "_fetch_inner", lambda *a, **k: [])
    assert crawler.fetch("SHA", "PEK", ["2026-11-01"]) == []
    assert QunarCrawler.login_suspect is True


def test_blocked_challenge_still_wins_over_failure_type(crawler, monkeypatch):
    from crawlers.challenge import blocked_signal

    def _one(from_city, to_city, day):
        crawler._last_challenge = blocked_signal("slider", "code 7")
        crawler.path_note("H5", "blocked", date=day, detail="code 7")
        return None

    monkeypatch.setattr(crawler, "_fetch_one", _one)
    assert crawler.fetch("SHA", "PEK", ["2026-11-01"]) == []
    assert QunarCrawler.login_suspect is False
    assert "blocked" in [p["status"] for p in crawler.paths]


# ---------------- 3. RADAR TIMEOUT / COOLDOWN ----------------

class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class _Resp:
    def __init__(self, payload):
        self.url = "https://touch.qunar.com/x/getFlightCalendar?x=1"
        self.payload = payload

    def json(self):
        return self.payload


class _Page:
    def __init__(self, clock, responses=()):
        self.clock = clock
        self.responses = list(responses)
        self.handlers = {}
        self.goto_calls = []
        self.wait_counts = []
        self.fail_goto = False

    def on(self, evt, cb):
        self.handlers[evt] = cb

    def goto(self, url, **kw):
        self.goto_calls.append((self.clock(), url, kw.get("timeout")))
        self.wait_counts.append(0)
        if self.fail_goto:
            raise RuntimeError("net down")
        for r in self.responses:
            self.handlers["response"](r)

    def wait_for_timeout(self, ms):
        if self.wait_counts:
            self.wait_counts[-1] += 1
        self.clock.now += ms / 1000.0


class _Ctx:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page

    def close(self):
        pass


class _Chromium:
    def __init__(self, ctx):
        self.ctx = ctx

    def launch_persistent_context(self, *a, **k):
        return self.ctx


class _PW:
    def __init__(self, ctx):
        self.chromium = _Chromium(ctx)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_calendar(monkeypatch, page, clock):
    import playwright.sync_api as pw_api
    monkeypatch.setattr(pw_api, "sync_playwright", lambda: _PW(_Ctx(page)))
    monkeypatch.setattr(qunar_mod, "time", types.SimpleNamespace(time=clock))


def test_calendar_second_attempt_has_its_own_deadline(monkeypatch, tmp_path):
    clock = _Clock()
    page = _Page(clock)
    _patch_calendar(monkeypatch, page, clock)
    with pytest.raises(TimeoutError):
        QunarCrawler.fetch_low_price_calendar(
            "上海", "曼谷", "2026-11-01", "2026-11-30",
            logger=_LOG, timeout=8.0, profile_root=str(tmp_path))
    assert len(page.wait_counts) == 2, page.wait_counts
    assert all(n > 0 for n in page.wait_counts), page.wait_counts
    # 第二次尝试的导航超时以剩余预算为界，不是沿用已耗尽的旧 deadline
    assert page.goto_calls[1][2] <= 4000


def test_calendar_risk_evidence_returns_none(monkeypatch, tmp_path):
    clock = _Clock()
    page = _Page(clock, [_Resp({"bstatus": {"code": 10003}})])
    _patch_calendar(monkeypatch, page, clock)
    assert QunarCrawler.fetch_low_price_calendar(
        "上海", "曼谷", "2026-11-01", "2026-11-30",
        logger=_LOG, timeout=8.0, profile_root=str(tmp_path)) is None


def test_calendar_loaded_empty_is_not_risk(monkeypatch, tmp_path):
    clock = _Clock()
    page = _Page(clock, [_Resp({"bstatus": {"code": 0},
                                "lowPriceList": []})])
    _patch_calendar(monkeypatch, page, clock)
    out = QunarCrawler.fetch_low_price_calendar(
        "上海", "曼谷", "2026-11-01", "2026-11-30",
        logger=_LOG, timeout=8.0, profile_root=str(tmp_path))
    assert out == {"bstatus": 0, "lowPriceList": []}


def test_calendar_load_failure_raises_not_none(monkeypatch, tmp_path):
    clock = _Clock()
    page = _Page(clock)
    page.fail_goto = True
    _patch_calendar(monkeypatch, page, clock)
    with pytest.raises(TimeoutError):
        QunarCrawler.fetch_low_price_calendar(
            "上海", "曼谷", "2026-11-01", "2026-11-30",
            logger=_LOG, timeout=8.0, profile_root=str(tmp_path))


def test_calendar_browser_unavailable_raises_runtime(monkeypatch, tmp_path):
    import playwright.sync_api as pw_api

    def _boom():
        raise RuntimeError("browser executable missing")

    monkeypatch.setattr(pw_api, "sync_playwright", _boom)
    with pytest.raises(RuntimeError):
        QunarCrawler.fetch_low_price_calendar(
            "上海", "曼谷", "2026-11-01", "2026-11-30",
            logger=_LOG, timeout=8.0, profile_root=str(tmp_path))


def test_radar_timeout_does_not_arm_risk_cooldown(monkeypatch):
    import core.special_radar as sr
    monkeypatch.setattr(sr, "_QUNAR_COOLDOWN_UNTIL", 0.0)
    sr._QUNAR_CACHE.clear()

    def _timeout(*a, **k):
        raise TimeoutError("load timeout")

    monkeypatch.setattr(QunarCrawler, "fetch_low_price_calendar",
                        staticmethod(_timeout))
    out = sr.build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                          "end": LATER, "channels": ["qunar"]}, _LOG)
    assert out["channels"]["qunar"]["status"] == "error"
    assert sr._QUNAR_COOLDOWN_UNTIL == 0.0


def test_radar_risk_evidence_arms_long_cooldown(monkeypatch):
    import core.special_radar as sr
    monkeypatch.setattr(sr, "_QUNAR_COOLDOWN_UNTIL", 0.0)
    sr._QUNAR_CACHE.clear()
    monkeypatch.setattr(QunarCrawler, "fetch_low_price_calendar",
                        staticmethod(lambda *a, **k: None))
    out = sr.build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                          "end": LATER, "channels": ["qunar"]}, _LOG)
    assert out["channels"]["qunar"]["status"] == "error"
    assert sr._QUNAR_COOLDOWN_UNTIL > 0.0


# ---------------- 4. ROUND-TRIP HONESTY ----------------

def test_ret_date_unsupported_without_query(crawler, monkeypatch):
    calls = []
    monkeypatch.setattr(crawler, "_fetch_inner",
                        lambda *a, **k: calls.append(1) or [])
    out = crawler.fetch("SHA", "PEK", ["2026-11-01"],
                        ret_date="2026-11-08")
    assert out == []
    assert calls == []
    assert len(crawler.paths) == 1
    rec = crawler.paths[0]
    assert rec["path"] == "TRIP" and rec["status"] == "unsupported"
    assert "未发起单程查询" in rec["detail"]


# ---------------- 5. 1999 NO-RESULT VS LOGIN ----------------

def test_no_result_message_is_not_login():
    import json as _json
    txt = _json.dumps({
        "bstatus": {"code": 1999, "msg": "没有查询到符合条件的航班"},
        "code": -1, "data": None, "msg": "没有查询到符合条件的航班",
        "ret": False})
    assert QunarCrawler._no_result_text(txt) is True
    assert QunarCrawler._risk_signal(txt) is None
    assert QunarCrawler._parse_intl_response(txt) == ([], "empty")
    login_txt = _json.dumps({
        "bstatus": {"code": 1999, "msg": "成功"}, "code": -1,
        "data": None, "msg": "成功", "ret": False})
    assert QunarCrawler._no_result_text(login_txt) is False
    sig = QunarCrawler._risk_signal(login_txt)
    assert sig is not None and sig.status == "login"


def test_fetch_explicit_no_result_does_not_mark_login(crawler, monkeypatch):
    def _empty(*a, **k):
        crawler._last_no_result = True
        return []
    monkeypatch.setattr(crawler, "_fetch_inner", _empty)
    QunarCrawler.login_suspect = False
    out = crawler.fetch("SHA", "PEK", ["2026-11-01"])
    assert out == []
    assert QunarCrawler.login_suspect is False
    assert crawler._last_no_result is True
