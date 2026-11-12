# -*- coding: utf-8 -*-
"""r1063 T15：成功率保护按维度独立——日历烂不该把整家渠道一起降频。

背景：`health_penalty`（自动降频）此前只有渠道级口径——`path_stats` 只出
`platform × 入口 × 域`，`set_health` 只落一个渠道值，`plan_query` 拿它拉长
整家渠道的 TTL。目标要求「每个维度可独立调整」，所以：
  1. `path_stats` 额外产出 `dims`（按 `dim_of_path()` 归维度）；
  2. `set_health(..., dim=)` / `plan_query(..., dim=)` 按维度取惩罚；
  3. 维度样本不足时回落渠道级（噪声不该决定速度）。
"""
import os
import tempfile

import pytest

from core.storage import PriceStorage, dim_of_path


@pytest.fixture()
def ps():
    d = tempfile.mkdtemp()
    return PriceStorage(os.path.join(d, "t.db"))


def _seed(ps, n=6):
    """同一渠道：日历通路全失败、PC（明细）全成功。"""
    for i in range(n):
        ps.save_fetch_path("ctrip", "SHA", "BJS", "2027-01-29", "日历",
                           "error", attempt_id="cal-%d" % i)
        ps.save_fetch_path("ctrip", "SHA", "BJS", "2027-01-30", "PC",
                           "ok", rows=3, attempt_id="det-%d" % i)


def test_dimension_mapping_is_single_source():
    """维度归属只有一份映射：通路名 → 维度。"""
    assert dim_of_path("日历") == "calendar"
    assert dim_of_path("窗历") == "calendar"
    assert dim_of_path("app-calendar") == "calendar"
    assert dim_of_path("往返") == "round_trip"
    assert dim_of_path("TRIP") == "round_trip"
    assert dim_of_path("多程") == "multi_city"
    assert dim_of_path("low-fare") == "low_fare"
    # 其余一律 detail（含 PC/H5/API/App 及各细段）
    for p in ("PC", "H5", "H5/API", "API", "QUERY", "app-list", "app-date"):
        assert dim_of_path(p) == "detail", p
    assert dim_of_path("") == "detail"


def test_path_stats_exposes_dimension_nodes(ps):
    _seed(ps)
    node = ps.path_stats(24)["ctrip"]
    dims = node.get("dims") or {}
    assert set(dims) >= {"calendar", "detail"}, sorted(dims)
    assert dims["calendar"]["attempts"] == 6
    assert dims["calendar"]["ok"] == 0
    assert dims["calendar"]["rate"] == 0.0
    assert dims["detail"]["attempts"] == 6
    assert dims["detail"]["ok"] == 6
    assert dims["detail"]["rate"] == 1.0
    # 渠道级仍是两维之和（今天的口径不变）
    assert node["attempts"] == 12
    assert node["ok"] == 6


def test_dimension_query_rate_counts_once_per_dimension(ps):
    """查询口径在维度内同样成立：一次查询一条路径出数即算该维度成功。"""
    _seed(ps)
    node = ps.path_stats(24)["ctrip"]
    cal = node["dims"]["calendar"]
    det = node["dims"]["detail"]
    assert (cal["query_attempts"], cal["query_ok"]) == (6, 0)
    assert (det["query_attempts"], det["query_ok"]) == (6, 6)


def _pacing_with_baseline(minutes_ago=30):
    """造一个带基线的 Pacing：假时钟 + 30 分钟前采过一条贴近阈值的价。

    `plan_query` 的档位由「距上次采集多久」决定（TTL 内 skip / 过了就 fast），
    而成功率保护的作用是**把 TTL 拉长**——所以要看它生效，必须有一条基线，
    否则永远返回「无历史基线 → fast」，测不出惩罚。
    """
    from core.pacing import Pacing

    now = 1_000_000.0
    pac = Pacing({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120,
                               "near_ratio": 0.15}}, clock=lambda: now)
    pac.seed_fetch("ctrip", ("SHA", "BJS", "2027-01-29"), 1000.0,
                   now - minutes_ago * 60)
    return pac, now


def test_dimension_penalty_does_not_leak_to_other_dimensions():
    """日历烂（×3）→ 日历查询被 skip；明细好（×1）→ 明细查询照常 fast。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.05, 10, dim="calendar")
        pac.set_health("ctrip", 0.95, 10, dim="detail")
        cal, why_cal = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                      threshold=1000.0, dim="calendar")
        det, why_det = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                      threshold=1000.0, dim="detail")
        assert cal == "skip", (cal, why_cal)      # 15×3=45 分钟 TTL，30 分钟内
        assert det == "fast", (det, why_det)      # 15 分钟 TTL 已过
    finally:
        sp.invalidate()


def test_thin_dimension_falls_back_to_channel_level():
    """维度样本不足（2 条 < 下限 5）时回落渠道级：不让噪声决定速度。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.05, 10)                 # 渠道级烂 → ×3
        pac.set_health("ctrip", 0.95, 2, dim="detail")    # 维度只有 2 条样本
        det, why = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                  threshold=1000.0, dim="detail")
        assert det == "skip", ("维度样本不足却没回落渠道级", det, why)
    finally:
        sp.invalidate()


def test_channel_level_key_still_present_in_snapshot():
    """快照仍按渠道暴露 health（界面/门禁读这个形状），维度读数另挂 health_dims。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({})
    try:
        pac = Pacing({})
        pac.set_health("ctrip", 0.5, 10)
        pac.set_health("ctrip", 0.1, 10, dim="calendar")
        snap = pac.snapshot()
        ch = snap["channels"].get("ctrip") or {}
        assert (ch.get("health") or {}).get("rate") == 0.5
        assert "calendar" in (ch.get("health_dims") or {})
    finally:
        sp.invalidate()


def test_the_pipeline_actually_wires_dimension_health():
    """接线钉子：`main.py` 必须真的把维度级读数喂进去、并带 dim 查 TTL。

    只钉「调用形态在」，不重复它的判据——判据在上面几条行为用例里。
    少了这两处，`path_stats` 出了 `dims` 也没人用，等于维度级降频是空转。
    """
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert 'for _d, _dn in (_node.get("dims") or {}).items():' in src, \
        "main.py 没有遍历 path_stats 的 dims（维度级读数没人用）"
    assert "dim=_d" in src, "main.py 没把维度传给 set_health"
    assert "days_ahead=_days, dim=dim" in src, \
        "main.py 没把维度传给 plan_query（TTL 仍按渠道级降频）"
    # r1063 T16：链路级
    assert 'for _pth, _pn in (_node.get("paths") or {}).items():' in src, \
        "main.py 没有遍历 path_stats 的 paths（链路级读数没人用）"
    assert "path=_pth" in src, "main.py 没把链路传给 set_health"


# ---------------- 链路级（r1063 T16）：H5/API、PC、API 各自独立 ----------------

def test_path_level_penalty_does_not_leak_to_sibling_paths():
    """同一维度下的两条链路互不连坐：H5/API 烂，PC 照常。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        pac.set_health("ctrip", 0.98, 10, dim="detail", path="PC")
        assert pac._health_penalty("ctrip", "detail", "H5/API") == 3.0
        assert pac._health_penalty("ctrip", "detail", "PC") == 1.0
    finally:
        sp.invalidate()


def test_path_penalty_scales_only_that_paths_gate_wait():
    """`gate_path` 的限速只按该链路自己的成功率放大。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({"crawler": {"rate": {"min_gap_s": 10}}})
    try:
        now = 1_000_000.0
        pac = Pacing({"crawler": {"rate": {"min_gap_s": 10}},
                      "schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120}},
                     clock=lambda: now)
        # 只让 H5/API 这一条链路"刚发过"，其余链路没发过
        pac.record("ctrip", path="H5/API")
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        _ok, wait_bad, why = pac.gate_path("ctrip", "detail", "H5/API")
        _ok2, wait_ok, why_ok = pac.gate_path("ctrip", "detail", "PC")
        # 同一渠道的令牌桶是共享的（`record(path=…)` 同时记渠道桶，那是
        # per_minute 的渠道上限），所以 PC 也会等渠道级的 10s——这**不是**
        # 连坐；连坐会表现为 PC 也被乘上 3 倍。
        assert wait_bad >= 10 * 3.0 - 1e-6, ("链路级降频没进限速", wait_bad, why)
        assert "成功率保护" in why, why
        assert wait_ok <= 10.0 + 1e-6, ("同维度的另一条链路被乘了倍数", wait_ok, why_ok)
        assert "成功率保护" not in why_ok, why_ok
    finally:
        sp.invalidate()


def test_snapshot_exposes_path_level_readings():
    """快照给策略面板逐链路读数：键是 `维度/通路`。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({})
    try:
        pac = Pacing({})
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        pac.set_health("ctrip", 0.9, 10, dim="calendar", path="日历")
        ch = (pac.snapshot()["channels"] or {}).get("ctrip") or {}
        hp = ch.get("health_paths") or {}
        assert "detail/H5/API" in hp, sorted(hp)
        assert hp["detail/H5/API"]["penalty"] == 3.0
        assert hp["calendar/日历"]["penalty"] == 1.0
    finally:
        sp.invalidate()
