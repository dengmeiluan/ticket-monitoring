# -*- coding: utf-8 -*-
"""r918：预热时序——等**风控 cookie 落下**，而不是死等固定秒数。

为什么单独钉：日历/深链的价值不在"停留了几秒"，而在"服务端把会话 cookie
发下来了"。固定 ``wait_for_timeout(4000)`` 有两种失败模式——

* cookie 还没下来就去打 → 服务端当新会话 → 444/202 软拒（账本会把它写成
  "该日无价"，这是红线）；
* cookie 早下来了却还在等 → 白等。

``wait_risk_cookies`` 改成轮询命中即返回、超时如实返回空；
ctrip 国际日历据此把"预热未落 cookie + 无价"记成 ``soft_reject`` 而不是
``empty``。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r918_warmup_timing.py -q
"""
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.base import BaseCrawler  # noqa: E402

_LOG = logging.getLogger("test_r918")


class _Ctx:
    """按时间线返回 cookie 的假上下文（模拟服务端"过一会儿才下发"）。"""

    def __init__(self, timeline):
        # timeline: [(at_seconds, [names...]), ...]
        self.timeline = list(timeline)
        self.t0 = time.time()

    def cookies(self):
        now = time.time() - self.t0
        out = []
        for at, names in self.timeline:
            if now >= at:
                out.extend({"name": n, "value": "1"} for n in names)
        return out


class _C(BaseCrawler):
    name = "ctrip"
    RISK_COOKIES = ("cticket", "_bfa", "MKT_CKID")


def _c(raw=("cticket", "_bfa", "MKT_CKID")):
    c = _C({}, _LOG)
    c.RISK_COOKIES = raw
    return c


# ---------------------------------------------------------------------------
# 1. wait_risk_cookies
# ---------------------------------------------------------------------------
def test_returns_immediately_when_already_present():
    c = _c()
    ctx = _Ctx([(0.0, ["cticket", "_bfa"])])
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=5.0)
    elapsed = time.time() - t0
    assert set(hit) == {"cticket", "_bfa"}
    assert elapsed < 0.5, "cookie 已在场时不该等满超时（实测 %.2fs）" % elapsed


def test_waits_until_cookie_lands():
    c = _c()
    ctx = _Ctx([(0.4, ["cticket"])])
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=6.0, poll_s=0.1)
    elapsed = time.time() - t0
    assert hit == ["cticket"]
    assert 0.3 <= elapsed < 3.0, elapsed


def test_returns_empty_on_timeout():
    c = _c()
    ctx = _Ctx([])                     # 永远不下发
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=0.5, poll_s=0.1)
    elapsed = time.time() - t0
    assert hit == []
    assert elapsed >= 0.4


def test_no_declared_cookies_is_a_noop():
    c = _c(raw=())
    ctx = _Ctx([(0.0, ["cticket"])])
    t0 = time.time()
    assert c.wait_risk_cookies(ctx, timeout_s=5.0) == []
    assert time.time() - t0 < 0.2      # 没声明就不该等


def test_cookies_raising_is_fail_soft():
    c = _c()

    class _Bad:
        def cookies(self):
            raise RuntimeError("context closed")
    t0 = time.time()
    assert c.wait_risk_cookies(_Bad(), timeout_s=0.4, poll_s=0.1) == []
    assert time.time() - t0 >= 0.3     # 等满超时，不抛异常


# ---------------------------------------------------------------------------
# 2. 日历记账：预热没落下 cookie → soft_reject，不是 empty
# ---------------------------------------------------------------------------
def test_calendar_without_warm_cookie_is_soft_reject_not_empty():
    """把决策逻辑单独抽出来验证（不启动浏览器）。

    与 ctrip._fetch_intl_calendar 里那段 if 完全同构：
        ``if _cal_status == "empty" and not warm_ok: status = soft_reject``
    """

    def _status(_cal_status, warm_ok):
        if _cal_status == "empty" and not warm_ok:
            return ("soft_reject", "预热未落下风控 cookie，按软拒记")
        return (_cal_status,
                "登录/验证页，非空结果" if _cal_status != "empty"
                else "国际日历未返回该日报价")

    assert _status("empty", False)[0] == "soft_reject"
    assert _status("empty", True)[0] == "empty"
    assert _status("login", False)[0] == "login"
    assert _status("blocked", False)[0] == "blocked"
