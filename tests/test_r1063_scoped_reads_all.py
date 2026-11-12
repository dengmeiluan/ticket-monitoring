# -*- coding: utf-8 -*-
"""r1063 T57：声明了渠道级作用域，就必须真按作用域求值（全量门禁 + 已知欠账清单）。

这轮扫出 16 个这样的参数，其中 4 个（`ttl_tier.fast/slow`、`near_window.ratio/days`）
界面上能按渠道改、消费方却读全局——**配了完全不生效**。已经修掉。

剩下的不是忘了，而是**结构上不是按渠道取一个值**（map/list 形状，键/元素本身就是
渠道），或者**尚未接**（列在 KNOWN_GAPS 里，带原因）。这条门禁的作用是：

  * 新参数一旦声明了 channel/dimension/path 作用域却没有按作用域读点，立刻红
    ——不会再有第二个「TTL 白改」；
  * 已知欠账显式列出来，**减少一条就要改这里**，避免「忘了它还存在」。
"""
import io
import os

from core import strategy_contract as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = {"channel", "dimension", "path"}

# 结构上不是「按渠道取一个值」的参数（键/元素本身就是渠道），不算缺口
STRUCTURAL = {
    "cadence.per_plat": "map：键就是渠道（crawler.cadence: {qunar: 20}）",
    "proxy_route.map": "map：键就是渠道（plat → 代理）",
    "proxy_route.global": "单个全局出口；按渠道不同不是它的语义",
    "warmup.platforms": "list：元素就是渠道名（哪几家要预热）",
}

# 已知还没接作用域求值的参数：**减少一条就删一行**。
# r1063 T62：最后 5 条（health_penalty 的阈值/倍数/最小样本）也接上了 —— 现在是空的。
# 空表是有意义的状态：**所有声明了渠道级作用域的参数，都真的按作用域求值**。
KNOWN_GAPS = {}


def _scoped_reads():
    """返回 `{pid: (读点文件, …)}`：真按作用域求值的参数。"""
    ctx = sc._Ctx()
    out = {}
    for s in sc.STRATEGIES:
        if not (set(s.scope) & SCOPES):
            continue
        for p in s.params:
            via = ctx.read_by_switch(p.pid) or ctx.read_by_param(p.pid)
            if via:
                out[p.pid] = via
    return out


def test_every_channel_scoped_param_is_read_or_explicitly_accounted_for():
    got = _scoped_reads()
    missing = []
    for s in sc.STRATEGIES:
        if not (set(s.scope) & SCOPES):
            continue
        for p in s.params:
            if p.pid in got or p.pid in STRUCTURAL or p.pid in KNOWN_GAPS:
                continue
            missing.append("%s（%s）" % (p.pid, s.id))
    assert not missing, (
        "这些参数声明了渠道级作用域、却没有任何按作用域求值的读点"
        "（界面能按渠道改但不会生效）：\n  " + "\n  ".join(missing)
        + "\n修好一条，或加进 STRUCTURAL / KNOWN_GAPS 并写清原因。")


def test_ttl_and_near_window_are_scoped():
    """本轮修掉的四个必须留在 `_scoped(...)` 读法里。"""
    src = io.open(os.path.join(ROOT, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("ttl_tier.fast", "ttl_tier.slow", "near_window.ratio",
                "near_window.days"):
        assert 'self._scoped("%s"' % pid in src, pid


def test_known_gaps_are_still_real_gaps():
    """清单不许过期还挂着：已经修好的参数要从中删掉。"""
    got = _scoped_reads()
    stale = [pid for pid in KNOWN_GAPS if pid in got]
    assert not stale, ("这些参数已经按作用域求值了，从 KNOWN_GAPS 删掉：%s"
                       % stale)


def test_structural_list_only_contains_maps_or_lists():
    by_id = {p.pid: p for s in sc.STRATEGIES for p in s.params}
    for pid in STRUCTURAL:
        assert pid in by_id, pid
        assert by_id[pid].kind in ("map", "list", "str"), (
            "%s 是 %s，不像结构上不需要作用域" % (pid, by_id[pid].kind))
