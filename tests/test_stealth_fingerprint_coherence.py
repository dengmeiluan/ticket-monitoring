# -*- coding: utf-8 -*-
"""STEALTH_JS 内部自洽：桌面/移动两档不串味，同 profile 幂等。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_stealth_fingerprint_coherence.py -q
"""
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
from crawlers.base import (BaseCrawler, STEALTH_JS,  # noqa: E402
                           stealth_replacements)

_LOG = logging.getLogger("test_stealth_fp")


class _MobileBase(BaseCrawler):
    use_mobile = True


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




PROBE = """() => ({
  vendor: navigator.vendor,
  platform: navigator.platform,
  touch: navigator.maxTouchPoints,
  hc: navigator.hardwareConcurrency,
  dm: typeof navigator.deviceMemory,
  sw: screen.width, sh: screen.height,
  aw: screen.availWidth, ah: screen.availHeight,
  cd: screen.colorDepth, pd: screen.pixelDepth,
  dpr: window.devicePixelRatio,
  chrome: typeof window.chrome,
  chromeIn: 'chrome' in window,
  uad: typeof navigator.userAgentData,
  uadIn: 'userAgentData' in navigator,
  dmIn: 'deviceMemory' in navigator,
  uadPlatform: navigator.userAgentData ? navigator.userAgentData.platform : null,
  uadMobile: navigator.userAgentData ? navigator.userAgentData.mobile : null,
  brands: navigator.userAgentData
    ? navigator.userAgentData.brands.map((b) => b.brand) : [],
  plugins: navigator.plugins.length,
  mimes: navigator.mimeTypes.length,
  pdf: Array.from(navigator.mimeTypes).map((m) => m.type),
  gl: (() => {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (!gl) return null;
    const e = gl.getExtension('WEBGL_debug_renderer_info');
    return e
      ? [gl.getParameter(e.UNMASKED_VENDOR_WEBGL),
         gl.getParameter(e.UNMASKED_RENDERER_WEBGL)]
      : [gl.getParameter(37445), gl.getParameter(37446)];
  })()
})"""


def _open(browser, mobile, profile="p1"):
    js, fp = _script(mobile, profile)
    ctx = browser.new_context(
        user_agent=fp["ua"], viewport=fp["viewport"],
        is_mobile=fp["is_mobile"], has_touch=fp["has_touch"])
    ctx.add_init_script(js)
    page = ctx.new_page()
    page.goto("about:blank")
    return ctx, page, fp








def test_same_profile_identical_and_different_profile_differs():
    a1, fp1 = _script(False, "alpha")
    a2, fp2 = _script(False, "alpha")
    b, fp3 = _script(False, "beta")
    assert fp1["seed"] == fp2["seed"]
    assert a1 == a2
    assert b != a1
    m1, _ = _script(True, "alpha")
    m2, _ = _script(True, "alpha")
    assert m1 == m2


def test_no_unresolved_placeholders():
    for mobile in (False, True):
        js, _ = _script(mobile)
        left = re.findall(r"__[A-Z0-9_]+__", js)
        assert not left, (mobile, left)




