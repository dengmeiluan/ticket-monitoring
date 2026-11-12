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


def test_mobile_headers_carry_self_consistent_client_hints():
    """移动档（r1063 T25 起是 Android Chrome）**必须**发 UA-CH。

    旧契约"移动档不发 UA-CH"是配合 iPhone/Safari UA 的；换成 Chromium 后，
    不发本身就是"UA 被改写"的证据。这里守的是**自洽**：版本与 UA 一致、
    `?1`、平台 Android。
    """
    h = profile_headers(_FP_MOBILE, {"Referer": "https://m.example.test/"})
    assert h["User-Agent"] == MOBILE_UA
    assert h["Accept-Language"] == "zh-CN,zh;q=0.9"
    major = re.search(r"Chrome/(\d+)", MOBILE_UA).group(1)
    assert 'v="%s"' % major in h["sec-ch-ua"], h
    assert h["sec-ch-ua-mobile"] == "?1", h
    assert h["sec-ch-ua-platform"] == '"Android"', h
    assert h["Referer"] == "https://m.example.test/", h




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
