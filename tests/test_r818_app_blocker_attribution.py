# -*- coding: utf-8 -*-
"""r818：App 渠道把「导航失败」误记成 blocked，pacing 会当成人机验证熔断 300s。

2026-11-02 线上：19:19:03 智行「设置航线失败：未进入城市选择页」后立即
`命中captcha，熔断 300s`——但当时并没有任何验证码证据，只是 App 还停在
旧页面/城市选择页没打开。`classify_failure()` 把路径状态 `blocked` 一律
归为 captcha；导航失败应记 timeout（下一轮自然重试），真验证码由
`detect_block()` 识别后另记 app-blocker/captcha。

同轮还钉住：明细页被广告/验证码/人脸挡住 ≠ 登录失效，只有 block.kind
为 login 才置 login_suspect，避免把风控拦截又转成一次「请重登」。
"""
import logging

import pytest

from crawlers.app_blockers import Block
from crawlers.app_zhixing import AppZhixingCrawler
from core.pacing import classify_failure

_LOG = logging.getLogger("t_r818")


def test_blocked_is_captcha_but_timeout_is_not():
    # 产品判据：这是误记 blocked 的代价，不是测试副本
    assert classify_failure(["blocked"]) == "captcha"
    assert classify_failure(["timeout"]) == ""


def test_route_navigation_failures_are_not_blocked():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("app_zhixing.py", "app_qunar.py"):
        src = open(os.path.join(root, "crawlers", name),
                   encoding="utf-8").read()
        assert 'path_note("app-route", "blocked"' not in src, name
        assert 'path_note("app-route", "timeout"' in src, name


@pytest.fixture
def zx(monkeypatch):
    c = AppZhixingCrawler({}, _LOG)
    c._skip_route = False
    c.login_suspect = False
    return c


def _run_with_block(c, monkeypatch, block):
    def _one(*a, **k):
        return [], block

    monkeypatch.setattr(c, "_one_date_detail", _one)
    return c._enter_detail_and_parse(
        object(), "SHA", "BKK", ["2026-11-16"])


def test_captcha_block_does_not_prompt_login(zx, monkeypatch):
    got, blocked = _run_with_block(
        zx, monkeypatch, Block("captcha", "滑块验证"))
    assert got == [] and blocked is True
    assert zx.login_suspect is False


def test_ad_block_does_not_prompt_login(zx, monkeypatch):
    _got, blocked = _run_with_block(
        zx, monkeypatch, Block("ad", "营销弹层（未找到关闭按钮）"))
    assert blocked is True
    assert zx.login_suspect is False


def test_login_block_prompts_login(zx, monkeypatch):
    _got, blocked = _run_with_block(
        zx, monkeypatch, Block("login", "手机号登录表单"))
    assert blocked is True
    assert zx.login_suspect is True
