# -*- coding: utf-8 -*-
"""STEALTH_JS：oscpu/connection 自洽 + profile_headers 单源。"""
import logging
import os
import re
import sys
import tempfile

import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawlers.base as base_mod  # noqa: E402
from crawlers.base import (BaseCrawler, MOBILE_UA, STEALTH_JS,  # noqa: E402
                           stealth_replacements)
from crawlers.base import profile_headers  # noqa: E402

_LOG = logging.getLogger("test_stealth_header")


class _MobileBase(BaseCrawler):
    use_mobile = True


_DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/131.0.0.0 Safari/537.36")
_FP_DESKTOP = {"ua": _DESKTOP_UA, "locale": "zh-CN", "is_mobile": False,
               "seed": 7}
_FP_MOBILE = {"ua": MOBILE_UA, "locale": "zh-CN", "is_mobile": True,
              "seed": 11}


def _script(mobile: bool, profile: str = "p1"):
    cls = _MobileBase if mobile else BaseCrawler
    with tempfile.TemporaryDirectory() as d:
        c = cls({"user_data_dir": d}, _LOG)
        c.profile_name = profile
        fp = c.fingerprint()
    js = STEALTH_JS
    for k, v in stealth_replacements(fp).items():
        js = js.replace(k, v)
    return js, fp


def _open(browser, mobile, profile="p1"):
    js, fp = _script(mobile, profile)
    ctx = browser.new_context(
        user_agent=fp["ua"], viewport=fp["viewport"],
        is_mobile=fp["is_mobile"], has_touch=fp["has_touch"])
    ctx.add_init_script(js)
    page = ctx.new_page()
    page.goto("about:blank")
    return ctx, page, fp


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


PROBE = """() => ({
  oscpuIn: 'oscpu' in navigator,
  oscpu: typeof navigator.oscpu,
  conn: typeof navigator.connection,
  eff: navigator.connection ? navigator.connection.effectiveType : null,
  save: navigator.connection ? navigator.connection.saveData : null,
  rtt: navigator.connection ? navigator.connection.rtt : null,
  dl: navigator.connection ? navigator.connection.downlink : null,
  sameConn: navigator.connection === navigator.connection
})"""


def _check_a(got):
    assert got["oscpuIn"] is False, got
    assert got["oscpu"] == "undefined", got
    assert got["conn"] == "object", got
    assert got["eff"] == "4g", got
    assert got["save"] is False, got
    assert 50 <= got["rtt"] <= 100, got
    assert 8 <= got["dl"] <= 12, got
    assert got["sameConn"] is True, got


def test_desktop_oscpu_and_connection_are_coherent(browser):
    ctx, page, fp = _open(browser, False, "desk-a")
    try:
        got = page.evaluate(PROBE)
    finally:
        ctx.close()
    assert fp["is_mobile"] is False
    _check_a(got)


def test_mobile_oscpu_and_connection_are_coherent(browser):
    ctx, page, fp = _open(browser, True, "mobile-a")
    try:
        got = page.evaluate(PROBE)
    finally:
        ctx.close()
    assert fp["is_mobile"] is True
    _check_a(got)


def test_connection_stable_same_profile_differs_across_profiles(browser):
    vals = {}
    for profile in ("same", "same", "other"):
        ctx, page, _fp = _open(browser, False, profile)
        try:
            got = page.evaluate(PROBE)
        finally:
            ctx.close()
        vals.setdefault(profile, []).append((got["rtt"], got["dl"]))
    assert vals["same"][0] == vals["same"][1], vals
    assert vals["same"][0] != vals["other"][0], vals


def test_no_unresolved_placeholders_including_connection():
    for mobile in (False, True):
        js, _ = _script(mobile)
        left = re.findall(r"__[A-Z0-9_]+__", js)
        assert not left, (mobile, left)


# ---------------- B: profile_headers 单源 ----------------

def test_desktop_headers_match_ua_and_locale():
    h1 = profile_headers(_FP_DESKTOP, {
        "Referer": "https://example.test/",
        "Accept-Encoding": "gzip, deflate, br",
    })
    h2 = profile_headers(_FP_DESKTOP, {
        "Referer": "https://example.test/",
        "Accept-Encoding": "gzip, deflate, br",
    })
    assert h1["User-Agent"] == _DESKTOP_UA
    assert h1["Accept-Language"] == "zh-CN,zh;q=0.9"
    major = re.search(r"Chrome/(\d+)", _DESKTOP_UA).group(1)
    assert 'v="%s"' % major in h1["sec-ch-ua"], h1
    assert h1["sec-ch-ua-platform"] == '"Windows"', h1
    assert h1["sec-ch-ua-mobile"] == "?0", h1
    assert h1["Referer"] == "https://example.test/", h1
    assert h1["Accept-Encoding"] == "gzip, deflate, br", h1
    # 同 profile 连续两次逐项完全一致（不随机化）
    assert list(h1.items()) == list(h2.items()), (h1, h2)


def test_mobile_headers_have_no_client_hints():
    h = profile_headers(_FP_MOBILE, {"Referer": "https://m.example.test/"})
    assert h["User-Agent"] == MOBILE_UA
    assert h["Accept-Language"] == "zh-CN,zh;q=0.9"
    assert not any(k.lower().startswith("sec-ch-ua") for k in h), h
    assert h["Referer"] == "https://m.example.test/", h


def test_mobile_tier_has_no_client_hints_in_headers_nor_useragentdata(browser):
    """移动档两侧同律：请求头不得出现任何 sec-ch-ua*，页面也不暴露
    navigator.userAgentData（Safari UA 不该带 Chromium 专属 UA-CH）。"""
    h = profile_headers(_FP_MOBILE, {"Referer": "https://m.example.test/"})
    assert not any(k.lower().startswith("sec-ch-ua") for k in h), h
    assert not any(k in h for k in ("sec-ch-ua", "sec-ch-ua-mobile",
                                    "sec-ch-ua-platform")), h
    ctx, page, fp = _open(browser, True, "mobile-hints")
    try:
        got = page.evaluate("""() => ({
          uad: typeof navigator.userAgentData,
          uadIn: 'userAgentData' in navigator,
          protoUad: 'userAgentData' in Navigator.prototype
        })""")
    finally:
        ctx.close()
    assert fp["is_mobile"] is True
    assert got["uad"] == "undefined", got
    assert got["uadIn"] is False, got
    assert got["protoUad"] is False, got


def test_headers_profile_scoped_and_identity_cannot_be_overridden():
    other = dict(_FP_DESKTOP, ua=_DESKTOP_UA.replace("Chrome/131", "Chrome/132"))
    h1 = profile_headers(_FP_DESKTOP, {
        "user-agent": "spoof",
        "accept-language": "spoof",
        "sec-ch-ua": "spoof",
        "X-Keep": "1",
    })
    h2 = profile_headers(other, {})
    assert h1["User-Agent"] == _DESKTOP_UA
    assert h1["Accept-Language"] == "zh-CN,zh;q=0.9"
    assert h1["sec-ch-ua"] != "spoof"
    assert h1["X-Keep"] == "1"
    assert h1["User-Agent"] != h2["User-Agent"]
    assert h1["sec-ch-ua"] != h2["sec-ch-ua"]


def test_accept_language_follows_locale():
    en = profile_headers({"ua": _DESKTOP_UA, "locale": "en-US",
                          "is_mobile": False}, {})
    assert en["Accept-Language"] == "en-US,en;q=0.9", en
    zh_tw = profile_headers({"ua": MOBILE_UA, "locale": "zh-TW",
                             "is_mobile": True}, {})
    assert zh_tw["Accept-Language"] == "zh-TW,zh;q=0.9", zh_tw
