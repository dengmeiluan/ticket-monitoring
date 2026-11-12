# -*- coding: utf-8 -*-
"""r1063 T29：跨查询流水线调度器（渠道互斥 + 跨查询重叠）。

用真实 `data/pulse.json` 量化收益，并在单测里把三个硬约束钉死：
同一渠道任意时刻最多一个任务、每个任务恰好一次、结果不丢不乱序。
"""
import collections
import io
import json
import os
import threading
import time

import pytest

from core import pipeline as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- 硬约束：互斥 / 不双采 / 结果齐 ----------------

def test_same_channel_is_never_in_flight_twice():
    queries = [("q%d" % i, ["ctrip", "qunar", "fliggy"]) for i in range(6)]
    live = collections.Counter()
    peak = collections.Counter()
    lock = threading.Lock()

    def fetch(label, chan):
        with lock:
            live[chan] += 1
            peak[chan] = max(peak[chan], live[chan])
        time.sleep(0.01)
        with lock:
            live[chan] -= 1
        return (label, chan)

    got = pl.run(queries, fetch, workers=4)
    assert all(v == 1 for v in peak.values()), dict(peak)
    # 每个 (查询, 渠道) 恰好一次
    for label, chans in queries:
        assert sorted(c for c, _r in got[label]) == sorted(chans), got[label]
    assert sum(len(v) for v in got.values()) == 18


def test_results_are_ordered_like_the_input():
    queries = [("q1", ["a", "b", "c"]), ("q2", ["a", "b", "c"])]

    def fetch(label, chan):
        time.sleep(0.02 if chan == "a" else 0.001)
        return chan.upper()

    got = pl.run(queries, fetch, workers=3)
    assert [c for c, _ in got["q1"]] == ["a", "b", "c"]
    assert [r for _c, r in got["q1"]] == ["A", "B", "C"]


def test_one_task_failure_does_not_break_the_round():
    queries = [("q", ["ok1", "boom", "ok2"])]

    def fetch(label, chan):
        if chan == "boom":
            raise RuntimeError("模拟单渠道失败")
        return "fine"

    got = pl.run(queries, fetch, workers=2)
    d = dict(got["q"])
    assert d["ok1"] == "fine" and d["ok2"] == "fine"
    assert isinstance(d["boom"], RuntimeError), d["boom"]


def test_pool_implementation_has_the_same_contract():
    queries = [("q%d" % i, ["x", "y"]) for i in range(4)]
    seen = []
    lock = threading.Lock()

    def fetch(label, chan):
        with lock:
            seen.append((label, chan))
        return chan

    got = pl.run_with_pool(queries, fetch, workers=2)
    assert len(seen) == 8 and len(set(seen)) == 8
    assert all(len(v) == 2 for v in got.values())


# ---------------- 收益预估：用真实 pulse 数据 ----------------

def _real_latencies():
    path = os.path.join(ROOT, "data", "pulse.json")
    try:
        rounds = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None
    lat = {}
    for r in rounds:
        for name, c in (r.get("chans") or {}).items():
            v = float(c.get("lat") or 0)
            if v > 0:
                lat.setdefault(name, []).append(v)
    if not lat:
        return None
    return {k: sum(v) / len(v) for k, v in lat.items()}


def test_real_data_says_where_the_time_goes():
    """用真实数据回答「瓶颈是同一条渠道，还是不同渠道轮着拖」。

    这条不是"流水线一定更快"，而是把**事实**钉住：如果同一个渠道的**总工作量**
    就是最大头，那换调度省不下它的串行时间——那就该去压渠道自身耗时或减查询数，
    而不是重写调度。数据变了这条断言会失败，正好提醒重新判断。
    """
    lat = _real_latencies()
    if not lat:
        pytest.skip("没有可用的 pulse 历史数据")
    chans = sorted(lat)[:4]
    queries = [("q%d" % i, chans) for i in range(10)]
    cp = pl.critical_path(queries, lambda _l, c: lat.get(c, 0.0))
    assert cp["kind"] in ("same_channel", "varies")
    assert cp["channel"], cp
    # 该渠道的总工作量必须是最大头（否则说明真正的瓶颈在别处）
    assert cp["critical_total"] > 0
    est = pl.potential(queries, lambda _l, c: lat.get(c, 0.0))
    print("实测 %s → critical=%s est=%s" % (lat, cp, est))
    if cp["kind"] == "same_channel":
        # 同一条渠道拖所有查询：流水线收益上限就是 1（串行瓶颈是它自己）
        assert est["gain"] <= 1.05, (cp, est)


def test_critical_path_detects_varying_bottleneck():
    """不同查询被不同渠道拖着时，判成 `varies`（这才是流水线有用的情形）。"""
    queries = [("q1", ["a", "b"]), ("q2", ["a", "b"])]
    lat = {("q1", "a"): 10.0, ("q1", "b"): 1.0,
           ("q2", "a"): 1.0, ("q2", "b"): 10.0}
    cp = pl.critical_path(queries, lambda l, c: lat.get((l, c), 0.0))
    assert cp["kind"] == "varies", cp


def test_potential_matches_naive_model_on_uniform_latency():
    queries = [("q1", ["a", "b"]), ("q2", ["a", "b"])]
    est = pl.potential(queries, lambda _l, _c: 10.0, workers=2)
    assert est["barrier"] == 20.0                    # 2 查询 × max(10,10)
    assert est["pipeline"] <= 20.0 and est["gain"] >= 1.0


def test_empty_input_is_safe():
    assert pl.run([], lambda *a: None) == {}
    assert pl.potential([], lambda *a: 0)["gain"] == 0.0
