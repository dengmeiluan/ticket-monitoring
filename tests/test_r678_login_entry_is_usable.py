# -*- coding: utf-8 -*-
r"""r678：弹窗登录的入口必须真的能让人登录。

issue #10 评论：「途牛不知道为什么弹窗登录不了」。实测根因不是网站整体
故障，而是入口选错——`https://www.tuniu.com/` 在采集同款移动指纹下被腾讯
云 WAF 拦成「WAF 拦截页面」（正文只有「安全检测/无法继续」，登录控件 0 个）。
用户对着那页当然登不进去。

判据（真浏览器、真网络、只读，不驱动登录、不绕验证）：
- 每个渠道的 `LOGIN_SLOTS[*].login_url` 在移动指纹下必须落到「有登录控件
  或明确登录文案」的页面，且不得是 WAF/拦截页；
- 途牛必须落在 passport 登录页（此前 www 首页是拦截页）。

网络不可用 / 站点临时拒绝时跳过（不把外部状态当代码缺陷），但**拦截页**
一旦出现就红——那不是网络问题，是入口选错。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
# 明确不是「用户可登录页面」的措辞（WAF/拒绝/停服）
BLOCK_WORDS = ("WAF", "安全检测", "Web应用防火墙", "无法继续", "访问被拒绝",
               "Forbidden", "站点已停止")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    from pathlib import Path
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        yield b
        b.close()


def _open(browser, url):
    ctx = browser.new_context(
        user_agent=UA_IPHONE, viewport={"width": 390, "height": 844},
        is_mobile=True, has_touch=True, locale="zh-CN",
        timezone_id="Asia/Shanghai")
    try:
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=35000)
            pg.wait_for_timeout(2500)
        except Exception as e:
            pytest.skip("站点不可达（外部状态，不作缺陷）：%s" % type(e).__name__)
        return {
            "url": pg.url, "title": pg.title(),
            "text": pg.inner_text("body")[:1500],
            "password": pg.locator("input[type=password]").count(),
            "tel": pg.locator(
                "input[type=tel],input[inputmode=numeric]").count(),
        }
    finally:
        ctx.close()


def _assert_login_surface(rec, name):
    hit = [w for w in BLOCK_WORDS if w in (rec["title"] + rec["text"])]
    assert not hit, "%s 登录入口落到拦截页（%s）：%s" % (
        name, "/".join(hit), rec["url"])
    assert rec["password"] + rec["tel"] > 0 or "登录" in rec["text"], (
        "%s 登录入口没有任何登录控件/文案，用户无从登录：%s"
        % (name, rec["url"]))


def test_tuniu_login_url_is_a_real_login_page(browser):
    from core.login_slots import LOGIN_SLOTS
    rec = _open(browser, LOGIN_SLOTS["tuniu"]["login_url"])
    assert "passport.tuniu.com" in rec["url"], (
        "途牛登录入口又回到会触发 WAF 的首页：%s" % rec["url"])
    _assert_login_surface(rec, "途牛")
    assert rec["password"] + rec["tel"] > 0, "途牛登录页没有可输入的登录控件"


def test_ctrip_login_url_is_not_an_interstitial(browser):
    from core.login_slots import LOGIN_SLOTS
    rec = _open(browser, LOGIN_SLOTS["ctrip"]["login_url"])
    _assert_login_surface(rec, "携程")
