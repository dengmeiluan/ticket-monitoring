# -*- coding: utf-8 -*-
"""r663：接入去哪儿 App 时暴露的两处拦路物误判（真机 dump 复现）。

一、登录页被判成**验证码**。
   去哪儿登录页文案里有「获取验证码」「您也可以尝试接听语音验证码」，
   旧词表收了裸「验证码」→ 判 captcha。处置完全不同：captcha 要人工接管
   并触发 300s 熔断，而这里只要**让用户登录**（走内嵌登录画面）。

二、机票首页被判成**广告**。
   首页自带「返里程」「领券」入口 → 命中营销词，且首页没有航班号/价格
   （`has_payload=False`）→ 判 ad，整轮采集作废。

两条都用真机 dump 的**结构特征**复现（不含业务正文），不写死具体页面。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_blockers import (BLOCK_AD, BLOCK_CAPTCHA, BLOCK_LOGIN,
                                   detect_block)


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
