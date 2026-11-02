# -*- coding: utf-8 -*-
"""r402：携程国际"没拿到/没解析出"不得记成"真无票"。

真实账本（2026-10-26 13:47）：
  ctrip PC SHA→BKK 2026-11-16  empty  「国际列表未解析到航班」

但同一航线同一日期在 10-27 10:03 采到 **221 行**。也就是说那条 empty
既不成立（有票），也没有证据支撑（note 自己写的是"未解析到"）。

`empty` 的语义是"站点明确说没票、无需操作"。而这两个分支实际是：
  · 一包响应都没到      → 本机/链路没拿到东西      → error
  · 收到包但解析不出航班 → 可能改版打穿了选择器      → error
在没有"明确无票"措辞时断言无票，会让读者以为真没航班而停止关注。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(here, "crawlers", "ctrip.py"),
                encoding="utf-8").read()


def test_no_response_is_error_not_empty():
    s = _src()
    i = s.index('"国际列表请求无响应"')
    block = s[max(0, i - 400):i + 400]
    assert '_status = "blocked" if _blocked else "error"' in block, block


def test_unparsed_is_error_not_empty():
    s = _src()
    i = s.index('"国际列表未解析到航班"')
    block = s[max(0, i - 300):i + 500]
    assert 'else "error"' in block, block
    assert 'else "empty"' not in block, block


def test_login_still_wins_over_error():
    """登录墙仍优先于 error（重登才能解，重试不能）。"""
    s = _src()
    i = s.index('"国际列表未解析到航班"')
    block = s[max(0, i - 300):i + 500]
    assert '"login" if need_login' in block, block


def test_explicit_no_flights_keeps_empty():
    """真正"明确无票"的地方仍应能记 empty（别把修复做过头）。

    携程国际这里没有"明确无票"的措辞分支，故整体不应再出现
    未解析→empty；但 blocked/login/ok 三个分支必须还在。
    """
    s = _src()
    for token in ('"blocked"', '"login"', '"ok"'):
        assert token in s
    assert re.search(r'_status = "blocked" if _blocked else "error"', s)
