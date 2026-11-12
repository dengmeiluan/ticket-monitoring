# -*- coding: utf-8 -*-
"""r1063 T31：渠道内部限速档位可配置（原先是类属性字面量）。

普查（`crawlers/*.py`）找到的硬编码：`qunar._MIN_GAP_S = 8`、
`qunar.ROUND_WAIT_BUDGET_S = 300`、`tuniu.RATE_MAX = 3`、`tuniu.RATE_WINDOW = 600`。
这些都是"速度 vs 风控"最直接的旋钮，却写死在类属性里——用户想调快只能改代码。

语义写死一条：`channel_rate.enabled = false` 表示**忽略参数层定制、回到内置兜底**，
**不是**"关掉限速"——关掉限速是另一种危险动作，不该藏在"关掉定制"里。
"""
import io
import os

import pytest

from crawlers.qunar import _min_gap_s, _round_wait_budget_s
from core import strategy_params as sp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_qunar_min_gap_default_and_override():
    assert _min_gap_s() == 8.0                     # 契约默认
    sp.set_config({"crawler": {"qunar_min_gap_s": 5}})
    assert _min_gap_s() == 5.0
    sp.set_config({"crawler": {"strategy_overrides": {
        "qunar": {"channel_rate.qunar_min_gap_s": 12}}}})
    assert _min_gap_s("qunar") == 12.0             # 渠道覆盖
    assert _min_gap_s("ctrip") == 8.0              # 别的渠道不受影响


def test_qunar_min_gap_never_below_one_second():
    sp.set_config({"crawler": {"qunar_min_gap_s": 0}})
    assert _min_gap_s() >= 1.0


def test_qunar_wait_budget_override():
    assert _round_wait_budget_s() == 300
    sp.set_config({"crawler": {"qunar_round_wait_budget_s": 120}})
    assert _round_wait_budget_s() == 120


def test_switch_off_means_builtin_fallback_not_unlimited():
    """关掉开关 = 回内置兜底；**不是**变成 0（那等于不限速）。"""
    sp.set_config({"crawler": {"qunar_min_gap_s": 3,
                               "strategy_overrides": {
                                   "qunar": {"channel_rate.enabled": False}}}})
    assert _min_gap_s("qunar") == 8.0, "关掉定制后应回到内置兜底 8s"


def test_tuniu_rate_limits_follow_the_parameter_layer():
    from crawlers.tuniu import TuniuCrawler

    inst = object.__new__(TuniuCrawler)
    inst.name = "tuniu"
    mx, win = TuniuCrawler._rate_limits(inst)
    assert (mx, win) == (3, 600.0), (mx, win)
    sp.set_config({"crawler": {"tuniu_rate_max": 5,
                               "tuniu_rate_window_s": 300}})
    mx2, win2 = TuniuCrawler._rate_limits(inst)
    assert (mx2, win2) == (5, 300.0), (mx2, win2)


def test_no_hardcoded_knob_left_unreachable():
    """这些旋钮在策略目录里必须有登记，否则用户看不见也就调不了。"""
    src = io.open(os.path.join(ROOT, "core", "strategy_contract.py"),
                  encoding="utf-8").read()
    for pid in ("channel_rate.qunar_min_gap_s",
                "channel_rate.qunar_wait_budget_s",
                "channel_rate.tuniu_rate_max",
                "channel_rate.tuniu_window_s"):
        assert pid in src, pid
