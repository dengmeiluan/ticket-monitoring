# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r663_blocker_login_vs_captcha.py
- tests/test_r818_app_blocker_attribution.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import pytest
import sys

from core.pacing import classify_failure
from crawlers.app_blockers import BLOCK_AD, BLOCK_CAPTCHA, BLOCK_LOGIN, Block, detect_block
from crawlers.app_zhixing import AppZhixingCrawler


# ---- merged from tests/test_r663_blocker_login_vs_captcha.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _node(text, x1=0, y1=0, x2=900, y2=40):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _xml(*texts):
    return ('<?xml version="1.0"?><hierarchy rotation="0">'
            + "".join(_node(t) for t in texts) + "</hierarchy>")


def test_login_form_is_login_not_captcha():
    """手机号登录表单 = 要用户登录，不是风控验证码。"""
    xml = _xml("+86", "请输入手机号", "获取验证码",
               "您也可以尝试接听语音验证码", "遇到问题")
    b = detect_block(xml)
    assert b.kind == BLOCK_LOGIN, (b.kind, b.detail)
    assert b.kind != BLOCK_CAPTCHA


def test_login_form_wins_even_with_marketing_prices_on_screen():
    """登录页同时挂 ¥35/¥60 的机票券：不得因为"页面上有价格"就当数据页。"""
    xml = _xml("¥35", "机票券", "¥14", "酒店券",
               "+86", "请输入手机号", "获取验证码")
    assert detect_block(xml).kind == BLOCK_LOGIN


def test_real_captcha_still_detected():
    """真验证码（滑块/点选）仍必须判 captcha——收紧词表不能把功能弄丢。"""
    for copy in ("向右滑动填充拼图", "请依次点击", "拖动滑块", "完成验证"):
        b = detect_block(_xml(copy, "登录"))
        assert b.kind == BLOCK_CAPTCHA, (copy, b.kind)


def test_feature_page_with_marketing_entry_is_not_ad():
    """功能页自带「返里程/领券」入口，不是广告弹层。"""
    xml = _xml("单程", "往返", "多程", "北京", "上海", "10月31日",
               "舱位不限", "公务/头等舱", "返里程", "商旅出行", "搜索",
               "机票", "低价机票", "火车票")
    assert detect_block(xml).kind == ""


def test_small_marketing_overlay_is_still_ad():
    """真弹层（文案极少）即使没有关闭按钮也要如实上报 ad（既有契约）。"""
    b = detect_block(_xml("限时活动", "新人专享"))
    assert b.kind == BLOCK_AD


def test_closable_ad_still_returns_click_point():
    b = detect_block(_xml("限时活动", "关闭"))
    assert b.kind == BLOCK_AD
    assert b.close_xy is not None


# ---- merged from tests/test_r818_app_blocker_attribution.py ----

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
