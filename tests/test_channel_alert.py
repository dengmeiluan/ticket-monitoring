# -*- coding: utf-8 -*-
"""渠道级告警：连续零数据才喊，且不刷屏。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channel_alert import alert_text, should_alert  # noqa: E402


def test_should_alert_gates_by_rounds_and_cooldown():
    assert not should_alert(2, 3, 0, 10000, 3600)     # 轮次不够
    assert should_alert(3, 3, 0, 10000, 3600)         # 刚好达标
    assert not should_alert(3, 3, 9000, 10000, 3600)  # 冷却内
    assert should_alert(4, 3, 0, 10000, 3600)
    assert not should_alert(0, 3, 0, 10000, 3600)


def test_alert_text_names_channel_and_next_step():
    title, desp = alert_text("qunar", 3, None, now=0)
    assert "去哪儿" in title and "3" in title
    assert "从未出数" in desp
    assert "去验证" in desp                     # 给出下一步，而不是只报故障
    t2, d2 = alert_text("ctrip", 4, 0, now=7200)   # 0=无历史
    t3, d3 = alert_text("ctrip", 4, 7200 - 7200, now=7200)
    t4, d4 = alert_text("ctrip", 4, 0.1, now=7200)
    assert "从未出数" in d2
    assert "上次出数" in d4 and "分钟前" in d4
