# -*- coding: utf-8 -*-
"""r1063 T57：TTL / 邻近比价窗口按**作用域**求值（渠道覆盖真的生效）。

实测缺口：`resolve("ttl_tier.fast", plat="fliggy")` 早就能给出覆盖值 5，
而 `pacing.cfg["fast_ttl_min"]` 仍是全局 15 —— 界面上按渠道把 TTL 从 15 分钟
调到 5 分钟，**一点效果都没有**。同类还有 `ttl_tier.slow`、`near_window.ratio`、
`near_window.days`。

优先级与 T42 的 `_pval` 同一条：**参数层有意见才采用**，没配过就用全局值
（"参数层是默认来源，不是永远优先"）。
"""
import sys
import time

import pytest

from core import strategy_params as sp
from core.pacing import Pacing

BASE = {"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
        "crawler": {"health_ok_ratio": 0.85, "health_min_samples": 5}}


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _pacing():
    # `clock` 必须返回浮点（早先写成返回 list，age 算出来是垃圾）
    return Pacing(dict(BASE), clock=lambda: NOW[0])


NOW = [1_800_000_000.0]


def _seed_last(p, plat, minutes_ago, key=("a", "b", "2026-12-01")):
    p._last[(plat,) + key] = (NOW[0] - minutes_ago * 60, 1000.0)


def test_channel_override_changes_the_tier_for_that_channel_only():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"health_ok_ratio": 0.85,
                               "health_min_samples": 5,
                               "strategy_overrides": {
                                   "fliggy": {"ttl_tier.fast": 5}}}})
    p = _pacing()
    # 10 分钟前刚采过：全局 15 分钟还新鲜；覆盖成 5 分钟的那家该重采了
    for plat in ("fliggy", "ctrip"):
        _seed_last(p, plat, 10)
    tier_f, _ = p.plan_query("fliggy", ("a", "b", "2026-12-01"),
                             days_ahead=60)
    tier_c, _ = p.plan_query("ctrip", ("a", "b", "2026-12-01"),
                             days_ahead=60)
    assert tier_f == "fast", tier_f
    assert tier_c != "fast", tier_c


def test_no_override_keeps_the_global_ttl():
    """没配过覆盖时行为**不变**（参数层只是默认来源）。"""
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"health_ok_ratio": 0.85,
                               "health_min_samples": 5}})
    p = _pacing()
    _seed_last(p, "fliggy", 10)
    tier, _ = p.plan_query("fliggy", ("a", "b", "2026-12-01"), days_ahead=60)
    assert tier != "fast", tier


def test_scoped_reads_reach_path_scope_too():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"strategy_overrides": {
                       "ctrip/intl/H5/API": {"ttl_tier.fast": 6}}}})
    p = _pacing()
    # 声明下限是 5，所以覆盖值取 6（4 会被夹到 5）
    assert p._scoped("ttl_tier.fast", "ctrip", "intl", "H5/API", 15) == 6
    assert p._scoped("ttl_tier.fast", "ctrip", "intl", "PC", 15) == 15
    assert p._scoped("ttl_tier.fast", "ctrip", "", "", 15) == 15


def test_near_days_override_is_scoped():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"strategy_overrides": {
                       "qunar": {"near_window.days": 30}}}})
    p = _pacing()
    assert p._scoped("near_window.days", "qunar", "", "", 3) == 30
    assert p._scoped("near_window.days", "ctrip", "", "", 3) == 3


def test_scoped_helper_never_raises():
    """参数层炸了也不能把"排期"搞挂——回落全局值。"""
    p = _pacing()
    assert p._scoped("不存在的.pid", "fliggy", "", "", 7) == 7


def test_no_leftover_bare_ttl_reads():
    """门禁：TTL/近窗的三个值必须经 `_scoped`（否则渠道覆盖又会失效）。"""
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("ttl_tier.fast", "ttl_tier.slow", "near_window.ratio"):
        assert 'self._scoped("%s"' % pid in src, pid
