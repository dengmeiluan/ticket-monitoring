# -*- coding: utf-8 -*-
"""r816：认证 Cookie 必须是「登录后才下发」的，不能拿匿名/风控 Cookie 顶替。

2026-11-02 匿名实测（全新无 Cookie 上下文）：
  - 去哪儿 QN1 在 touch/www/h5 首页就下发；QN271 是 qmark SDK 的 fp；
  - 飞猪 cookie2/_m_h5_tk 在 www.fliggy.com 匿名页就下发；
  - 携程 cticket、同程 memberIdNew/cnUser、途牛 ssoUser/TUNIUmuser/
    tuniuuser、去哪儿 _q 在匿名页均不出现。
QN1/cookie2 被误当 AUTH 时，登出态也会被当成登录态回写快照 →
覆盖上一份可用快照，用户下一轮就「又掉登录」。
"""
import logging
import time

from crawlers.base import BaseCrawler
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler

_LOG = logging.getLogger("t_r816")


def _ck(name, value="v", expires=-1):
    return {"name": name, "value": value, "expires": expires}


def test_auth_markers_are_login_only_and_cover_web_channels():
    assert CtripCrawler.AUTH_COOKIES == ("cticket",)
    assert FliggyCrawler.AUTH_COOKIES == ("unb",)
    assert "cookie2" not in FliggyCrawler.AUTH_COOKIES
    assert QunarCrawler.AUTH_COOKIES == ("_q",)
    assert "QN1" not in QunarCrawler.AUTH_COOKIES
    assert set(TongchengCrawler.AUTH_COOKIES) == {"memberIdNew", "cnUser"}
    assert set(TuniuCrawler.AUTH_COOKIES) == {
        "ssoUser", "TUNIUmuser", "tuniuuser"}


def test_state_has_auth_rejects_anonymous_and_expired_cookies():
    now = time.time()
    q = QunarCrawler({}, _LOG)
    # QN1 是匿名/风控 Cookie，单靠它不能证明登录
    assert q._state_has_auth(
        {"cookies": [_ck("QN1", "visitor", now + 3600)]}) is False
    # 空值不算；已过期的持久 Cookie 不算
    assert q._state_has_auth({"cookies": [_ck("_q", "")]}) is False
    assert q._state_has_auth(
        {"cookies": [_ck("_q", "user", now - 1)]}) is False
    # session Cookie 与未过期持久 Cookie 才算
    assert q._state_has_auth({"cookies": [_ck("_q", "user", -1)]}) is True
    assert q._state_has_auth(
        {"cookies": [_ck("_q", "user", now + 3600)]}) is True

    f = FliggyCrawler({}, _LOG)
    assert f._state_has_auth(
        {"cookies": [_ck("cookie2", "anon", now + 3600)]}) is False
    assert f._state_has_auth(
        {"cookies": [_ck("unb", "12345", now + 3600)]}) is True


def test_qunar_snapshot_with_only_risk_cookie_not_refreshable():
    q = QunarCrawler({}, _LOG)
    state = {"cookies": [
        _ck("QN1", "visitor", -1),
        _ck("QN48", "x", -1),
        _ck("QN300", "x", -1),
    ]}
    assert q._state_has_auth(state) is False


def test_qunar_detail_clears_stale_scope_login():
    """去哪儿任一 scope 真出数 → 更早的别的 scope 拒绝不再催登录。"""
    from datetime import datetime
    from webui import _clear_qunar_stale_auth

    def et(v):
        return datetime.fromisoformat(v).timestamp() if v else 0.0

    scopes = {
        "international": {"needs_login": False,
                          "detail_at": "2026-11-02 19:17:30",
                          "reason": "会话失效"},
        "unknown": {"needs_login": True,
                    "detail_at": "2026-11-02 17:36:58",
                    "reason": "会话失效"},
        # 比最新成功还晚的拒绝是真拒绝，不能清
        "newer": {"needs_login": True,
                  "detail_at": "2026-11-02 19:20:00",
                  "reason": "会话失效"},
    }
    _clear_qunar_stale_auth(
        scopes, et("2026-11-02 16:59:44"), et)
    assert scopes["unknown"]["needs_login"] is False
    assert scopes["unknown"]["reason"] == ""
    assert scopes["newer"]["needs_login"] is True
    # 最新成功的 scope 自己也可能留着旧「会话失效」文案：needs_login
    # 已是 False，但文案不能继续吓用户说会话失效（线上 19:17 实报）。
    assert scopes["international"]["reason"] == ""
    assert scopes["newer"]["reason"] == "会话失效"


def test_qn1999_only_prompts_login_without_auth_cookie():
    # 单次=间歇放行；连续≥2 且无认证 Cookie 才请重登
    assert QunarCrawler._qn1999_is_login(1, False) is False
    assert QunarCrawler._qn1999_is_login(2, False) is True
    # 认证 Cookie 仍在场时，重登救不回 1999，按软拒退避
    assert QunarCrawler._qn1999_is_login(2, True) is False
    assert QunarCrawler._qn1999_is_login(9, True) is False


def test_login_snapshot_requires_auth_cookie():
    q = QunarCrawler({}, _LOG)
    anonymous = {"cookies": [_ck("QN1", "visitor", -1)]}
    logged_in = {"cookies": [_ck("_q", "user", -1)]}
    # 登录窗口“我已登录完成”不是登录证据：无 AUTH 不落盘
    assert q._session_state_allowed(anonymous, "login") is False
    assert q._session_state_allowed(logged_in, "login") is True
    # 采集态同理；迁移不要求认证
    assert q._session_state_allowed(anonymous, None) is False
    assert q._session_state_allowed(anonymous, "migrate") is True


def test_expired_auth_does_not_count_for_other_channels():
    now = time.time()
    for cls, name in (
            (CtripCrawler, "cticket"),
            (TongchengCrawler, "memberIdNew"),
            (TuniuCrawler, "ssoUser")):
        c = cls({}, _LOG)
        assert c._state_has_auth(
            {"cookies": [_ck(name, "old", now - 60)]}) is False
        assert c._state_has_auth(
            {"cookies": [_ck(name, "fresh", now + 3600)]}) is True
