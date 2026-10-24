# -*- coding: utf-8 -*-
"""同程/途牛国际通道失败分层诚实性钉（§5/§10）。

同程日历与途牛 queryFlight 的真实边界必须可区分：导航/请求超时、
请求异常、坏 JSON/解析失败不得落成 empty；只有干净成功响应且无行
才允许 empty。本文件用故障注入钉住三条映射与两条干净边界，禁止
CAPTCHA/登录门被绕过（只做分类，不做验证码破解）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_tt_honesty.py
"""
import contextlib
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers.tongcheng as tc_mod  # noqa: E402
import crawlers.tuniu as tn_mod  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.tuniu import IntlFailure, TuniuCrawler  # noqa: E402

_DATE = "2026-11-16"
_LOG = logging.getLogger("t_tt_honesty")


# ─────────────── 同程国际日历故障注入 ───────────────

class _Resp:
    def __init__(self, status=200, text=""):
        self.status = status
        self._text = text

    def text(self):
        return self._text


class _FakePage:
    def __init__(self, goto_exc=None, eval_result=None, eval_exc=None):
        self._goto_exc = goto_exc
        self._eval_result = eval_result
        self._eval_exc = eval_exc
        self.url = "https://www.ly.com/iflight/"

    def goto(self, url, **kw):
        if self._goto_exc is not None:
            raise self._goto_exc
        return None

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, script, arg=None, *a, **k):
        if self._eval_exc is not None:
            raise self._eval_exc
        return self._eval_result


class _FakeCtx:
    def __init__(self, req_resp=None, req_exc=None):
        outer = self

        class _Req:
            def get(self, url, **kw):
                if outer._req_exc is not None:
                    raise outer._req_exc
                return outer._req_resp

        self._req_resp = req_resp
        self._req_exc = req_exc
        self.request = _Req()


def _tc(monkeypatch, *, goto_exc=None, eval_result=None, eval_exc=None,
        req_resp=None, req_exc=None):
    c = TongchengCrawler({"delay_min": 0, "delay_max": 0}, _LOG)
    c.probe_mode = False
    c.path_reset()
    page = _FakePage(goto_exc=goto_exc, eval_result=eval_result,
                     eval_exc=eval_exc)
    ctx = _FakeCtx(req_resp=req_resp, req_exc=req_exc)
    monkeypatch.setattr(
        TongchengCrawler, "browser",
        lambda self, headless=None: contextlib.nullcontext(ctx))
    monkeypatch.setattr(c, "new_page", lambda _ctx: page)
    monkeypatch.setattr(c, "_sleep", lambda: None)
    return c


def _tc_status(c):
    return c.paths[-1]["status"]


def test_tc_intl_navigation_timeout_is_timeout(monkeypatch):
    # 入口导航超时 + 日历请求空 body：不得冒充无票
    c = _tc(monkeypatch, goto_exc=TimeoutError("nav timeout"),
            eval_result={"status": 200, "body": ""},
            req_resp=_Resp(200, ""))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "timeout"


def test_tc_intl_request_timeout_is_timeout(monkeypatch):
    c = _tc(monkeypatch, eval_exc=TimeoutError("fetch timeout"),
            req_exc=TimeoutError("fallback timeout"))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "timeout"


def test_tc_intl_request_exception_is_error(monkeypatch):
    c = _tc(monkeypatch, eval_exc=RuntimeError("render gone"),
            req_exc=RuntimeError("ctx request failed"))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "error"


def test_tc_intl_invalid_json_is_parse_error(monkeypatch):
    c = _tc(monkeypatch, eval_result={"status": 200,
                                      "body": "<html>not-json</html>"})
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "parse_error"


def test_tc_intl_empty_body_is_parse_error(monkeypatch):
    c = _tc(monkeypatch, eval_result={"status": 200, "body": ""},
            req_resp=_Resp(200, ""))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "parse_error"


def test_tc_intl_missing_data_object_is_parse_error(monkeypatch):
    body = json.dumps({"code": 200, "message": "ok"})
    c = _tc(monkeypatch, eval_result={"status": 200, "body": body})
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "parse_error"


def test_tc_intl_clean_empty_rows_is_empty(monkeypatch):
    body = json.dumps({"code": 200, "data": {"RD": []}})
    c = _tc(monkeypatch, eval_result={"status": 200, "body": body})
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert _tc_status(c) == "empty"


def test_tc_intl_success_parser_unchanged(monkeypatch):
    body = json.dumps({"code": 200, "data": {"RD": [
        {"DD": _DATE, "TP": 922, "P": 435}]}})
    c = _tc(monkeypatch, eval_result={"status": 200, "body": body})
    out = c._fetch_intl("SHA", "NRT", [_DATE])
    assert len(out) == 1 and out[0].price == 922.0
    assert _tc_status(c) == "calendar"


# ─────────────── 途牛国际 queryFlight 故障注入 ───────────────

class _JsonResp:
    def __init__(self, payload=None, text="", json_exc=None):
        self._payload = payload
        self._text = text
        self._json_exc = json_exc

    @property
    def text(self):
        return self._text

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


class _FakeClient:
    def __init__(self, qf_resp=None, get_exc=None):
        self._qf_resp = qf_resp
        self._get_exc = get_exc
        self.cookies = {}

    def get(self, url, **kw):
        if self._get_exc is not None:
            raise self._get_exc
        if "m2015/intlFlight/flight/list" in str(url):
            return _JsonResp(text='<input id="token" value="ABC">')
        return self._qf_resp

    def close(self):
        return None


def _tn(monkeypatch, *, qf_resp=None, get_exc=None):
    c = TuniuCrawler({"max_attempts": 1, "rate_limit": False,
                      "delay_min": 0, "delay_max": 0}, _LOG)
    c.max_attempts = 1
    c.max_poll = 2
    c.backoff_s = 0
    c.rate_limit = False
    c.path_reset()
    monkeypatch.setattr(
        tn_mod.httpx, "Client",
        lambda *a, **k: _FakeClient(qf_resp=qf_resp, get_exc=get_exc))
    monkeypatch.setattr(tn_mod.time, "sleep", lambda *a: None)
    monkeypatch.setattr(c, "_sleep", lambda: None)
    return c


def test_tn_intl_http_timeout_typed(monkeypatch):
    c = _tn(monkeypatch, get_exc=TimeoutError("read timeout"))
    ok, raw, blocked = c._one_attempt_intl("SHA", "NRT", _DATE, polls=2)
    assert ok is False and isinstance(raw, IntlFailure)
    assert raw.status == "timeout" and raw.detail


def test_tn_intl_request_exception_typed(monkeypatch):
    c = _tn(monkeypatch, get_exc=RuntimeError("connection reset"))
    ok, raw, blocked = c._one_attempt_intl("SHA", "NRT", _DATE, polls=2)
    assert ok is False and isinstance(raw, IntlFailure)
    assert raw.status == "error" and raw.detail


def test_tn_intl_invalid_json_typed(monkeypatch):
    c = _tn(monkeypatch, qf_resp=_JsonResp(json_exc=ValueError("bad json")))
    ok, raw, blocked = c._one_attempt_intl("SHA", "NRT", _DATE, polls=2)
    assert ok is False and isinstance(raw, IntlFailure)
    assert raw.status == "parse_error" and raw.detail


def test_tn_intl_aggregation_timeout_typed(monkeypatch):
    c = _tn(monkeypatch, qf_resp=_JsonResp(payload={
        "data": {"needQueryMore": "1", "productList": []}}))
    ok, raw, blocked = c._one_attempt_intl("SHA", "NRT", _DATE, polls=2)
    assert ok is False and isinstance(raw, IntlFailure)
    assert raw.status == "timeout" and "聚合" in raw.detail


def test_tn_intl_typed_failure_maps_to_path(monkeypatch):
    # 调用方按失败类型落账（不是 empty）
    for status in ("timeout", "error", "parse_error"):
        c = TuniuCrawler({"max_attempts": 1, "rate_limit": False},
                         _LOG)
        c.max_attempts = 1
        c.backoff_s = 0
        c.rate_limit = False
        c.path_reset()
        monkeypatch.setattr(c, "_sleep", lambda: None)
        monkeypatch.setattr(
            c, "_one_attempt_intl",
            lambda *a, _s=status, **k: (
                False, IntlFailure(_s, "injected"), False))
        assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
        assert c.paths[-1]["status"] == status, (status, c.paths[-1])


def test_tn_intl_clean_empty_product_list_is_empty(monkeypatch):
    c = _tn(monkeypatch, qf_resp=_JsonResp(payload={
        "data": {"needQueryMore": "0", "productList": []}}))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert c.paths[-1]["status"] == "empty"


def test_tn_intl_parse_empty_after_rows_is_parse_error(monkeypatch):
    c = _tn(monkeypatch, qf_resp=_JsonResp(payload={
        "data": {"needQueryMore": "0",
                 "productList": [{"not": "a flight"}]}}))
    assert c._fetch_intl("SHA", "NRT", [_DATE]) == []
    assert c.paths[-1]["status"] == "parse_error"


def test_tn_intl_success_path_unchanged(monkeypatch):
    c = _tn(monkeypatch, qf_resp=_JsonResp(payload={
        "data": {"needQueryMore": "0", "productList": [{
            "dTime": "2026-11-16 09:30", "aTime": "2026-11-16 14:00",
            "airlineName": "东方航空", "flightNos": "MU523",
            "cabinName": "经济舱", "avgTotalPrice": 2380.0,
            "avgBasePrice": 1860.0, "avgTax": 520.0, "totalMin": 270,
        }]}}))
    out = c._fetch_intl("SHA", "NRT", [_DATE])
    assert len(out) == 1 and out[0].price == 2380.0
    assert c.paths[-1]["status"] == "ok"
