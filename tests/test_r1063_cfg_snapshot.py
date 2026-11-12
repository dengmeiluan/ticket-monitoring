# -*- coding: utf-8 -*-
"""r1063 T37：策略配置快照（导出 / 对比 / 导入）。

策略有 30 条 × 98 个参数 + 四级作用域覆盖，全散在 `crawler.*` 点路径里。
"备份这套调好的配置""换机器照搬""改坏了回滚"——现在只能手工比对，最容易错。

快照只装「和默认不一样的东西」：全局层只收偏离默认的项（同一份默认配置导出
是空表，一眼看出改了什么）；粒度覆盖原样带上；**不含 users/凭证/停手**
（停手是运行期状态，"临时停 15 分钟"导出再导入会变成"永久停"）。
"""
import copy

import pytest

from core import cfg_snapshot as cs
from core.strategy_contract import STRATEGIES

P_NUM = ("rate_min_gap.value", "crawler.rate.min_gap_s")
P_BOOL = ("ttl_tier.enabled", "crawler.strategy_enabled.ttl_tier")


def _nest(dotted, value):
    segs = [x for x in dotted.split(".") if x]
    root = {}
    node = root
    for s in segs[:-1]:
        node[s] = {}
        node = node[s]
    node[segs[-1]] = value
    return root


def test_export_only_carries_deviations():
    default_cfg = {}
    assert cs.export(default_cfg)["values"] == {}, "默认配置导出来必须是空表"
    cfg = _nest(P_NUM[1], 9)
    snap = cs.export(cfg)
    assert snap["values"] == {P_NUM[0]: 9}, snap["values"]


def test_export_keeps_overrides_and_drops_users():
    cfg = {"crawler": {"strategy_overrides": {"ctrip": {P_NUM[0]: 7}}},
           "users": [{"name": "alice", "token": "secret"}]}
    snap = cs.export(cfg)
    assert snap["overrides"] == {"ctrip": {P_NUM[0]: 7}}
    assert "users" not in snap
    assert "secret" not in str(snap), "快照里不许出现凭证"


def test_no_halt_unless_asked():
    """默认不含停手：它是运行期状态，搬过去会把"临时停"变成"永久停"。"""
    assert "halt" not in cs.export({})


def test_round_trip_is_exact():
    cfg = _nest(P_NUM[1], 9)
    cfg["crawler"]["strategy_overrides"] = {"ctrip/intl": {P_NUM[0]: 11}}
    snap = cs.export(cfg)
    fresh = {}
    got = cs.apply(fresh, snap)
    assert got["applied"] >= 1 and not got["rejected"], got
    assert cs.export(fresh)["values"] == snap["values"]
    assert cs.export(fresh)["overrides"] == snap["overrides"]


def test_scope_rows_never_leak_into_the_global_layer():
    """作用域覆盖**不许**被当成全局值写进去（真实踩过的坑）。"""
    cfg = _nest(P_NUM[1], 9)
    cfg["crawler"]["strategy_overrides"] = {"ctrip": {P_NUM[0]: 11}}
    fresh = {}
    cs.apply(fresh, cs.export(cfg))
    from core.cfg_snapshot import _get_path
    assert _get_path(fresh, P_NUM[1]) == 9, "渠道覆盖值 11 漏进了全局层"
    # pid 里本身带点（`rate_min_gap.value`），这里直接索引，别走点路径解析
    ovr = (fresh.get("crawler") or {}).get("strategy_overrides") or {}
    assert (ovr.get("ctrip") or {}).get(P_NUM[0]) == 11, ovr


def test_apply_clears_when_snapshot_says_default():
    """快照里的值是默认值 → 应用时应当把它**清回默认**，而不是留一份冗余。"""
    cfg = _nest(P_NUM[1], 9)
    snap = {"version": 1, "values": {P_NUM[0]: 3}, "overrides": {}}   # 3 = 默认
    got = cs.apply(cfg, snap)
    assert got["cleared"] == 1, got
    from core.cfg_snapshot import _get_path
    assert _get_path(cfg, P_NUM[1]) is None


def test_unknown_pid_is_rejected_loudly():
    got = cs.apply({}, {"version": 1, "values": {"nope.pid": 1},
                        "overrides": {}})
    assert got["rejected"] == [{"pid": "nope.pid", "scope": ""}], got


def test_future_version_is_refused():
    with pytest.raises(ValueError) as e:
        cs.apply({}, {"version": 99, "values": {}, "overrides": {}})
    assert "版本" in str(e.value)


def test_diff_is_readable_and_idempotent():
    cfg = _nest(P_NUM[1], 9)
    snap = cs.export(cfg)
    assert cs.diff(cfg, snap) == [], "同一份配置对比自己必须没有差异"
    other = _nest(P_NUM[1], 12)
    rows = cs.diff(other, snap)
    assert len(rows) == 1
    r = rows[0]
    assert (r["pid"], r["before"], r["after"], r["action"]) == (
        P_NUM[0], 12, 9, "set"), r


def test_dry_run_changes_nothing():
    cfg = _nest(P_NUM[1], 9)
    snap = {"version": 1, "values": {P_NUM[0]: 12}, "overrides": {}}
    before = copy.deepcopy(cfg)
    got = cs.apply(cfg, snap, dry_run=True)
    assert got["applied"] == 1
    assert cfg == before, "dry_run 不许改 cfg"


def test_values_are_clamped_on_import():
    """越界的快照值必须被夹到声明区间（与界面同一条边界）。"""
    p = [pp for s in STRATEGIES for pp in s.params if pp.pid == P_NUM[0]][0]
    cfg = {}
    cs.apply(cfg, {"version": 1, "values": {P_NUM[0]: (p.hi or 0) + 9999},
                   "overrides": {}})
    from core.cfg_snapshot import _get_path
    got = _get_path(cfg, P_NUM[1])
    assert got is not None and float(got) <= float(p.hi), (got, p.hi)
