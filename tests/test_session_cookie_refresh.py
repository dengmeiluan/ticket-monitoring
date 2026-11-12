# -*- coding: utf-8 -*-
"""登录态健壮性：快照 Cookie 的「新盖旧」与采集后回写。

用户反馈「配置完过一会又要登录」。根因不在配置保存（不删 Cookie），
而是两处会话生命周期：
  1. 以前只补 profile 缺失的 Cookie；profile 里同名旧 Cookie 过期后，
     新快照永远盖不上去 → 重启/换配置后像掉登录；
  2. 快照只在登录/验证窗口写；短命会话 Cookie 在采集轮里轮换后，
     快照仍是登录那一刻的旧值 → 重启后短命 Cookie 已过期。
这里钉住：过期/更旧的档案 Cookie 可被快照替换；更新的不覆盖；
采集态仅在认证 Cookie 仍在时回写，且沿用 saved_at（不冒充重新登录）。
"""
import io
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import BaseCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG = logging.getLogger("t_session")


def _ck(name, expires, domain=".ctrip.com", value="v"):
    return {"name": name, "value": value, "domain": domain,
            "path": "/", "expires": expires}


def test_restore_plan_replaces_expired_or_older_profile_cookie():
    now = time.time()
    existing = [
        _ck("expired", now - 60, value="old"),
        _ck("older", now + 100, value="old"),
        _ck("newer", now + 500, value="keep"),
        _ck("session", -1, value="keep-session"),
    ]
    saved = [
        _ck("expired", now + 3600, value="fresh"),
        _ck("older", now + 200, value="fresh"),
        _ck("newer", now + 300, value="stale"),
        _ck("session", now + 3600, value="persistent"),
        _ck("missing", now + 3600, value="new"),
    ]
    plan = {c["name"]: c["value"]
            for c in BaseCrawler._restore_plan(existing, saved, now)}
    assert plan == {
        "expired": "fresh",   # 档案已过期 → 快照盖
        "older": "fresh",     # 快照到期更晚 → 快照盖
        "missing": "new",     # 档案没有 → 补
    }


def test_restore_plan_session_cookie_rules():
    now = time.time()
    # 档案 session Cookie 视为当前，不被旧快照的持久 Cookie 覆盖
    existing = [_ck("s", -1, value="current")]
    saved = [_ck("s", now + 3600, value="old-persistent")]
    assert BaseCrawler._restore_plan(existing, saved, now) == []
    # 档案持久 Cookie 已过期，快照 session Cookie 可以救回来
    existing = [_ck("s", now - 1, value="dead")]
    saved = [_ck("s", -1, value="live-session")]
    plan = BaseCrawler._restore_plan(existing, saved, now)
    assert len(plan) == 1 and plan[0]["value"] == "live-session"
    # 非法 expires 不硬判
    assert BaseCrawler._restore_plan(
        [{"name": "x", "domain": ".a", "path": "/", "expires": "bad"}],
        [{"name": "x", "domain": ".a", "path": "/", "expires": "bad"}],
        now) == []


def test_state_has_auth_uses_channel_auth_cookie():
    c = CtripCrawler({}, _LOG)
    assert c._state_has_auth(
        {"cookies": [{"name": "cticket", "value": "v"}]}) is True
    assert c._state_has_auth(
        {"cookies": [{"name": "unrelated", "value": "v"}]}) is False
    assert c._state_has_auth({}) is False
    # 没有登记认证 Cookie 的渠道不自动回写，避免把空壳覆盖快照
    plain = BaseCrawler({}, _LOG)
    assert plain._state_has_auth(
        {"cookies": [{"name": "x", "value": "v"}]}) is False


def test_should_refresh_snapshot_only_for_logged_in_collection(tmp_path):
    root = str(tmp_path)
    c = CtripCrawler({"user_data_dir": root}, _LOG)
    p = c.session_state_path
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.time(), "cookies": []}, f)
    assert c._should_refresh_snapshot(None) is True
    assert c._should_refresh_snapshot("login") is False
    assert c._should_refresh_snapshot("migrate") is False
    # 没有 saved_at（没确认过登录）时不回写
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump({"saved_at": 0, "cookies": []}, f)
    assert c._should_refresh_snapshot(None) is False
    # 未登记 AUTH_COOKIES 的渠道不回写。用本地替身，别拿真渠道当
    # 反例：同程/途牛已登记认证 Cookie，再拿它们当「未登记」会把
    # 修复测反。
    class _NoAuthCrawler(BaseCrawler):
        name = "noauth"
        profile_name = "noauth"

    n = _NoAuthCrawler({"user_data_dir": root}, _LOG)
    np = n.session_state_path
    os.makedirs(os.path.dirname(np), exist_ok=True)
    with io.open(np, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.time(), "cookies": []}, f)
    assert n._should_refresh_snapshot(None) is False


def test_browser_context_uses_restore_plan_and_guards_refresh():
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8", newline="").read()
    assert "plan = self._restore_plan(ctx.cookies(), saved)" in src
    assert "self._should_refresh_snapshot(save_session)" in src
    assert "not self._session_state_allowed(state, save_session)" in src
    assert "未检测到登录凭证（AUTH_COOKIES）" in src


def test_web_channel_auth_cookies_registered():
    """认证 Cookie 必须是「登录后才下发」的那几个。

    2026-11-02 匿名实测：同程 m.ly.com/www.ly.com 只下发 longKey；
    途牛 m.tuniu.com/flight 只有 connect.sid、passport 登录页只有
    PASSPORTSESSID；飞猪 www.fliggy.com 下发 cookie2/_m_h5_tk；去哪儿
    touch/www/h5 首页下发 QN1。上面清单里的名字在匿名上下文都不出现，
    才能作「已登录」证据；否则登出态也会被当成登录态回写空壳快照。
    """
    expected = {
        CtripCrawler: ("cticket",),
        FliggyCrawler: ("unb",),
        QunarCrawler: ("_q",),
        TongchengCrawler: ("memberIdNew", "cnUser"),
        TuniuCrawler: ("ssoUser", "TUNIUmuser", "tuniuuser"),
    }
    for cls, names in expected.items():
        assert cls.AUTH_COOKIES == names, cls.__name__
        c = cls({}, _LOG)
        for name in names:
            assert c._state_has_auth(
                {"cookies": [{"name": name, "value": "v"}]}) is True
        assert c._state_has_auth(
            {"cookies": [{"name": "unrelated", "value": "v"}]}) is False
