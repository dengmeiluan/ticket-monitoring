# -*- coding: utf-8 -*-
"""r625：熔断开关关掉后，不能仍宣称「已熔断」。

`crawler.breaker.enabled: false` 在配置页可关，`ChannelBreaker.allow()` 也确实
放行。但 `Pacing.observe()` 原样返回 kind，而调用方（main.py）把 kind 当
「已熔断」的信号：

  - 写一条 `action=auto_trip` 干预台账（干预次数被虚增）
  - 打「[节流] 命中 captcha，熔断 300s」告警
  - 触发「命中人机验证自动开窗」

于是用户关掉开关后，界面/日志/账本仍说「已熔断」——开关看起来生效了，实际没有。
而且 `state` 仍是 `ok`、`remain_s=0`，面板渠道行显示「正常」，这一轮明明
被验证码拦过的事实彻底消失了。

修法：
  1) `observe()` 在开关关闭时返回空 kind（不写台账/不告警/不开窗），
     但把归因记到 `_cause[plat]`；
  2) 快照把它挂成 `blocked_but_open`，面板显示「被拦 · 未熔断」。
负控：把 `observe()` 的开关分支去掉即红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing  # noqa: E402

BLOCKED = ["blocked"]
NOTE = "验证码"


def _p(enabled):
    return Pacing({"crawler": {"breaker": {"enabled": enabled}}})


def test_disabled_breaker_does_not_report_trip():
    pac = _p(False)
    assert pac.cfg["breaker_enabled"] is False
    kind, cd = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "", (
        "熔断已关闭，observe 仍返回 %r —— 调用方会写 auto_trip 台账、"
        "打「命中…熔断」告警、自动弹窗" % kind)
    assert cd == 0, "熔断已关闭，不应有冷却时长：%r" % cd
    assert pac._breaker.allow("ctrip") == (True, 0), "关闭后必须放行"
    # 也不该出现在本轮 trips 里（面板「本轮节流」按它算）
    trips = pac.snapshot().get("last_round", {}).get("trips") or []
    assert not [t for t in trips if t.get("plat") == "ctrip"], (
        "关闭后仍记了本轮熔断：%s" % trips)


def test_disabled_breaker_still_keeps_the_cause_visible():
    """开关可以关，事实不能消失：被什么拦的要留在载荷里。"""
    pac = _p(False)
    pac.observe("ctrip", BLOCKED, NOTE)
    ch = (pac.snapshot().get("channels") or {}).get("ctrip") or {}
    assert ch.get("blocked_but_open") == "captcha", (
        "关掉熔断后归因丢了（界面会显示一片正常）：%s" % ch)
    assert ch.get("remain_s") in (0, None), "关闭时不应有冷却：%s" % ch


def test_enabled_breaker_behaviour_is_unchanged():
    """开关开启时行为一字不变（回归护栏）。"""
    pac = _p(True)
    kind, cd = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "captcha" and cd > 0, (kind, cd)
    assert pac._breaker.allow("ctrip")[0] is False, "开启时必须熔断"
    ch = (pac.snapshot().get("channels") or {}).get("ctrip") or {}
    assert not ch.get("blocked_but_open"), (
        "开启时不该走 blocked_but_open 分支：%s" % ch)


def test_soft_and_login_still_handled_when_breaker_off():
    """软拒/登录墙不是「熔断」语义——关掉熔断不应连它们一起吞掉。"""
    pac1 = _p(False)
    k1, _ = pac1.observe("qunar", ["soft_reject"], NOTE)
    assert k1 == "soft", (
        "软拒要给「下一轮先预热」的信号，不该因熔断关闭而消失：%r" % k1)
    # 登录墙用独立实例：软拒会在同一渠道留下 needs_warmup，
    # 混在一起测会把「登录」的分支判定搅浑（测试隔离，非产品行为）。
    pac2 = _p(False)
    k2, cd2 = pac2.observe("qunar", ["login"], NOTE)
    assert k2 == "login" and cd2 > 0, (k2, cd2)


def test_string_false_from_yaml_is_respected():
    """手写 yaml 的 'false' 字符串也要真的关掉（同 r519 的教训）。"""
    pac = Pacing({"crawler": {"breaker": {"enabled": "false"}}})
    assert pac.cfg["breaker_enabled"] is False
    kind, _ = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "", "'false' 字符串没有被当成关闭：observe=%r" % kind


def test_panel_renders_the_not_tripped_state():
    """界面必须有这一档文案，否则关掉开关后只能看到「正常」。"""
    import io
    w = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8", newline="").read()
    i = w.index("blocked_but_open")
    seg = w[max(0, i - 400):i + 500]
    assert "被拦 · 未熔断" in seg, "面板没有「被拦 · 未熔断」这一档：%s" % seg[:260]
    assert "熔断已关闭" in seg, "没有说清为什么没熔断：%s" % seg[:260]
