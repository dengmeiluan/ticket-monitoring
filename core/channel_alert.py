# -*- coding: utf-8 -*-
"""渠道级告警：连续 N 轮零数据就主动喊一声，而不是等人去看面板。

纯函数，零 I/O：判定（该不该发）与措辞（发什么）分开，便于单测。
"""
# 渠道显示名统一取自单一事实源：新增 App 渠道时不必再改这里
# （写死清单会让新渠道的告警文案露出裸 id）。
from core.channels import CHANNEL_CN as CN  # noqa: E402


def should_alert(streak, rounds, last_ts, now, cooldown_s):
    """连续零数据 ≥ rounds 轮，且距上次告警 ≥ cooldown 才发。"""
    try:
        n = int(streak or 0)
        need = max(1, int(rounds or 1))
        prev = float(last_ts or 0)
        now = float(now)
    except (TypeError, ValueError):
        return False
    if n < need:
        return False
    return (now - prev) >= max(0, int(cooldown_s or 0))


def alert_text(plat, streak, last_ok_ts, now=None, hint=""):
    """title/desp：说清"哪家、多久、下一步做什么"。"""
    import time as _t
    name = CN.get(plat, plat)
    title = "[渠道告警] %s 连续 %d 轮无数据" % (name, int(streak or 0))
    if last_ok_ts:
        gap = max(0, int(((now or _t.time()) - float(last_ok_ts)) // 60))
        ago = "上次出数在 %d 分钟前" % gap
    else:
        ago = "本次运行内从未出数"
    desp = ("%s：%s。\n可能原因：验证码/限流、会话失效、页面改版。\n"
            "处理：控制台「节流状态」→ 看现场/去验证；验证通过会自动复位并补采。"
            % (name, ago))
    if hint:
        desp += "\n现场：%s" % str(hint)[:160]
    return title, desp
