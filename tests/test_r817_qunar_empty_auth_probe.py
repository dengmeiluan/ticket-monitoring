# -*- coding: utf-8 -*-
"""r817：去哪儿「三路径空结果」不得无条件当成会话失效。

2026-11-02 线上实测：19:18 SHA→LHR 单次 1999 后重试拿到三路径空结果，
旧逻辑立即置 login_suspect 并提示重登；但同一快照的 _q 调
user.qunar.com/index/userBaseInfo 仍返回 ret=True/errcode=200。用户因此
被反复推去重登一个完好的会话。

新归因：
  - 认证 Cookie 不在场 / 探测明确匿名 → 才提示重登；
  - 认证 Cookie 在场且探测在线 → 软空/限流，只退避重试一次，不催重登；
  - 探测不可达 → 待验证，同样不催重登；
  - 旧 login_suspect 在新一轮探测在线时自动清除（无需人工重登）。
"""
import json
import logging
import os
import time
from types import SimpleNamespace

import pytest

from crawlers.challenge import login_signal
from crawlers.qunar import QunarCrawler

_LOG = logging.getLogger("t_r817")


def _ck(name, value="v", expires=-1):
    return {"name": name, "value": value, "domain": ".qunar.com",
            "path": "/", "expires": expires}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload=None, exc=None, calls=None):
        self.payload = payload
        self.exc = exc
        self.calls = calls if calls is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return _Resp(self.payload)


@pytest.fixture(autouse=True)
def _reset_qunar_state():
    QunarCrawler.login_suspect = False
    QunarCrawler._auth_probe_at = 0.0
    QunarCrawler._auth_probe_ok = None
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    yield
    QunarCrawler.login_suspect = False
    QunarCrawler._auth_probe_at = 0.0
    QunarCrawler._auth_probe_ok = None
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0


def _crawler(tmp_path, cookies):
    q = QunarCrawler({"user_data_dir": str(tmp_path)}, _LOG)
    os.makedirs(os.path.dirname(q.session_state_path), exist_ok=True)
    with open(q.session_state_path, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.time(), "cookies": cookies}, f)
    return q


def test_empty_verdict_matrix():
    # 认证 Cookie 不在场：空结果才可能是未登录
    assert QunarCrawler._empty_verdict(False, None) == "login"
    assert QunarCrawler._empty_verdict(False, True) == "login"
    # 探测在线：软空/限流，不催重登
    assert QunarCrawler._empty_verdict(True, True) == "soft"
    # 探测明确匿名：认证 Cookie 残留但会话已死
    assert QunarCrawler._empty_verdict(True, False) == "login"
    # 探测不可达：待验证，不催重登
    assert QunarCrawler._empty_verdict(True, None) == "verify"


def test_probe_true_reads_auth_cookie_and_caches(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("QN1", "anon"), _ck("_q", "user")])
    calls = []
    client = _Client({"ver": 1, "ret": True, "errcode": 200}, calls=calls)
    monkeypatch.setattr("core.net.new_client", lambda **kw: client)

    assert q._probe_session_alive() is True
    assert len(calls) == 1
    assert "userBaseInfo" in calls[0][0]
    cookies = calls[0][1].get("cookies") or {}
    assert cookies.get("_q") == "user"
    assert "_q" not in (cookies.get("QN1") or "")

    # 10 分钟缓存：连续空结果不重复打探测接口
    assert q._probe_session_alive() is True
    assert len(calls) == 1


def test_probe_anonymous_false_and_network_none(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    anon = _Client({"ver": 1, "ret": False, "errcode": 22032})
    monkeypatch.setattr("core.net.new_client", lambda **kw: anon)
    assert q._probe_session_alive() is False

    QunarCrawler._auth_probe_at = 0.0
    QunarCrawler._auth_probe_ok = None
    boom = _Client(exc=RuntimeError("network down"))
    monkeypatch.setattr("core.net.new_client", lambda **kw: boom)
    assert q._probe_session_alive() is None
    # 探测失败不写缓存，下次仍可重试
    assert QunarCrawler._auth_probe_at == 0.0


def test_probe_without_auth_cookie_does_not_call_network(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("QN1", "anon")])

    def _no_net(**kw):
        raise AssertionError("无认证 Cookie 不应发起探测")

    monkeypatch.setattr("core.net.new_client", _no_net)
    assert q._probe_session_alive() is False


def _fetch_stub(q, rows):
    calls = []

    def _inner(*a, **k):
        calls.append((a, k))
        return list(rows)

    q._fetch_inner = _inner
    return calls


def _patch_fetch_timing(monkeypatch):
    monkeypatch.setattr(QunarCrawler, "_BACKOFF_S", (0, 0))
    monkeypatch.setattr(QunarCrawler, "_MIN_GAP_S", 0)


def test_soft_empty_retries_once_without_login_prompt(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    calls = _fetch_stub(q, [])
    q._probe_session_alive = lambda: True
    _patch_fetch_timing(monkeypatch)

    assert q.fetch("SHA", "BKK", ["2026-11-16"]) == []
    assert len(calls) == 2          # 空 → 退避重试一次
    assert QunarCrawler.login_suspect is False
    assert (q.last_soft_reject or {}).get("kind") == "soft_empty"


def test_verify_empty_retries_once_without_login_prompt(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    calls = _fetch_stub(q, [])
    q._probe_session_alive = lambda: None
    _patch_fetch_timing(monkeypatch)

    assert q.fetch("SHA", "BKK", ["2026-11-16"]) == []
    assert len(calls) == 2
    assert QunarCrawler.login_suspect is False
    assert (q.last_soft_reject or {}).get("kind") == "soft_empty"


def test_probe_anonymous_prompts_login_without_wasted_retry(
        tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    calls = _fetch_stub(q, [])
    q._probe_session_alive = lambda: False
    _patch_fetch_timing(monkeypatch)

    assert q.fetch("SHA", "BKK", ["2026-11-16"]) == []
    assert len(calls) == 1
    assert QunarCrawler.login_suspect is True


def test_no_auth_cookie_prompts_login(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("QN1", "anon")])
    calls = _fetch_stub(q, [])
    q._probe_session_alive = lambda: (_ for _ in ()).throw(
        AssertionError("无认证 Cookie 不应探测"))
    _patch_fetch_timing(monkeypatch)

    assert q.fetch("SHA", "BKK", ["2026-11-16"]) == []
    assert len(calls) == 1
    assert QunarCrawler.login_suspect is True


def test_stale_login_suspect_self_heals_when_probe_alive(
        tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    rows = [SimpleNamespace(flight_no="MU5101", depart_time="08:00")]
    calls = _fetch_stub(q, rows)
    q._probe_session_alive = lambda: True
    _patch_fetch_timing(monkeypatch)
    QunarCrawler.login_suspect = True

    got = q.fetch("SHA", "BKK", ["2026-11-16"])
    assert len(got) == 1
    assert len(calls) == 1
    assert QunarCrawler.login_suspect is False


def test_intl_success_quiets_following_intl_but_not_domestic(
        tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    rows = [SimpleNamespace(flight_no="MU5101", depart_time="08:00")]
    calls = _fetch_stub(q, rows)
    q._probe_session_alive = lambda: True
    _patch_fetch_timing(monkeypatch)

    assert len(q.fetch("SHA", "BKK", ["2026-11-16"])) == 1
    assert q._intl_quiet_until > time.time()
    # r940：让位窗口只挡「刚查过的」。LHR 从没轮到过 → 本窗口放行一次
    # （否则配置里第一条国际线永远独吞配额，后面三条饿死）。
    assert len(q.fetch("SHA", "LHR", ["2026-11-16"])) == 1
    assert len(calls) == 2
    assert "SHA-LHR" in q._intl_route_seen
    # 同一个窗口再要 LHR：已经轮到过，必须让位；按「主动让位」入账
    # （r929：让位不是我方被拒，记 soft_reject 会把成功率读低）
    assert q.fetch("SHA", "LHR", ["2026-11-16"]) == []
    assert len(calls) == 2
    assert any(p.get("status") == "paced" for p in q.paths)
    assert not any(p.get("status") == "soft_reject" for p in q.paths)
    # 国内列表另有配额，不受国际让位影响
    assert len(q.fetch("SHA", "HAK", ["2027-01-29"])) == 1
    assert len(calls) == 3


def test_intl_soft_empty_quiets_following_intl(tmp_path, monkeypatch):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    calls = _fetch_stub(q, [])
    q._probe_session_alive = lambda: True
    _patch_fetch_timing(monkeypatch)

    assert q.fetch("SHA", "BKK", ["2026-11-16"]) == []
    assert len(calls) == 2          # 首次 + 软空退避重试一次
    assert q._intl_quiet_until > time.time()
    # r940：LHR 从没轮到过 → 本窗口放行一次（同样软空重试，共 2 次请求）
    assert q.fetch("SHA", "LHR", ["2026-11-16"]) == []
    assert len(calls) == 4
    assert "SHA-LHR" in q._intl_route_seen
    # 再要 LHR：已经轮到过，本轮不再连打
    assert q.fetch("SHA", "LHR", ["2026-11-16"]) == []
    assert len(calls) == 4


def test_login_signal_with_auth_online_is_soft(tmp_path):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    q._probe_session_alive = lambda: True
    q.last_soft_reject = None

    assert q._mark_login_signal(login_signal("1999/2008")) is False
    assert QunarCrawler.login_suspect is False
    assert (q.last_soft_reject or {}).get("kind") == "soft_reject"


def test_login_signal_with_auth_anonymous_prompts_login(tmp_path):
    q = _crawler(tmp_path, [_ck("_q", "user")])
    q._probe_session_alive = lambda: False

    assert q._mark_login_signal(login_signal("登录墙")) is True
    assert QunarCrawler.login_suspect is True


def test_login_signal_without_auth_prompts_without_probe(tmp_path):
    q = _crawler(tmp_path, [_ck("QN1", "anon")])
    q._probe_session_alive = lambda: (_ for _ in ()).throw(
        AssertionError("无认证 Cookie 不应探测"))

    assert q._mark_login_signal(login_signal("登录墙")) is True
    assert QunarCrawler.login_suspect is True


def test_source_uses_probe_and_soft_empty_marker():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "crawlers", "qunar.py"),
               encoding="utf-8").read()
    assert "def _probe_session_alive" in src
    assert "def _mark_login_signal" in src
    assert "def _empty_verdict" in src
    assert "self._soft_empty_retried" in src
    assert "_empty_verdict(" in src
    # 通用风控信号不得再绕过认证判断直接催重登
    assert 'if _sig.status == "login":\n                QunarCrawler' not in src
