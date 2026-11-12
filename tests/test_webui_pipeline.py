# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_phase_names_and_park.py
- tests/test_r1063_phase_timer.py
- tests/test_r1063_pipeline.py
- tests/test_r1063_route_timeout.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import collections
import io
import json
import main
import os
import pytest
import threading
import time

from core import pipeline as pl, strategy_params as sp
from core.pacing import Pacing
from core.phase_timer import PhaseTimer
from core.yield_stats import YieldLedger


# ---- merged from tests/test_r1063_phase_names_and_park.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
              encoding="utf-8").read()


def test_manual_phases_are_namespaced():
    """手动打点必须带 `耗时·` 前缀（与路径名隔离，否则读数自相矛盾）。"""
    for name in ("耗时·运行时", "耗时·前置", "耗时·日历", "耗时·明细",
                 "耗时·收尾"):
        assert 'self.timed("%s")' % name in SRC, name
    # 不许再出现裸的 `self.timed("日历")`（会与路径账同名）
    assert 'self.timed("日历")' not in SRC


def test_calendar_subphases_are_separate():
    assert 'self.timed("耗时·日历·打开")' in SRC
    assert 'self.timed("耗时·日历·等价")' in SRC


def test_park_has_single_back_fast_path():
    """收尾快路径：一次 BACK 就回首页，失败再走既有梯子。"""
    i = SRC.index("def _park_at_home")
    seg = SRC[i:i + 2600]
    assert "单次 BACK 快路径" in seg
    assert 'dev.keyevent("KEYCODE_BACK")' in seg
    assert "一次 BACK 已回首页" in seg
    # 既有梯子必须仍在（快路径失败要能兜住）
    assert 'find(nodes(xml), "机票")' in seg


def test_back_fast_path_returns_before_tab_loop():
    """顺序必须是「先 BACK 判首页」→ 再 Tab 轮询，不能反。"""
    i = SRC.index("def _park_at_home")
    seg = SRC[i:i + 2600]
    assert seg.index("单次 BACK 快路径") < seg.index('find(nodes(xml), "机票")')


# ---- merged from tests/test_r1063_phase_timer.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_summary_aggregates_same_name():
    t = PhaseTimer()
    t.mark("导航", 10)
    t.mark("日历", 4)
    t.mark("导航", 6)
    rows = t.summary()
    assert rows[0] == {"name": "导航", "s": 16.0, "n": 2}, rows
    assert rows[1]["name"] == "日历"


def test_context_manager_times_and_never_raises():
    t = PhaseTimer()
    with t("等待"):
        time.sleep(0.02)
    assert t.summary()[0]["name"] == "等待"
    assert t.summary()[0]["s"] >= 0

    class Boom:
        pass

    # 未知阶段名 / 没打开就 stop：一律不抛
    assert t.stop("从没开始") == 0.0
    t.mark("坏值", "abc")


def test_text_readout_is_one_line():
    t = PhaseTimer()
    t.mark("日历", 16)
    t.mark("前置", 8)
    txt = t.text()
    assert "日历" in txt and "前置" in txt and "共" in txt


def test_ledger_stores_phase_totals(tmp_path=None):
    import tempfile

    p = os.path.join(tempfile.mkdtemp(), "y.json")
    led = YieldLedger(p)
    led.note_phases("app_zhixing", [{"name": "日历", "s": 12.0, "n": 1},
                                    {"name": "前置", "s": 8.0, "n": 1}])
    led.note_phases("app_zhixing", [{"name": "日历", "s": 4.0, "n": 1}])
    import json
    rec = json.load(open(p, encoding="utf-8"))["app_zhixing"]["phases"]
    assert rec["日历"]["n"] == 2 and rec["日历"]["total_s"] == 16.0, rec
    assert rec["前置"]["total_s"] == 8.0


def test_crawlers_have_timed_and_auto_marks():
    app = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    brw = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    for src in (app, brw):
        assert "def timed(self" in src
        assert "def phases_timer(self" in src
        assert "_phase_prev" in src, "自动打点必须留在 path_note 里"
        assert "note_phases" in src, "收尾必须写账"


def test_zhixing_has_explicit_marks():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    # r1063 T78 起手动打点统一带 `耗时·` 前缀（与路径名隔离）
    for name in ("耗时·前置", "耗时·导航", "耗时·日历"):
        assert 'with self.timed("%s")' % name in src, name


# ---- merged from tests/test_r1063_pipeline.py ----

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


# ---- merged from tests/test_r1063_route_timeout.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_route_timeout_comes_from_the_parameter_layer():
    sp.set_config({"crawler": {"route_timeout_s": 120}})
    assert main._route_timeout(["ctrip"]) == 120.0


def test_route_timeout_takes_the_max_over_channels():
    """一轮共用一个等待窗：取最大值，否则慢家会被配置判成"超时"。"""
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng": {"budget.route_s": 600}}}})
    assert main._route_timeout(["ctrip", "tongcheng"]) == 600.0
    assert main._route_timeout(["ctrip"]) == 300.0        # 契约默认


def test_route_timeout_is_clamped_by_the_contract():
    sp.set_config({"crawler": {"route_timeout_s": 99999}})
    assert main._route_timeout(["ctrip"]) <= 900.0


def test_route_timeout_falls_back_when_nothing_resolves(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no provider")
    monkeypatch.setattr(sp, "resolve", _boom)
    assert main._route_timeout(["ctrip"]) == float(main._ROUTE_FUT_TIMEOUT)


def test_literal_900_is_gone():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "15 * 60" not in src, "900 秒字面量还在（一次挂死白等 15 分钟）"
    assert "timeout_s=_route_timeout(" in src, "两处栅栏没走参数层"


def test_timeout_count_is_observable():
    p = Pacing({})
    p.note_query_timing(wall=10.0, work=3.0, tasks=4, paced=0, timed_out=2)
    t = p.snapshot()["timing"]
    assert t["timed_out"] == 2, t
    assert t["idle_ratio"] == 0.7


def test_panel_mentions_timeouts():
    src = webui_full_src()
    seg = src[src.index("const _timeline=(()=>{"):][:1200]
    assert "超时" in seg and "t.timed_out" in seg
