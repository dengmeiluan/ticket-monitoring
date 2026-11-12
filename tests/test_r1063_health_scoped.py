# -*- coding: utf-8 -*-
"""r1063 T62：`health_penalty` 五个阈值按**作用域**求值（清掉最后 5 条欠账）。

缺口：`set_health()` / `_health_penalty()` 读 `self.cfg` 的全局值——界面上给某家
渠道或某条链路单独调「多低算差 / 罚几倍 / 多少样本才判」，一律不生效
（`health_penalty.enabled` 早就能到链路级，但这五个数值不能）。

清完之后 `KNOWN_GAPS` 是空表——**所有声明了渠道级作用域的参数都真按作用域求值**。
"""
import pytest

from core import strategy_params as sp
from core.pacing import Pacing

CFG = {"crawler": {"health_min_samples": 5, "health_ok_ratio": 0.7,
                   "health_slow_ratio": 0.4, "health_slow_factor": 1.5,
                   "health_slowest_factor": 3.0}}


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _p(overrides=None):
    cfg = {"crawler": dict(CFG["crawler"])}
    if overrides:
        cfg["crawler"]["strategy_overrides"] = overrides
    sp.set_config(cfg)
    return Pacing(dict(CFG))


def _pen(p, plat, rate=0.2, n=10):
    p.set_health(plat, rate, n)
    return (p.snapshot()["channels"].get(plat) or {}).get("health", {}).get(
        "penalty")


def test_slowest_factor_follows_the_channel_override():
    p = _p({"fliggy": {"health_penalty.slowest_factor": 6.0}})
    assert _pen(p, "fliggy") == 6.0
    assert _pen(p, "ctrip") == 3.0        # 别家不受影响


def test_ok_ratio_override_changes_the_band():
    """把 ok 线抬到 0.95 → 0.8 的成功率也算"差"，该降频。"""
    p = _p({"fliggy": {"health_penalty.ok_ratio": 0.95}})
    assert _pen(p, "fliggy", rate=0.8) == 1.5      # 落进 slow 档
    assert _pen(p, "ctrip", rate=0.8) == 1.0       # 全局 0.7 线 → 算好


def test_min_samples_override_gates_the_judgement():
    """样本门槛按渠道定：fliggy 要求 20 条，5 条样本时**不下判**。"""
    p = _p({"fliggy": {"health_penalty.min_samples": 20}})
    assert _pen(p, "fliggy", rate=0.1, n=5) == 1.0
    assert _pen(p, "ctrip", rate=0.1, n=5) == 3.0


def test_path_scope_reaches_the_thresholds():
    p = _p({"ctrip/intl/H5/API": {"health_penalty.slowest_factor": 8.0}})
    p.set_health("ctrip", 0.1, 10, dim="intl", path="H5/API")
    p.set_health("ctrip", 0.1, 10, dim="intl", path="PC")
    ch = p.snapshot()["channels"]["ctrip"]
    assert ch["health_paths"]["intl/H5/API"]["penalty"] == 8.0
    assert ch["health_paths"]["intl/PC"]["penalty"] == 3.0


def test_no_override_keeps_global_behaviour():
    p = _p()
    assert _pen(p, "fliggy", rate=0.6) == 1.5   # 0.4 ≤ 0.6 < 0.7 → slow
    assert _pen(p, "fliggy", rate=0.8) == 1.0   # ≥ 0.7 → 不降频


def test_read_points_are_present():
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("health_penalty.min_samples", "health_penalty.ok_ratio",
                "health_penalty.slow_ratio", "health_penalty.slow_factor",
                "health_penalty.slowest_factor"):
        assert 'self._scoped("%s"' % pid in src, pid
