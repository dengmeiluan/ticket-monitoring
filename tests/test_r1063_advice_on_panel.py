# -*- coding: utf-8 -*-
"""r1063 T194：自动诊断**上屏**（pacing 载荷里的 advice_top + 面板那一行）。

为什么要有它：`core.advise` 只做过 CLI，面板里看不见——用户要开终端才知道
"现在最该做什么"，属"一切可视化"的缺口。改成后端把结论塞进**同一份** pacing
载荷（不发第二次请求，避免卡片与建议时序错位），前端只画一行 `.snote`。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.advise import top_from_pacing  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_empty_payload_gives_nothing():
    assert top_from_pacing({}) == []
    assert top_from_pacing(None) == []


def test_app_risk_hint_is_panel_safe():
    """面板是纯文本：不许把 Markdown 的 ** 直接画出来。"""
    out = top_from_pacing({"degraded": {"app_risk_blocked": True}})
    assert out, "App 风控降级时必须给一条建议"
    txt = out[0]["text"]
    assert "搜索弹出的页面" in txt
    assert "**" not in txt, "面板会原样显示星号（实测过）"


def test_at_most_two_items():
    out = top_from_pacing({"degraded": {"app_risk_blocked": True,
                                       "device_env": True}})
    assert len(out) <= 2


def test_blocked_channel_shows_up():
    """有 0 成功率渠道时必须点名（用户才知道点哪家自检）。"""
    # 形状必须与 _blocked_channels 一致：channels 是 dict、按通路给 rate/attempts
    pacing = {"channels": {"app_ctrip": {
        "needs_login": True, "advice": "登录态失效",
        "paths": {"航班明细": {"rate": 0.0, "attempts": 74,
                             "why": "该日被要求登录"}}}}}
    out = top_from_pacing(pacing)
    assert any("被拦" in x["text"] or "0 成功率" in x["text"] for x in out), out


def test_webui_renders_advice_line():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "_adviceLine" in w, "面板没渲染建议行"
    i = w.index("_adviceLine")
    assert "advice_top" in w, "载荷里没挂 advice_top"
    assert "+_degradeLine+_adviceLine" in w, "建议行必须紧跟在「降级」之后"
