# -*- coding: utf-8 -*-
"""Shared recognition of OTA challenge/login pages.

Recognition only: callers record blocked/login and stop. This module does
not solve CAPTCHAs, drive sliders, or call third-party solving services.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChallengeSignal:
    kind: str          # login | slider | click | captcha | waf | refresh
    status: str        # login | blocked
    marker: str
    confidence: str = "high"

    @property
    def detail(self) -> str:
        labels = {
            "login": "登录门",
            "slider": "滑块验证",
            "click": "点选验证",
            "captcha": "人机验证",
            "waf": "访问验证",
            "refresh": "服务端强刷",
        }
        label = labels.get(self.kind, self.kind)
        return "%s（%s）" % (label, self.marker) if self.marker else label


# Normal list pages contain “登录/注册” in the header; only explicit walls
# match these markers.
_LOGIN_TEXT_RE = re.compile(
    r"请登录|请先登录|账号密码登录|扫码登录|验证码登录|手机登录/注册|手机号登录")
_LOGIN_URL_RE = re.compile(r"passport|/login|/signin", re.I)
_CHALLENGE_TEXT_RE = re.compile(
    r"验证码|人机验证|安全验证|访问验证|滑动验证|拖动|滑块|拼图|请完成验证")
_SLIDER_TEXT_RE = re.compile(r"滑动验证|拖动|滑块|拼图")
_CLICK_TEXT_RE = re.compile(r"点选|按顺序点击")
_WAF_TEXT_RE = re.compile(r"安全验证|访问验证|whaleguard|baxia", re.I)


def login_signal(marker: str = "login") -> ChallengeSignal:
    return ChallengeSignal("login", "login", str(marker or "login"))


def blocked_signal(kind: str = "captcha",
                   marker: str = "challenge") -> ChallengeSignal:
    return ChallengeSignal(kind or "captcha", "blocked", str(marker or ""))


def classify_text(text: str = "", url: str = "") -> Optional[ChallengeSignal]:
    """Classify a rendered page/body or URL as a login wall or challenge.

    Returns None for a normal page, including pages whose header merely has
    a “登录/注册” link. Login wins over challenge when both are present,
    because the operator action is the same and auth state is the stronger
    evidence.
    """
    body = str(text or "")
    target = str(url or "")
    url_hit = _LOGIN_URL_RE.search(target)
    text_hit = _LOGIN_TEXT_RE.search(body)
    if url_hit or text_hit:
        return login_signal((url_hit or text_hit).group(0))
    hit = (_CHALLENGE_TEXT_RE.search(body) or _CLICK_TEXT_RE.search(body)
           or _WAF_TEXT_RE.search(body))
    if not hit and not _WAF_TEXT_RE.search(target):
        return None
    if _SLIDER_TEXT_RE.search(body):
        kind = "slider"
    elif _CLICK_TEXT_RE.search(body):
        kind = "click"
    elif _WAF_TEXT_RE.search(body) or _WAF_TEXT_RE.search(target):
        kind = "waf"
    else:
        kind = "captcha"
    return blocked_signal(kind, hit.group(0) if hit else "waf")
