# -*- coding: utf-8 -*-
"""r1592：登录墙冷却必须逐次翻倍并封顶（今天携程/飞猪被撞到登不上）。

一次偶发的登录墙该 15 分钟就回来；但如果**反复撞**（App + 浏览器两个端，
每家一小时 25–40 次），固定 15 分钟就是在持续加重风险分。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import ChannelBreaker  # noqa: E402


def _pacer():
    return ChannelBreaker(base_s=300, cap_s=3600,
                          login_cooldown_s=900, challenge_cooldown_s=21600)


def test_login_cooldown_escalates_and_caps():
    p = _pacer()
    got = []
    for _ in range(6):
        got.append(p.trip("fliggy", "login"))
    assert got[0] == 900, got
    assert got[1] == 1800, got
    assert got[2] == 3600, got
    assert got[3] == 7200, got
    assert got[4] == 14400, got
    assert got[5] == 14400, "没封顶：%s" % got


def test_success_resets_login_escalation():
    p = _pacer()
    p.trip("fliggy", "login")
    p.trip("fliggy", "login")
    for _ in range(3):
        p.note_ok("fliggy", need=1)
    assert p.trip("fliggy", "login") == 900, "成功之后应从 900 重新开始"


def test_other_breaker_kinds_unaffected():
    p = _pacer()
    cd = p.trip("fliggy", "captcha")
    assert cd >= 0, cd
