# -*- coding: utf-8 -*-
"""挑战处置接缝：默认纯转发（现行行为不变），注册处理器后才接管。

负控（都在这里）：
- 未注册处理器 → 接缝不接手：goto 仍是原样转发，App 侧仍返回 captcha 块；
- 处理器抛异常 → 接缝自己吞掉并按「没接住」返回，采集流程不中断；
- 普通页面不得被误判成挑战（否则处理器会被无谓唤起）。
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.challenge import (ChallengeContext, ChallengeHandler,
                                ChallengeOutcome, after_navigation,
                                current_handler, handle_device,
                                install_navigation_guard, register_handler,
                                unregister_handler)

CHALLENGE_BODY = "请完成安全验证，拖动滑块完成拼图"
NORMAL_BODY = "北京 上海 MU5101 08:00 1180"


class _FakePage:
    def __init__(self, body="", url="https://example.invalid/"):
        self._body = body
        self.url = url
        self.goto_calls = []
        self.reads = 0

    def inner_text(self, selector):
        self.reads += 1
        return self._body

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))
        return "GOTO_RESULT"


class _RecordingHandler(ChallengeHandler):
    name = "recording"

    def __init__(self, handled=True):
        self.handled = handled
        self.nav_calls = []
        self.dev_calls = []

    def on_navigation(self, page, ctx):
        self.nav_calls.append(ctx)
        return ChallengeOutcome(handled=self.handled, detail="已处置")

    def on_device(self, dev, ctx):
        self.dev_calls.append((dev, ctx))
        return ChallengeOutcome(handled=self.handled, detail="已处置")


class _BoomHandler(ChallengeHandler):
    name = "boom"

    def on_navigation(self, page, ctx):
        raise RuntimeError("处理器炸了")

    def on_device(self, dev, ctx):
        raise RuntimeError("处理器炸了")


def _reset():
    unregister_handler()


def test_no_handler_seam_is_inert():
    """负控：没注册处理器时，接缝什么都不做（识别都不跑）。"""
    _reset()
    page = _FakePage(CHALLENGE_BODY)
    assert after_navigation(page) is False
    assert handle_device(object(), "<hierarchy/>") is None
    assert current_handler() is None


def test_navigation_guard_forwards_untouched_without_handler():
    """负控：没注册处理器时，goto 是纯转发——不读页面、不改返回值。"""
    _reset()
    page = _FakePage(CHALLENGE_BODY)
    assert install_navigation_guard(page) is True
    assert page.goto("https://example.invalid/x",
                     wait_until="domcontentloaded") == "GOTO_RESULT"
    assert page.goto_calls == [("https://example.invalid/x",
                                {"wait_until": "domcontentloaded"})]
    assert page.reads == 0, "没注册处理器就不该读页面正文"


def test_guard_is_installed_only_once_per_page():
    """同一页可能被多条采集流程复用，重复装会让回调嵌套。"""
    _reset()
    page = _FakePage(NORMAL_BODY)
    assert install_navigation_guard(page) is True
    assert install_navigation_guard(page) is False


def test_handler_takes_over_on_challenge_page():
    """注册处理器后：命中挑战页就交给它，识别结果与页面一并送达。"""
    _reset()
    handler = _RecordingHandler()
    register_handler(handler)
    try:
        page = _FakePage(CHALLENGE_BODY)
        install_navigation_guard(page)
        page.goto("https://example.invalid/list")
        assert len(handler.nav_calls) == 1
        ctx = handler.nav_calls[0]
        assert ctx.signal is not None
        assert ctx.signal.status == "blocked"
        assert ctx.signal.kind == "slider"
        assert ctx.url == "https://example.invalid/"
        assert ctx.body == CHALLENGE_BODY
    finally:
        _reset()


def test_normal_page_does_not_wake_the_handler():
    """负控：普通页面不得误判成挑战，否则处理器会被无谓唤起。"""
    _reset()
    handler = _RecordingHandler()
    register_handler(handler)
    try:
        page = _FakePage(NORMAL_BODY)
        install_navigation_guard(page)
        page.goto("https://example.invalid/list")
        assert handler.nav_calls == []
    finally:
        _reset()


def test_handler_exception_does_not_break_navigation():
    """负控：处理器炸了也不能带崩采集——接缝按「没接住」返回。"""
    _reset()
    register_handler(_BoomHandler())
    try:
        page = _FakePage(CHALLENGE_BODY)
        install_navigation_guard(page)
        assert page.goto("https://example.invalid/list") == "GOTO_RESULT"
        assert after_navigation(page) is False
    finally:
        _reset()


def test_device_seam_delegates_to_handler():
    """App 侧：dump 判定为挑战时交给处理器，xml 与设备一并送达。"""
    _reset()
    handler = _RecordingHandler()
    register_handler(handler)
    try:
        dev = object()
        out = handle_device(dev, "<hierarchy>验证码</hierarchy>",
                            ChallengeContext(plat="app_qunar", surface="APP"))
        assert out is not None and out.handled is True
        assert len(handler.dev_calls) == 1
        got_dev, ctx = handler.dev_calls[0]
        assert got_dev is dev
        assert ctx.body == "<hierarchy>验证码</hierarchy>"
        assert ctx.device is dev
        assert ctx.plat == "app_qunar"
    finally:
        _reset()


def test_register_unregister_round_trip():
    _reset()
    handler = _RecordingHandler()
    register_handler(handler)
    assert current_handler() is handler
    assert unregister_handler() is handler
    assert current_handler() is None
    page = _FakePage(CHALLENGE_BODY)
    assert after_navigation(page) is False


def test_app_clear_blockers_hands_captcha_to_handler():
    """App 采集：处理器接住验证码 → 重新 dump 后继续，不再返回 captcha 块。"""
    from crawlers.app_base import AppCrawler

    _reset()

    class _Dev:
        def __init__(self):
            self.dumps = 0

        def dump(self):
            self.dumps += 1
            if self.dumps == 1:
                return ('<hierarchy><node text="请完成安全验证" '
                        'bounds="[0,0][900,60]" /></hierarchy>')
            return ('<hierarchy><node text="MU5101" '
                    'bounds="[0,0][900,60]" /></hierarchy>')

        def tap(self, *a):
            return None

    class _Handler(ChallengeHandler):
        name = "app-solver"

        def on_device(self, dev, ctx):
            return ChallengeOutcome(handled=True)

    register_handler(_Handler())
    try:
        crawler = AppCrawler({}, logging.getLogger("seam-test"))
        dev = _Dev()
        xml, block = crawler._clear_blockers(dev, dev.dump())
        assert block.kind == "", "处理器接住后不该再返回 captcha 块：%s" % block
        assert "MU5101" in xml
    finally:
        _reset()


def test_app_clear_blockers_unchanged_without_handler():
    """负控：没注册处理器时，App 侧照旧返回 captcha 块（现行行为）。"""
    from crawlers.app_base import AppCrawler

    _reset()
    crawler = AppCrawler({}, logging.getLogger("seam-test"))
    xml = ('<hierarchy><node text="请完成安全验证" '
           'bounds="[0,0][900,60]" /></hierarchy>')
    _xml, block = crawler._clear_blockers(object(), xml)
    assert block.kind == "captcha"


# ---------- 真浏览器核对（守卫对真实 Playwright Page 必须透明） ----------

_HTML = ("data:text/html;charset=utf-8,<html><body><h1>%s</h1>"
         "</body></html>")


@pytest.fixture(scope="module")
def browser():
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        if not Path(driver.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        b = driver.chromium.launch()
        yield b
        b.close()


def test_real_page_guard_is_transparent(browser):
    """真浏览器：没注册处理器时，goto 的返回值与页面渲染都不受影响。"""
    _reset()
    ctx = browser.new_context()
    plain = ctx.new_page()
    expect = plain.goto(_HTML % "hello", wait_until="domcontentloaded")
    page = ctx.new_page()
    install_navigation_guard(page)
    got = page.goto(_HTML % "hello", wait_until="domcontentloaded")
    assert got == expect, "守卫改了 goto 的返回值：%r vs %r" % (got, expect)
    assert "hello" in page.inner_text("body")


def test_real_page_hands_challenge_to_handler(browser):
    """真浏览器：挑战页被识别 → 处理器接手并 reload → 页面回到可读状态。"""
    from crawlers.challenge import install_navigation_guard

    _reset()
    seen = []

    class _Handler(ChallengeHandler):
        name = "real-solver"

        def on_navigation(self, pg, ctx):
            seen.append(ctx.signal.kind if ctx.signal else None)
            pg.goto(_HTML % "solved", wait_until="domcontentloaded")
            return ChallengeOutcome(handled=True)

    register_handler(_Handler())
    try:
        ctx = browser.new_context()
        page = ctx.new_page()
        install_navigation_guard(page)
        page.goto(_HTML % CHALLENGE_BODY, wait_until="domcontentloaded")
        assert seen == ["slider"], seen
        assert "solved" in page.inner_text("body"), page.inner_text("body")
    finally:
        _reset()
