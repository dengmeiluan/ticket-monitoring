# -*- coding: utf-8 -*-
"""r805bp：健康卡也要认出「App 登录失效」，并指向内嵌画面。

现场（2026-11-01）：去哪儿 App 每轮账本都是 `app-login/login`，健康卡却写
「抓取失败（原因待核对）」，建议「打开原站核实 IP/风控/登录」——把「该重登」
混成了「原因未知」。`classify_round` 早就有 login 分支，但调用方只传了 cookie，
登录证据恒空，分支永远走不到。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_app_login_evidence_becomes_login_card():
    from core.health_diag import classify_round
    cards = classify_round(
        {"app_qunar": {"s": "timeout", "note": "未取到可用结果：set-city-dep"}},
        login={"app_qunar": {"needs_login": True}},
        all_plats=("app_qunar",))
    c = cards[0]
    assert c["kind"] == "login", c
    assert "内嵌画面" in c["action"], (
        "App 渠道的动作必须指向内嵌画面：%r" % c["action"])


def test_browser_login_action_still_points_to_window():
    from core.health_diag import classify_round
    cards = classify_round({"qunar": {"s": "timeout", "note": "拦截"}},
                           login={"qunar": {"needs_login": True}},
                           all_plats=("qunar",))
    assert cards[0]["kind"] == "login"
    assert "内嵌" not in cards[0]["action"], cards[0]["action"]


def test_health_decorate_feeds_login_evidence():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("def _health_decorate(")
    seg = src[i:i + 3000]
    assert "_app_login_expired" in seg, "健康诊断没接 App 登录证据"
    assert "login=_login_ev" in seg, "classify_round 仍没收到 login 证据"
