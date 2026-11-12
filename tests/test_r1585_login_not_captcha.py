# -*- coding: utf-8 -*-
"""r1585：登录页不许被认成「人机验证」。

用户现场原话：「我就看到携程和飞猪要认证」——他能看到的是**登录页**，
而界面提示他「命中验证，需要人工点「去验证」」，两边对不上。

原因：`challenge._CHALLENGE_TEXT_RE` 里收了**裸「验证码」**，而登录页
（飞猪：「支付宝登录 / 验证码 / 账号密码 / 欢迎来到飞猪」）正是靠
这条被分到 captcha；同时 `_LOGIN_TEXT_RE` 又不认识「支付宝登录 / 账号密码」，
于是登录 > 验证的优先级没生效。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.challenge import classify_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def _read(name):
    return io.open(os.path.join(FIX, name), encoding="utf-8",
                   errors="replace").read()


def test_fliggy_login_page_is_login_not_captcha():
    sig = classify_text(text=_read("fliggy_login_page.xml"))
    assert sig is not None, "飞猪登录页没被识别出任何挑战（会被当成没数据）"
    assert sig.kind == "login", (
        "飞猪登录页被认成 %r —— 界面会提示「去验证」，而用户看到的是登录页"
        % (sig.kind,))


def test_ctrip_login_page_is_login():
    sig = classify_text(text=_read("ctrip_login_page.xml"))
    assert sig is not None and sig.kind == "login", sig


def test_train_page_is_not_a_challenge():
    assert classify_text(text=_read("tongcheng_train_page.xml")) is None, \
        "同程火车票页被当成挑战页"


def test_real_slider_still_detected():
    sig = classify_text(text="请拖动滑块完成验证")
    assert sig is not None and sig.kind in ("slider", "captcha"), sig
