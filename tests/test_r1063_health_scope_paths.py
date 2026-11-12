# -*- coding: utf-8 -*-
"""r1063 T16：通路（H5/API、PC、API…）作为独立作用域，且读数进策略面板行。

目标原话：「…一切可统一状态，一切可精准控制，例如 H5/API、PC、API 这类
通路也算作独立维度，进策略面板行」。

三件事：
  1. `pacing` 内部收成**单一状态** `_health_all[(plat, dim, path)]`
     （渠道 = (plat,"","")），`_health` 退化成一个只读兼容视图；
  2. 取倍数按「链路 → 维度 → 渠道」逐级回落，`gate_path` 只放大**该链路**
     的限速倍数（同维度其它链路不受影响）；
  3. `/api/strategy` 出 `health`（渠道/维度/链路三档），策略面板行按目录里的
     `scope` 字段（不是写死 id）渲染「当前降频」那一行。
"""
import io
import os
import tempfile

import pytest

from core.storage import PriceStorage


def _pacing(clock=None):
    from core.pacing import Pacing
    return Pacing({"crawler": {"rate": {"min_gap_s": 10}},
                   "schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120,
                                "near_ratio": 0.15}},
                  clock=(clock or (lambda: 1_000_000.0)))


@pytest.fixture(autouse=True)
def _clean_params():
    from core import strategy_params as sp
    sp.invalidate()
    yield
    sp.invalidate()


# ---------------- 单一状态 ----------------

def test_health_state_is_one_store_with_a_compat_view():
    """渠道级读数仍能从 `_health[plat]` 读到（老契约），但内部只有一份状态。"""
    pac = _pacing()
    pac.set_health("ctrip", 0.5, 10)
    pac.set_health("ctrip", 0.1, 10, dim="calendar")
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    assert pac._health["ctrip"]["rate"] == 0.5          # 兼容视图：只含渠道级
    keys = sorted(k for k in pac._health_all)
    assert ("ctrip", "", "") in keys
    assert ("ctrip", "calendar", "") in keys
    assert ("ctrip", "detail", "H5/API") in keys
    # 兼容视图是**投影**，不是第二份状态：往它写不会改真状态
    pac._health["ctrip"]["rate"] = 0.99
    assert pac._health["ctrip"]["rate"] == 0.5


# ---------------- 逐级回落 ----------------

def test_precedence_path_over_dimension_over_channel():
    pac = _pacing()
    pac.set_health("ctrip", 0.05, 10)                        # 渠道 ×3
    pac.set_health("ctrip", 0.5, 10, dim="calendar")         # 维度 ×1.5
    pac.set_health("ctrip", 0.02, 10, dim="calendar",
                   path="日历")                              # 链路 ×3
    assert pac._health_penalty("ctrip", "calendar", "日历") == 3.0
    assert pac._health_penalty("ctrip", "calendar", "窗历") == 1.5   # 回落维度
    assert pac._health_penalty("ctrip", "detail", "PC") == 3.0       # 回落渠道


def test_thin_path_sample_falls_back_to_dimension_then_channel():
    pac = _pacing()
    pac.set_health("ctrip", 0.05, 10)                        # 渠道 ×3
    pac.set_health("ctrip", 0.02, 2, dim="detail", path="H5/API")   # 样本不足
    assert pac._health_penalty("ctrip", "detail", "H5/API") == 3.0


# ---------------- 精准控制：只压那一条 ----------------

def test_gate_path_scales_only_the_bad_links_wait():
    from core import strategy_params as sp
    # 限速基数走参数层（`rate_min_gap` 的读点就是 `sp.resolve`），
    # 所以这里显式装一份配置，别依赖出厂默认 3s。
    sp.set_config({"crawler": {"rate": {"min_gap_s": 10}}})
    pac = _pacing()
    pac.record("ctrip", path="H5/API")      # 让这条链路刚发过、需要等
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    _ok, bad, why = pac.gate_path("ctrip", "detail", "H5/API")
    _ok2, ok_wait, why2 = pac.gate_path("ctrip", "detail", "PC")
    assert bad >= 30.0 - 1e-6, (bad, why)          # 10s × 3
    assert "成功率保护" in why
    assert ok_wait <= 10.0 + 1e-6, (ok_wait, why2)  # 只等渠道级 10s，不被乘
    assert "成功率保护" not in why2


# ---------------- 统一状态：面板读数来自同一份 snapshot ----------------

def test_snapshot_carries_channel_dimension_and_path_scopes():
    pac = _pacing()
    pac.set_health("ctrip", 0.5, 10)
    pac.set_health("ctrip", 0.1, 10, dim="calendar")
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    ch = pac.snapshot()["channels"]["ctrip"]
    assert (ch.get("health") or {}).get("rate") == 0.5
    assert "calendar" in (ch.get("health_dims") or {})
    assert "detail/H5/API" in (ch.get("health_paths") or {})


def test_strategy_payload_exposes_scoped_health_and_row_renders_it():
    """面板行必须能看到「哪一条被压到几倍」，且判据是目录的 scope 字段。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    # 载荷：从 snapshot 取，不在 webui 里另算
    assert 'out["health"] = health' in src
    assert '_ch.get("health_paths")' in src
    # 渲染：按 scope 判定（不写死策略 id）
    fn = src[src.index("function stratScopeHTML(s){"):]
    fn = fn[:fn.index("function stratRowHTML(s){")]
    assert "indexOf('path')" in fn and "indexOf('dimension')" in fn
    assert "health_penalty" not in fn, "写死策略 id 就是第二份声明"
    assert "stratScopeHTML(s)" in src, "行模板没挂上逐作用域读数"
