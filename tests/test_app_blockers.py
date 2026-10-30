# -*- coding: utf-8 -*-
"""拦路物识别：广告可自动关、验证码/人脸只能人工、登录走登录流。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_blockers import (BLOCK_AD, BLOCK_CAPTCHA, BLOCK_LOGIN,
                                   Block, detect_block, is_page_blank)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures", "zhixing_list_dump.xml")


def _xml(*texts_and_bounds):
    nodes = "".join(
        f'<node text="{t}" bounds="[{x1},{y1}][{x2},{y2}]" />'
        for t, x1, y1, x2, y2 in texts_and_bounds)
    return f'<hierarchy rotation="0">{nodes}</hierarchy>'


def test_captcha_detected_with_real_copy():
    """美团实机文案：『请点击绿色数字7』。"""
    xml = _xml(("身份核实", 0, 0, 900, 60),
               ("请点击绿色数字7", 0, 600, 900, 700))
    b = detect_block(xml)
    assert b.kind == BLOCK_CAPTCHA
    assert b.blocking is True


def test_captcha_beats_login_when_both_present():
    """验证码页常同时有『登录』字样——先判登录会误导用户去重登。"""
    xml = _xml(("请依次点击", 0, 0, 900, 60),
               ("立即登录", 0, 100, 900, 140))
    assert detect_block(xml).kind == BLOCK_CAPTCHA


def test_login_detected():
    xml = _xml(("登录后，解锁更多优惠", 0, 0, 900, 40),
               ("去登录", 0, 60, 900, 100))
    assert detect_block(xml).kind == BLOCK_LOGIN


def test_slider_captcha_detected():
    xml = _xml(("请完成下面的验证测试", 0, 0, 900, 40),
               ("向右滑动填充拼图", 0, 60, 900, 100))
    assert detect_block(xml).kind == BLOCK_CAPTCHA


def test_ad_with_close_button_returns_coords():
    xml = _xml(("新人专享", 0, 0, 900, 40),
               ("限时活动", 0, 60, 900, 100),
               ("关闭", 840, 20, 890, 60))
    b = detect_block(xml)
    assert b.kind == BLOCK_AD
    assert b.close_xy == (865, 40), b.close_xy


def test_ad_without_close_button_is_still_ad():
    xml = _xml(("限时活动", 0, 0, 900, 40))
    b = detect_block(xml)
    assert b.kind == BLOCK_AD
    assert b.close_xy is None


def test_clean_flight_page_has_no_block():
    with open(FIX, encoding="utf-8") as f:
        xml = f.read()
    b = detect_block(xml)
    assert b.kind == "", f"真实航班页不该被误判成 {b.kind}（{b.detail}）"


def test_empty_input_is_no_block():
    assert detect_block("").kind == ""


def test_page_blank_detects_shell():
    """美团验证码失败后页面退化成空壳——这不是 empty（没票）。"""
    assert is_page_blank("<hierarchy></hierarchy>") is True
    assert is_page_blank(_xml(("机票", 0, 0, 100, 40))) is True


def test_page_blank_false_for_real_page():
    with open(FIX, encoding="utf-8") as f:
        assert is_page_blank(f.read()) is False


def test_block_repr_and_flag():
    b = Block(BLOCK_AD, "x", None)
    assert b.blocking is True
    assert Block("").blocking is False
    assert "ad" in repr(b)
