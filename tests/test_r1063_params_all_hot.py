# -*- coding: utf-8 -*-
"""r1063 T35：**全量**核对——目录里每一个参数都必须能热改并立刻生效。

这几十轮加了十来个参数和几个新策略族。单条测试只证明"我加的这个能用"，
证明不了"没有漏网"。这条按目录**逐个**跑：

  * 数值型：取区间中点写进配置 → `resolve()` 必须立刻给出该值，且 `source`
    不能还是 `default`（那说明它压根没读参数层，只是把默认值返回了）；
  * 布尔型：翻一个值 → 必须跟着翻；
  * 字符串/列表/映射型：只断言能读出声明默认值且不炸（这类没法安全往返）。

对 `strategy_enabled.<sid>` 这类"族的开关"也一起核对，因为它们同样要能热关。
"""
import pytest

from core import strategy_params as sp
from core.strategy_contract import STRATEGIES

ALL_PARAMS = [(s.id, p) for s in STRATEGIES for p in s.params]


def _nest(dotted, value):
    """`a.b.c` + 值 → 嵌套字典（`set_config` 吃的是配置树，不是点路径键）。"""
    segs = [x for x in str(dotted).split(".") if x]
    root = {}
    node = root
    for s in segs[:-1]:
        node[s] = {}
        node = node[s]
    node[segs[-1]] = value
    return root


def _numeric_mid(p):
    lo = p.lo if p.lo is not None else 0
    hi = p.hi if p.hi is not None else (p.default or 0) * 4 + 10
    mid = (float(lo) + float(hi)) / 2.0
    if p.kind == "int":
        mid = int(round(mid))
        # 别和默认值撞：撞了就证明不了"读到了配置"
        if mid == int(p.default or 0):
            mid = int(lo) if int(lo) != int(p.default or 0) else int(hi)
    else:
        if abs(mid - float(p.default or 0)) < 1e-9:
            mid = float(lo) if abs(float(lo) - float(p.default or 0)) > 1e-9 \
                else float(hi)
    return mid


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_catalog_is_substantial():
    assert len(ALL_PARAMS) >= 60, len(ALL_PARAMS)
    assert len(STRATEGIES) == 31, len(STRATEGIES)   # r1063 T47 起 31 条


@pytest.mark.parametrize("sid,p", ALL_PARAMS,
                         ids=["%s:%s" % (s, p.pid) for s, p in ALL_PARAMS])
def test_every_param_is_hot_and_honest(sid, p):
    """逐个参数：写进配置 → 立刻读到，且 source 不再是 default。"""
    got0 = sp.resolve(p.pid)
    assert got0.value == p.default or p.kind in ("str", "list", "map"), (
        "%s 的默认值读出 %r，声明是 %r" % (p.pid, got0.value, p.default))
    if p.kind in ("str", "list", "map"):
        return                      # 结构型不做往返（语义上没法安全替换）
    if p.kind == "bool":
        v = (not bool(p.default))
    else:
        v = _numeric_mid(p)
    sp.set_config(_nest(p.cfg, v))
    got = sp.resolve(p.pid)
    assert got.value == v, "%s 热改后读到 %r，期望 %r（配了不生效）" % (
        p.pid, got.value, v)
    assert str(got.source) != "default", (
        "%s 的 source 仍是 default：说明它没走参数层" % p.pid)


@pytest.mark.parametrize("sid,p", ALL_PARAMS,
                         ids=["%s:%s" % (s, p.pid) for s, p in ALL_PARAMS])
def test_every_param_clamps_within_declared_bounds(sid, p):
    """越界值必须被夹到声明区间（界面显示的边界＝落盘的边界）。"""
    if p.kind not in ("int", "float"):
        return
    lo = p.lo if p.lo is not None else -10 ** 9
    hi = p.hi if p.hi is not None else 10 ** 9
    sp.set_config(_nest(p.cfg, hi + 1000))
    got = sp.resolve(p.pid)
    assert float(got.value) <= float(hi) + 1e-9, (p.pid, got.value, hi)
    sp.invalidate()
    sp.set_config(_nest(p.cfg, lo - 1000))
    got2 = sp.resolve(p.pid)
    assert float(got2.value) >= float(lo) - 1e-9, (p.pid, got2.value, lo)


def test_overrides_work_for_every_scope_shape():
    """三档作用域都要能覆盖到（渠道 / 渠道·维度 / 渠道·维度·链路）。"""
    pid = "rate_min_gap.value"
    for scope in ("ctrip", "ctrip/intl", "ctrip/intl/H5/API"):
        sp.invalidate()
        sp.set_config({"crawler": {"strategy_overrides": {scope: {pid: 7}}}})
        plat, dim, path = (scope.split("/", 2) + ["", ""])[:3] \
            if scope.count("/") < 2 else (
                scope.split("/", 1)[0], scope.split("/")[1],
                scope.split("/", 2)[2])
        got = sp.resolve(pid, plat=plat, dim=dim, path=path)
        assert got.value == 7, (scope, got)
        assert str(got.source) in ("channel", "dimension", "path"), (scope, got)


def test_every_param_is_visible_in_the_panel_payload():
    """能被改 ≠ 能被看见：目录里每个参数都必须出现在面板载荷里。"""
    import webui

    pl = webui._strategy_payload()
    seen = {}
    for s in pl.get("strategies") or []:
        for row in s.get("params") or []:
            seen[row.get("pid")] = row
    missing = [p.pid for _sid, p in ALL_PARAMS if p.pid not in seen]
    assert not missing, "面板看不到这些参数：%s" % missing[:6]
    # 每个参数都要带「生效值 + 来源」，否则界面说不出"这值是谁定的"
    for _sid, p in ALL_PARAMS:
        row = seen[p.pid]
        assert "value" in row and "source" in row, (p.pid, row)


def test_every_strategy_appears_in_the_payload():
    import webui

    pl = webui._strategy_payload()
    ids = {s.get("id") for s in pl.get("strategies") or []}
    missing = [s.id for s in STRATEGIES if s.id not in ids]
    assert not missing, missing


CHANNEL_SCOPED = [(s.id, s.params[0]) for s in STRATEGIES
                  if "channel" in tuple(s.scope) and s.params]


@pytest.mark.parametrize("sid,p", CHANNEL_SCOPED,
                         ids=["%s" % sid for sid, _p in CHANNEL_SCOPED])
def test_channel_scope_actually_reaches_the_resolver(sid, p):
    """**声明了 channel 作用域**的策略，渠道覆盖必须真的覆盖到。

    这条防的是"声明写大、读点没接"——那样界面上能选渠道，实际却按全局走。
    """
    if p.kind not in ("int", "float", "bool"):
        pytest.skip("结构型参数不做往返")
    v = (not bool(p.default)) if p.kind == "bool" else _numeric_mid(p)
    sp.set_config({"crawler": {"strategy_overrides": {"ctrip": {p.pid: v}}}})
    got = sp.resolve(p.pid, plat="ctrip")
    assert got.value == v, (sid, p.pid, got)
    assert str(got.source) == "channel", (sid, p.pid, got)
