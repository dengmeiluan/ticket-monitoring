# -*- coding: utf-8 -*-
"""r1063 T28：路由级栅栏超时从「写死 15 分钟」变成可配置参数。

**证据（真实 `data/pulse.json`，48 轮）**：墙钟中位 253s、最大 1017.9s；
单渠道耗时中位 25–50s、最大 165s。900 秒的栅栏超时意味着一次挂死就白等
15 分钟——而它还是个字面量（策略目录 `budget` 里自己写着"字面量"）。

墙钟/最慢渠道 的中位是 **5.44**：说明慢的主因不是"单查询内等某一家"，
而是**每条查询各排一次队**（查询之间串行）+ 偶发挂死把整轮拖到 15 分钟。
这轮先解决后者（确定性收益），前者（跨查询流水线）留到下一步。
"""
import io
import os

import pytest

import main
from core import strategy_params as sp
from core.pacing import Pacing

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
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    seg = src[src.index("const _timeline=(()=>{"):][:1200]
    assert "超时" in seg and "t.timed_out" in seg
