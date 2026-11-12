# -*- coding: utf-8 -*-
"""r1063 T50：换道的**判据输入**可见（预算/冷却/上次结果）。

换道此前只有"成效"（预置几次 / 换了几次 / 回采几条）与"归因"（为什么 0 条）。
但用户最常问的是另一句：**为什么这次没换？** —— 那是预算用完了、冷却没到、
开关关了，还是 App 通路没就绪。这些是决策真正的输入。

做法：`core.failover.state()` 从**同一个账本**读出结构化的判据输入，
`pacing.snapshot().failover.plats` 带出去，界面挂到既有 `title` 上（不新增可见节点）。
"""
import io
import os
import tempfile

from core import failover as fo
from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_state_reports_budget_and_cooldown():
    d = tempfile.mkdtemp()
    st = fo.state("fliggy", {}, user_data_dir=d)
    assert st["app"] == "app_fliggy" and st["enabled"] is True
    assert st["cap"] > 0 and st["used"] == 0 and st["left"] == st["cap"]
    assert st["cooldown_left_s"] == 0


def test_state_follows_the_ledger():
    d = tempfile.mkdtemp()
    fo.note_switch("fliggy", "app_fliggy", ok=True, user_data_dir=d)
    st = fo.state("fliggy", {}, user_data_dir=d)
    assert st["used"] == 1 and st["left"] == st["cap"] - 1, st
    assert st["last_app"] == "app_fliggy" and st["last_ok"] is True
    # 冷却从上次换道算起
    assert st["cooldown_left_s"] > 0


def test_state_reflects_the_switch():
    """开关关了要能看出来（否则用户不知道为什么一直没换）。"""
    from core import strategy_params as sp
    sp.invalidate()
    try:
        sp.set_config({"crawler": {"strategy_enabled": {
            "app_fallback": False}}})
        assert fo.state("fliggy", {})["enabled"] is False
    finally:
        sp.invalidate()


def test_states_only_lists_channels_with_an_app_twin():
    d = tempfile.mkdtemp()
    got = fo.states(["fliggy", "ctrip", "app_fliggy", "tuniu"], {},
                    user_data_dir=d)
    assert "app_fliggy" not in got, "App 渠道本身不参与换道"
    # tuniu 没有 App 孪生（app_counterpart("tuniu") == ""）→ 不该出现
    assert set(got) == {"fliggy", "ctrip"}, got


def test_snapshot_carries_the_inputs():
    p = Pacing({"fliggy": {}, "ctrip": {}})
    fo_snap = p.snapshot()["failover"]
    assert "plats" in fo_snap and "fliggy" in fo_snap["plats"]
    row = fo_snap["plats"]["fliggy"]
    for k in ("cap", "used", "left", "cooldown_left_s", "enabled", "app"):
        assert k in row, (k, row)


def test_ui_tooltip_uses_the_inputs_without_new_nodes():
    seg = SRC[SRC.index("const _foPlatTitle="):][:1200]
    for token in ("v.cap", "v.used", "cooldown_left_s", "last_app", "last_ok"):
        assert token in seg, token
    # 只挂在既有 title 上：没有新增可见元素
    i = SRC.index("const _foPlatTitle=")
    after = SRC[i:i + 2000]
    assert "_foPlatTitle?(" in after or "esc(_foPlatTitle" in after
    assert "<div class=\"snote\"" in after or "class=\"snote\"" in after
