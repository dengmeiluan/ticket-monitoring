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


def _ctx_env(monkeypatch):
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
    return ctx, chromium


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


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def test_mobile_context_is_safari_coherent(browser):
    ctx, page, fp = _open(browser, True)
    try:
        got = page.evaluate(PROBE)
    finally:
        ctx.close()
    assert fp["is_mobile"] is True
    assert got["vendor"] == "Apple Computer, Inc."
    assert got["platform"] == "iPhone"
    # 移动档不得出现 Chromium 专属对象 / 桌面触摸特征
    assert got["chrome"] == "undefined", got
    assert got["chromeIn"] is False, got
    assert got["uad"] == "undefined", got
    assert got["uadIn"] is False, got
    assert got["dm"] == "undefined", got
    assert got["dmIn"] is False, got
    assert got["touch"] == 5
    assert (got["sw"], got["sh"]) == (390, 844), got
    assert (got["aw"], got["ah"]) == (390, 844), got
    assert got["dpr"] == 3
    assert got["cd"] == 24 and got["pd"] == 24
    assert got["plugins"] >= 1 and got["mimes"] >= 1
    assert "application/pdf" in got["pdf"], got["pdf"]
    assert got["gl"] == ["Apple Inc.", "Apple GPU"], got["gl"]


def test_desktop_context_is_windows_chrome_coherent(browser):
    ctx, page, fp = _open(browser, False)
    try:
        got = page.evaluate(PROBE)
    finally:
        ctx.close()
    assert fp["is_mobile"] is False
    assert got["vendor"] == "Google Inc."
    assert got["platform"] == "Win32"
    assert got["chrome"] == "object"
    assert got["chromeIn"] is True, got
    assert got["touch"] == 0
    assert (got["sw"], got["sh"]) == (1366, 900), got
    assert (got["aw"], got["ah"]) == (1366, 900), got
    assert got["dpr"] == 1
    assert got["cd"] == 24 and got["pd"] == 24
    assert got["uad"] == "object"
    assert got["uadIn"] is True, got
    assert got["uadPlatform"] == "Windows"
    assert got["uadMobile"] is False
    assert "HeadlessChrome" not in got["brands"]
    assert got["dm"] == "number"
    assert got["dmIn"] is True, got
    assert got["plugins"] >= 1 and got["mimes"] >= 1
    assert "application/pdf" in got["pdf"], got["pdf"]
    assert got["gl"] and got["gl"][0].startswith("Google Inc. ("), got["gl"]
    assert "ANGLE" in got["gl"][1], got["gl"]
    assert "Apple GPU" not in " ".join(got["gl"])


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


def test_browser_context_injects_resolved_script(monkeypatch):
    ctx, _ = _ctx_env(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        c = _MobileBase({"user_data_dir": d}, _LOG)
        with c._browser_context(True, False, 0, None):
            pass
    js = ctx.scripts[0]
    assert "Apple Computer, Inc." in js
    assert '"Apple GPU"' in js
    assert not re.findall(r"__[A-Z0-9_]+__", js)


def test_injected_scripts_follow_profile(monkeypatch):
    """真实注入路径：同 profile 两次一致，换 profile 必须不同。"""
    scripts = []
    for profile in ("alpha", "alpha", "beta"):
        ctx, _ = _ctx_env(monkeypatch)
        with tempfile.TemporaryDirectory() as d:
            c = BaseCrawler({"user_data_dir": d}, _LOG)
            c.profile_name = profile
            with c._browser_context(True, False, 0, None):
                pass
        scripts.append(ctx.scripts[0])
    assert scripts[0] == scripts[1]
    assert scripts[0] != scripts[2]
