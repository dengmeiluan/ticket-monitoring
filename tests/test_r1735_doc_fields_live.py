# -*- coding: utf-8 -*-
"""r1735：`docs/HEALTH_STATES.md` 里写的**载荷字段**必须真的存在。

上一轮的门禁只查关键词（文档写了、代码里有），不查"字段真在响应里"——
而文档最容易错的就是字段名。这里对真实 HTTP 响应逐个核对。
"""
import json
import urllib.request

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(path):
    return json.loads(OP.open("http://127.0.0.1:8765" + path, timeout=25).read())


def _skip():
    try:
        _get("/api/state")
    except Exception:
        import pytest
        pytest.skip("服务未运行")


def test_pacing_channel_halt_field():
    _skip()
    d = _get("/api/pacing")
    ch = d.get("channels") or {}
    assert ch, "pacing.channels 为空"
    for p, row in ch.items():
        assert "halt" in (row or {}), "%s 缺 halt 字段" % p


def test_three_rates_halts_field():
    _skip()
    d = _get("/api/three-rates")
    assert "halts" in d, "three-rates 缺 halts"


def test_pulse_quiet_field():
    _skip()
    d = _get("/api/pulse")
    q = d.get("quiet") or {}
    for k in ("start", "end", "active", "left_s"):
        assert k in q, "pulse.quiet 缺 %s" % k


def test_health_diag_state_fields():
    _skip()
    d = _get("/api/health")
    diag = d.get("diag") or []
    assert diag, "health.diag 为空"
    for c in diag:
        for k in ("halt", "no_plan", "retired"):
            assert k in c, "%s 的诊断卡缺 %s" % (c.get("plat"), k)


def test_rates_by_path_no_ok_field():
    _skip()
    d = _get("/api/three-rates")
    rows = d.get("by_path") or []
    if not rows:
        return
    assert any("no_ok" in r for r in rows), "by_path 没有 no_ok 标记（零出数行无法识别）"
