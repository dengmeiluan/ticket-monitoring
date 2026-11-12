# -*- coding: utf-8 -*-
"""r626：预热关掉后，不能留下一个永远清不掉的 «需要预热» 标记。

`crawler.warmup.enabled: false` 可关，`main.py:_warm_once()` 开头就 return。
但 `ChannelBreaker.trip()` 的 soft 分支无条件 `st["needs_warmup"] = True`，
而这个标志**只有 `note_warmup_ok()`（预热成功）才会清**——预热被关掉就
永远不会执行，标记永久挂着。后果：
  - 面板/载荷一直显示「需要预热」，而这个动作被用户关了；
  - 用户哪天重开预热，一个几小时前的软拒会立刻触发一次「强制预热」
    （`_warm_once` 里 `forced = needs_warmup` 是绕过名单的直接触发条件）。

修法：`Pacing.observe()` 在「软拒 + 预热已关」时不经 trip()，只
`mark_cause()` 留归因；软拒的 kind 照旧返回（那不是熔断语义）。
负控：把这段守卫去掉即红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing  # noqa: E402


def _p(warmup=True):
    return Pacing({"crawler": {"warmup": {"enabled": warmup}}})


def test_warmup_off_does_not_leave_a_sticky_flag():
    pac = _p(False)
    assert pac.cfg["warmup_enabled"] is False
    kind, cd = pac.observe("qunar", ["soft_reject"], "444")
    assert kind == "soft" and cd == 0, (kind, cd)
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is False, (
        "预热已关闭，却仍要求「下一轮先预热」——这个标志永远没人清：%s" % ch)


def test_warmup_off_still_keeps_the_soft_reject_visible():
    """事实要留痕：面板还得能说「这轮是软拒」。"""
    pac = _p(False)
    pac.observe("qunar", ["soft_reject"], "444")
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("reason") == "soft", (
        "关掉预热后连「软拒」这个归因也丢了：%s" % ch)


def test_warmup_on_behaviour_is_unchanged():
    """开启时一字不变（回归护栏）：软拒必须要求预热。"""
    pac = _p(True)
    kind, cd = pac.observe("qunar", ["soft_reject"], "444")
    assert kind == "soft" and cd == 0, (kind, cd)
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is True, (
        "开启预热时软拒没有要求预热（会把会话问题当 IP 问题）：%s" % ch)


def test_reopening_warmup_does_not_fire_a_stale_force():
    """软拒发生在预热关闭期间，重开预热后不该被当成「现在就要强制预热」。"""
    pac = _p(False)
    pac.observe("qunar", ["soft_reject"], "444")
    # 用户重开预热（热更新配置）
    pac.refresh({"crawler": {"warmup": {"enabled": True}}})
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is False, (
        "几小时前的软拒在重开预热后被当成当前状态，会立刻触发一次强制预热：%s"
        % ch)


def test_warmup_off_does_not_affect_login_wall():
    """登录墙不是软拒，不受预热开关影响（要引导去重登）。"""
    pac = _p(False)
    kind, cd = pac.observe("ctrip", ["login"], "请登录")
    assert kind == "login" and cd > 0, (kind, cd)
