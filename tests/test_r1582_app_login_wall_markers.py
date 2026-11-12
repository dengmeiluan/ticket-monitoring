# -*- coding: utf-8 -*-
"""r1582：飞猪/携程的登录页必须被认成登录墙（否则白跑 200 秒还记成超时）。

证据来自生产自动留证（2026-11-11）：
  · 飞猪 `app-login` 失败 dump：支付宝登录 / 验证码 / 账号密码 / 欢迎来到飞猪
  · 携程 `航班明细` 失败 dump：手机验证码登录 / 请输入手机号 / 获取验证码
飞猪那份原判据一条都不命中 → 登录页被读成"没数据"。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def _read(name):
    return io.open(os.path.join(FIX, name), encoding="utf-8",
                   errors="replace").read()


def _c():
    return AppCrawler({}, None)


def test_fliggy_login_page_is_recognised():
    assert _c().is_login_wall(_read("fliggy_login_page.xml")) is True, (
        "飞猪登录页没被认出来：会被当成'没数据'白跑 200 秒并累计熔断")


def test_ctrip_login_page_is_recognised():
    assert _c().is_login_wall(_read("ctrip_login_page.xml")) is True, (
        "携程登录页没被认出来")


def test_train_page_is_not_a_login_wall():
    assert _c().is_login_wall(_read("tongcheng_train_page.xml")) is False, (
        "同程火车票页被误判成登录墙")


def test_plain_page_is_not_a_login_wall():
    assert _c().is_login_wall('<node text="航班明细"/>') is False
