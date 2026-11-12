# -*- coding: utf-8 -*-
"""r1063 T206：自动退役死链路（0% + 样本够 + 原因是能力边界 → 停 24h 后复检）。

真机证据（今日）：
```
tuniu·PC   0%/49 次 · 每次约 98s  → 白烧 ≈ 80 分钟/天
why = 「距今天 >30 天的 PC 不查（风控），远日期走 H5/API」
```
落点在 `Pacing.gate_path()`（唯一闸门）：返回 `(False, 0, 原因)`，爬虫按既有
约定**只跳过这一条链路**、记 `paced`（不是 failed），不连坐整家渠道。

三条边界（都被用例钉住）：
1. 样本 < 10 或 rate > 0 → 不退役；
2. 原因**不命中**能力边界词（如"滑块拦截"）→ 不退役（那是熔断/换道的事）；
3. 24 小时后**自动放行一次**复检（可自愈，不是永久拉黑）；开关可整机关掉。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pacing as P  # noqa: E402


def _pac(cfg=None, why="不查"):
    pac = P.Pacing(cfg=cfg or {})
    try:
        pac.set_health("tuniu", 0.0, 49, dim="", path="PC")
    except TypeError:
        pac.set_health("tuniu", 0.0, 49)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = why
    return pac


def test_dead_boundary_path_is_retired():
    allow, wait, why = _pac().gate_path("tuniu", "", "PC")
    assert allow is False and wait == 0.0
    assert "自动退役" in why and "24h" in why, why


def test_other_paths_unaffected():
    pac = _pac()
    allow, _w, _why = pac.gate_path("tuniu", "", "H5/API")
    assert allow is True, "只该停那一条链路，不许连坐"


def test_small_sample_not_retired():
    pac = P.Pacing(cfg={})
    try:
        pac.set_health("tuniu", 0.0, 3, dim="", path="PC")
    except TypeError:
        pac.set_health("tuniu", 0.0, 3)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = "不查"
    assert pac.gate_path("tuniu", "", "PC")[0] is True


def test_risk_typed_zero_is_not_retired():
    """被风控拦出来的 0% 不归退役管（那是熔断/换道的事）。"""
    pac = P.Pacing(cfg={})
    try:
        pac.set_health("ctrip", 0.0, 30, dim="", path="PC")
    except TypeError:
        pac.set_health("ctrip", 0.0, 30)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = "滑块拦截，请点击重试"
    assert pac.gate_path("ctrip", "", "PC")[0] is True


def test_switch_off_allows():
    assert _pac({"path_auto_retire": False}).gate_path("tuniu", "", "PC")[0] is True


def test_retire_expires_and_probes_again():
    """到期必须放行一次复检，否则就是永久拉黑（用户再也发现不了修好了）。"""
    pac = _pac()
    key = pac._health_scope_key("tuniu", "", "PC")
    pac._auto_retire_next[key] = 0.0        # 模拟"已到期"
    allow, _w, _why = pac.gate_path("tuniu", "", "PC")
    assert allow is True, "到期应放行一次复检"
