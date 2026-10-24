# -*- coding: utf-8 -*-
"""P0: normal challenge/login recognition; never record a challenge as empty.

Scope: detection only. No auto-solving, no third-party solver, no official API.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _log(name="p0"):
    return logging.getLogger(name)


@pytest.fixture(autouse=True)
def _restore_class_state():
    from crawlers.qunar import QunarCrawler
    from crawlers.tuniu import TuniuCrawler
    yield
    QunarCrawler.login_suspect = False
    TuniuCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0


# ---------------- shared classifier ----------------

def test_classify_text_recognizes_login_and_challenge():
    from crawlers.challenge import classify_text
    assert classify_text("账号密码登录").status == "login"
    assert classify_text("请完成安全验证，拖动滑块").status == "blocked"
    assert classify_text("人机验证").status == "blocked"


def test_classify_text_does_not_flag_plain_login_header():
    from crawlers.challenge import classify_text
    # 正常列表页页头有“登录/注册”，不能因此判成登录墙。
    assert classify_text("上海 北京 登录 注册 航班列表") is None


def test_classify_text_uses_login_url():
    from crawlers.challenge import classify_text
    sig = classify_text("", url="https://user.qunar.com/passport/login.jsp")
    assert sig is not None and sig.status == "login"


def test_classify_text_recognizes_click_and_waf_markers():
    from crawlers.challenge import classify_text
    sig = classify_text("请点选下方文字")
    assert sig is not None and sig.status == "blocked" and sig.kind == "click"
    sig = classify_text("baxia")
    assert sig is not None and sig.status == "blocked" and sig.kind == "waf"


def test_classify_text_recognizes_sms_login_not_captcha():
    from crawlers.challenge import classify_text
    sig = classify_text("验证码登录")
    assert sig is not None and sig.status == "login"


# ---------------- Qunar ----------------

def test_qunar_risk_signal_maps_domestic_codes():
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._risk_signal('{"code":7}').status == "blocked"
    assert QunarCrawler._risk_signal('{"code":9}').status == "blocked"
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":10004}}').status == "blocked"
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":1999}}').status == "login"
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":2008},"code":8}').status == "login"
    assert QunarCrawler._risk_signal('{"data":{"routes":[]}}') is None


def test_qunar_h5_challenge_does_not_become_empty(monkeypatch):
    from crawlers.challenge import blocked_signal
    from crawlers.qunar import QunarCrawler
    q = QunarCrawler({"delay_min": 0, "delay_max": 0}, _log("p0q"))
    def _browser(*a, **k):
        q._last_challenge = blocked_signal("slider", "code 7")
        return None
    monkeypatch.setattr(q, "_fetch_via_browser", _browser)
    monkeypatch.setattr(q, "_fetch_via_httpx", lambda *a, **k: None)
    monkeypatch.setattr(QunarCrawler, "PC_PROBE_ON_MISS", False)
    assert q._fetch_one("SHA", "PEK", "2026-10-26") is None
    assert q.paths[0]["status"] == "blocked"
    assert "empty" not in [p["status"] for p in q.paths]


def test_qunar_blocked_challenge_skips_backoff_and_login_suspect(monkeypatch):
    from crawlers.challenge import blocked_signal
    from crawlers.qunar import QunarCrawler
    monkeypatch.setattr(QunarCrawler, "_BACKOFF_S", (0,))
    monkeypatch.setattr(QunarCrawler, "_MIN_GAP_S", 0)
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    q = QunarCrawler({"delay_min": 0, "delay_max": 0}, _log("p0qb"))
    calls = []
    def _one(*a, **k):
        calls.append(1)
        q._last_challenge = blocked_signal("slider", "code 7")
        return None
    monkeypatch.setattr(q, "_fetch_one", _one)
    assert q.fetch("SHA", "PEK", ["2026-10-26"]) == []
    assert len(calls) == 1
    assert QunarCrawler.login_suspect is False


def test_qunar_multi_date_blocked_keeps_query_evidence(monkeypatch):
    from crawlers.challenge import blocked_signal
    from crawlers.qunar import QunarCrawler
    monkeypatch.setattr(QunarCrawler, "_BACKOFF_S", (0,))
    monkeypatch.setattr(QunarCrawler, "_MIN_GAP_S", 0)
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    q = QunarCrawler({"delay_min": 0, "delay_max": 0}, _log("p0qm"))
    calls = []
    def _one(a, b, d):
        calls.append(d)
        if d == "2026-10-26":
            q._last_challenge = blocked_signal("slider", "code 7")
            q._query_challenge = q._last_challenge
        else:
            q._last_challenge = None
        return None
    monkeypatch.setattr(q, "_fetch_one", _one)
    assert q.fetch("SHA", "PEK", ["2026-10-26", "2026-10-27"]) == []
    assert calls == ["2026-10-26", "2026-10-27"]
    assert QunarCrawler.login_suspect is False


def test_qunar_intl_refresh_is_blocked_not_empty():
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._intl_risk_path("refresh") == ("blocked", "refresh")
    assert QunarCrawler._intl_risk_path("login") == ("login", "login")
    assert QunarCrawler._intl_risk_path("slider") == ("blocked", "slider")
    assert QunarCrawler._intl_risk_path("captcha") == ("blocked", "click")


def test_qunar_intl_body_risk_maps_html():
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._intl_body_risk("请登录") == "login"
    assert QunarCrawler._intl_body_risk("请完成安全验证") == "captcha"
    assert QunarCrawler._intl_body_risk("baxia 滑块") == "slider"
    assert QunarCrawler._intl_body_risk("普通页面") == ""


def test_qunar_login_h5_signal_still_tries_token_path(monkeypatch):
    from crawlers.challenge import login_signal
    from crawlers.qunar import QunarCrawler
    q = QunarCrawler({"delay_min": 0, "delay_max": 0}, _log("p0ql"))
    def _browser(*a, **k):
        q._last_challenge = login_signal("passport")
        return None
    flights = [{"code": "CA1", "name": "国航CA1", "price": 1000.0,
                "depTime": "08:00", "arrTime": "10:00"}]
    monkeypatch.setattr(q, "_fetch_via_browser", _browser)
    monkeypatch.setattr(q, "_fetch_via_httpx",
                        lambda *a, **k: (1000.0, flights))
    monkeypatch.setattr(QunarCrawler, "PC_PROBE_ON_MISS", False)
    got = q._fetch_one("SHA", "PEK", "2026-10-26")
    assert got is not None and got[0] == 1000.0
    assert [p["status"] for p in q.paths] == ["login", "ok"]


# ---------------- Tuniu ----------------

class _Resp:
    def __init__(self, text):
        self.text = text

    def json(self):
        return json.loads(self.text)


class _Cookies:
    def __init__(self):
        self._d = {}

    def set(self, k, v, domain=None, path=None):
        self._d[k] = v

    def get(self, k, default=""):
        return self._d.get(k, default)


class _FakeClient:
    def __init__(self, list_body):
        self._list_body = list_body
        self.cookies = _Cookies()

    def get(self, url, params=None, headers=None, timeout=None):
        if "listFlight" in url:
            return _Resp(self._list_body)
        return _Resp("")

    def close(self):
        pass


def _tuniu_crawler(monkeypatch, body):
    import crawlers.tuniu as tn
    from crawlers.tuniu import TuniuCrawler
    monkeypatch.setattr(tn.httpx, "Client", lambda *a, **k: _FakeClient(body))
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    return TuniuCrawler({"rate_limit": False, "max_attempts": 1,
                         "tuniu_max_poll": 1, "delay_min": 0,
                         "delay_max": 0}, _log("p0t"))


def test_tuniu_710114_marks_login_signal(monkeypatch):
    c = _tuniu_crawler(monkeypatch, '{"msg":"710114 请登录"}')
    ok, raw, blocked = c._one_attempt("SHA", "PEK", "2026-10-26")
    assert not ok and raw is None and blocked is True
    assert c._last_challenge is not None
    assert c._last_challenge.status == "login"


def test_tuniu_179991_marks_blocked_signal(monkeypatch):
    c = _tuniu_crawler(monkeypatch, '{"msg":"179991"}')
    ok, raw, blocked = c._one_attempt("SHA", "PEK", "2026-10-26")
    assert not ok and raw is None and blocked is True
    assert c._last_challenge is not None
    assert c._last_challenge.status == "blocked"


def test_tuniu_domestic_empty_path_uses_challenge_signal(monkeypatch):
    from crawlers.challenge import blocked_signal
    c = _tuniu_crawler(monkeypatch, '{"data":{}}')
    monkeypatch.setattr(c, "_fetch_pc_dom", lambda *a, **k: {})
    monkeypatch.setattr(c, "_dump_raw", lambda *a, **k: None)
    def _hoop(*a, **k):
        c._last_challenge = blocked_signal("waf", "179991")
        return None
    monkeypatch.setattr(c, "_hoop", _hoop)
    assert c.fetch("SHA", "PEK", ["2026-10-26"]) == []
    assert c.paths[0]["status"] == "blocked"
    assert "179991" in c.paths[0]["detail"]


def test_tuniu_intl_login_signal_stops_retry(monkeypatch):
    from crawlers.challenge import login_signal
    c = _tuniu_crawler(monkeypatch, '{"data":{}}')
    c.max_attempts = 3
    calls = []
    def _one(*a, **k):
        calls.append(1)
        c._last_challenge_intl = login_signal("needLogin")
        return False, None, True
    monkeypatch.setattr(c, "_one_attempt_intl", _one)
    assert c._hoop_intl("SHA", "KIX", "2026-10-25") is None
    assert len(calls) == 1


def test_tuniu_intl_needlogin_path_is_login(monkeypatch):
    from crawlers.challenge import login_signal
    c = _tuniu_crawler(monkeypatch, '{"data":{}}')
    monkeypatch.setattr(c, "_dump_raw", lambda *a, **k: None)
    def _hoop(*a, **k):
        c._last_challenge_intl = login_signal("needLogin")
        return None
    monkeypatch.setattr(c, "_hoop_intl", _hoop)
    assert c._fetch_intl("SHA", "KIX", ["2026-10-25"]) == []
    assert c.paths[0]["status"] == "login"


# ---------------- Fliggy ----------------

def test_fliggy_domestic_login_wall_is_login(monkeypatch):
    from crawlers.fliggy import FliggyCrawler
    c = FliggyCrawler({"delay_min": 0, "delay_max": 0}, _log("p0f"))
    def _pc(*a, **k):
        c._last_blocked = False
        c._last_login = True
        return []
    monkeypatch.setattr(c, "_fetch_pc", _pc)
    assert c.fetch("SHA", "PEK", ["2026-10-26"]) == []
    assert c.paths[0]["status"] == "login"


# ---------------- Ctrip ----------------

def test_ctrip_intl_calendar_login_is_not_empty():
    from crawlers.ctrip import CtripCrawler
    assert CtripCrawler._empty_calendar_status(
        "手机登录/注册", "https://m.ctrip.com/html5/") == "login"
    assert CtripCrawler._empty_calendar_status(
        "正常页面", "https://m.ctrip.com/html5/") == "empty"
