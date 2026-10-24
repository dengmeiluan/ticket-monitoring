# -*- coding: utf-8 -*-
"""登录完成后状态自动刷新（用户实测立案）：点「我已登录完成」后卡片
停留「会话可能失效」——两层根因：①清 login_suspect 的唯一路径=下轮采集
成功，而 qunar 退避冷却（≤300s）+调度周期让验证可能拖几十分钟；②前端
loadLogin 只在进入配置页/点按钮时拉一次，后端退绿页面也不自动跟上。

修法：①_finish_login 保存会话后清该渠道退避冷却（下轮调度 ≤5 分钟内
立即用新会话验证，成功即清标记退绿；login_suspect 本身不清——未验证
就退绿=假绿比琥珀更糟）；②前端登录分区可见时 30s 轮询+内容签名防抖
（状态无变化不重绘不打断点按；失败显式失效签名）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r291_login_refresh.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def test_finish_login_clears_backoff():
    """「我已登录完成」清该渠道退避冷却：用户主动登录=明确的重试意图，
    退避残留（最长 300s）会让下轮验证拖几十分钟——保存会话即清，
    下一轮调度立即用新会话验证。同时置 pending 验证窗（词面过渡档
    的数据源——置标记行为必须走真实 _finish_login 锁定）。"""
    import time
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old_cd = getattr(q, "_cooldown_until", None)
    old_pending = dict(getattr(webui._State, "login_pending", {}))
    webui._State.login_sessions["qunar"] = {"evt": threading.Event()}
    try:
        q._cooldown_until = 12345.0
        r = webui._finish_login("qunar")
        assert r["ok"] is True
        assert q._cooldown_until == 0, (
            "登录完成后退避冷却未清——下轮验证被退避残留拖慢")
        assert "qunar" not in webui._State.login_pending, (
            "finish 仅确认保存请求；pending 必须等 worker 真正落盘后置位")
    finally:
        webui._State.login_sessions.pop("qunar", None)
        if old_cd is not None:
            q._cooldown_until = old_cd
        webui._State.login_pending = old_pending


def test_finish_login_unknown_platform_no_side_effect():
    """无进行中登录窗口时返回 err 且不动冷却（副作用零外溢）。"""
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old_cd = getattr(q, "_cooldown_until", None)
    try:
        q._cooldown_until = 777.0
        r = webui._finish_login("qunar")
        assert r["ok"] is False
        assert q._cooldown_until == 777.0
    finally:
        if old_cd is not None:
            q._cooldown_until = old_cd


def test_login_polling_in_page():
    """前端自动刷新源码钉：登录分区周期轮询器（lgWatchStart 定义+挂接
    双段在场）+ 内容签名防抖判定行（状态无变化不重绘）。钉面锁唯一
    行为承载串——setInterval 在 PAGE 有其他消费点（主轮询），锁泛名
    是恒真式（十八§11 心理变异判据）。"""
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert "function lgWatchStart" in src, "轮询器定义缺席"
    assert "loadLogin(null,true);lgWatchStart();" in src, \
        "轮询挂接缺席（进分区即拉+启动）"
    assert "if(!force&&sig===LGSIG)" in src, \
        "内容签名防抖判定缺席（轮询重绘会打断点按）"


def test_finish_login_toast_wording():
    """toast 不得承诺未保证的分钟数：调度周期可配，只承诺「下一轮
    采集验证后自动更新（无需重启）」；检索页登录态另行即时同步。"""
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert "下一轮采集验证后自动更新状态（无需重启）" in src, "验证时机词面缺席"
    assert "下一轮采集（≤5 分钟）" not in src, "未保证的分钟数不得承诺"
    assert "SRX_LOGIN_T=0;SCAT=0;" in src, "finish 后未触发检索页登录态同步"


def test_finish_login_sets_pending_window():
    """「我已登录完成」置 pending 验证窗（10 分钟）：刚点完登录的卡片
    不得再说「会话可能失效，建议重登」——刚登完就被建议重登是词面
    自相矛盾（用户实测立案）；窗内 stale 仍在场（不退绿=未验证不假绿），
    前端以「验证中」过渡词面呈现。窗过后标记未清则回到「建议重登」
    （验证确实失败，重登建议重新成立）。"""
    import time
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old = getattr(q, "login_suspect", None)
    old_pending = dict(getattr(webui._State, "login_pending", {}))
    try:
        q.login_suspect = True
        webui._State.login_pending["qunar"] = time.time() - 1
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["stale"] is True, "窗内未验证不假绿"
        assert v["plats"]["qunar"]["pending"] is True, "pending 窗缺席"
        webui._State.login_pending["qunar"] = time.time() - 700
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["pending"] is False, "窗过期仍 pending"
    finally:
        if old is not None:
            q.login_suspect = old
        webui._State.login_pending = old_pending


def test_newer_login_rejection_ends_pending_window(monkeypatch):
    """点「登录完成」后只有**新的**明确拒绝才能结束待验证窗；旧拒绝
    证据不得把刚点的登录瞬间打回「建议重登」。"""
    import time
    from datetime import datetime
    import webui
    old_pending = dict(webui._State.login_pending)
    try:
        webui._State.login_pending["qunar"] = time.time() - 30
        monkeypatch.setattr(
            webui, "_health_state",
            lambda hours: {"evidence": {"qunar": {"domestic": {
                "auth_at": datetime.now().isoformat(timespec="seconds"),
                "detail_at": "", "auth_reason": "需登录"}}}})
        monkeypatch.setattr(webui, "_PROBE_AUTH", {})
        monkeypatch.setattr(webui._State, "login_sessions", {})
        v = webui._login_state_view()["plats"]["qunar"]
        assert v["pending"] is False, "新拒绝应结束待验证窗"
        assert v["status"] == "login_required"
    finally:
        webui._State.login_pending = old_pending


def test_login_pending_wording_in_page():
    """前端过渡词面钉：pending 窗内显示「验证中」不再说「建议重登」；
    登录窗口开着（active）时词面优先「登录中…」——登录中却说「建议
    重登」同为自相矛盾形态。"""
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert "下轮采集验证中" in src, "pending 过渡词面缺席"
    assert "会话需重新登录" in src, "常态失效词面被误删"
