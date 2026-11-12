# -*- coding: utf-8 -*-
"""硬风控 → 长时间冷却（默认 6h），普通滑块/登录的既有语义不变。

2026-11-06 背景：携程 `50003 环境存在风险`、飞猪「账号风险检测 / 需实名核验」、
阿里 `ContainerActivity` 白屏。原实现对 captcha 一律走指数退避、封顶
`breaker_cap_s`（默认 3600s），也就是**最多停 1 小时就再戳一次**；
而这类硬风控的风险分是累积的，按小时重试本身就在加重。
"""
import time

from core.pacing import ChannelBreaker, parse_pacing


def _t(**kw):
    return ChannelBreaker(**kw)


def test_hard_block_gets_long_cooldown():
    b = _t()
    now = 1_000_000.0
    cd = b.trip("p", "captcha", now=now,
                note="阿里安全容器 com.alibaba.wireless.security")
    assert cd == b.challenge_cooldown_s == 21600, cd
    ok, left = b.allow("p", now=now + 60)
    assert ok is False and left > 20000, (ok, left)


def test_plain_captcha_unchanged():
    """普通滑块仍走阶梯退避（base_s=300），不能被硬风控规则误伤。"""
    b = _t()
    assert b.trip("p", "captcha", now=1_000_000.0, note="请拖动滑块") == 300


def test_login_cooldown_unchanged():
    b = _t()
    assert b.trip("p", "login", now=1_000_000.0, note="请登录") == 900


def test_hard_block_does_not_accumulate_strikes():
    """硬风控不计 strikes：它不是普通限流，累积次数没有意义。"""
    b = _t()
    now = 1_000_000.0
    for i in range(3):
        b.trip("p", "captcha", now=now + i, note="需实名核验")
    st = b._rec("p")
    assert st["strikes"] == 0, st
    assert st["reason"] == "challenge", st


def test_switching_off_falls_back_to_ladder():
    b = _t(challenge_cooldown_s=0)
    assert b.trip("p", "captcha", now=1_000_000.0,
                  note="需实名核验") == 300


def test_markers_cover_observed_evidence():
    """这四条是 2026-11-06 实测到的真实文案，必须都被判成硬风控。"""
    b = _t()
    now = 1_000_000.0
    for note in ("当前登录环境存在风险，已被限制登录(50003)",
                 "账号风险检测 / 存在1条限制登录风险 / 请完成实名核验",
                 "当前账号行为异常，已被限制注册(40006)",
                 "com.alibaba.wireless.security.open.middletier.fc.ui."
                 "ContainerActivity"):
        assert b.trip("p", "captcha", now=now, note=note) == 21600, note


def test_config_roundtrip_and_clamp():
    assert parse_pacing({})["challenge_cooldown_s"] == 21600
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": 3600}}}
    )["challenge_cooldown_s"] == 3600
    # 上限一週、下限 0
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": 10 ** 9}}}
    )["challenge_cooldown_s"] == 604800
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": -5}}}
    )["challenge_cooldown_s"] == 0


def test_breaker_survives_reconfigure():
    b = _t()
    now = time.time()
    b.trip("p", "captcha", now=now, note="需实名核验")
    b.configure(base_s=600, cap_s=1800)   # 热重载只换阈值
    ok, left = b.allow("p", now=now + 10)
    assert ok is False and left > 20000, (ok, left)
