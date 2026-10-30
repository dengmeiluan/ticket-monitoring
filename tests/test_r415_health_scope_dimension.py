# -*- coding: utf-8 -*-
"""r415：渠道健康要有「厂商 × 域」第二维，不能只有厂商一个数。

用户实报：同程健康度 12%，但国内全绿——国际「日历」通路的门拒被算进
厂商总分，看不出「哪一端坏了」。飞猪同理：厂商 85%，实际是国内 100%
+ 国际 83%。

拆开维度需要三件事同时成立，缺一条分域统计就是空的：
1. 采集日志带域标记（`抓取完成… · 国内/国际`）；
2. 解析能从日志行认出域（含旧格式：嵌套 `[plat][intl]`、航线三字码）；
3. 同一轮国内国际都跑过（mixed）不能整轮丢弃，否则单端样本消失。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.health import _evidence_scope, parse_health  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(fn):
    return open(os.path.join(ROOT, fn), encoding="utf-8").read()


def test_scope_from_explicit_tag():
    assert _evidence_scope("抓取完成，得到 23 条记录 · 国内") == "domestic"
    assert _evidence_scope("抓取完成，得到 1 条记录 · 国际") == "international"


def test_scope_from_nested_channel_tag():
    """`[tongcheng][intl]` 这类嵌套前缀此前认不出（只 match 行首）。"""
    assert _evidence_scope("[tongcheng][intl] 窗历命中 1/1 日") == "international"
    assert _evidence_scope("[qunar][intl] 1999 连续 2 次") == "international"


def test_scope_from_route_codes():
    """旧日志没有域标记时，用航线三字码兜底判域。"""
    assert _evidence_scope("开始抓取 SHA->HAK 日期=['2027-01-29']") == "domestic"
    assert _evidence_scope("开始抓取 SHA->LHR 日期=['2026-11-16']") == "international"


def test_scope_unknown_when_no_evidence():
    """没有任何域证据时保持 unknown，绝不默认成国内。"""
    assert _evidence_scope("抓取完成，得到 3 条记录") == "unknown"


def test_fetch_logs_carry_scope_tag():
    """采集端必须把域写进日志——日志是健康解析的唯一数据源。"""
    src = _src("crawlers/base.py")
    i = src.index("抓取完成，得到")
    block = src[max(0, i - 900):i + 200]
    assert "is_intl_route" in block, block[-400:]
    assert "· " in block


def test_mixed_round_not_dropped():
    """一轮里国内国际都跑过时，两侧都要有样本（曾整轮被丢弃）。"""
    src = _src("core/health.py")
    i = src.index("by_scope")
    block = src[i:i + 2200]
    assert "mixed" in block
    assert "domestic" in block and "international" in block


def test_parse_health_exposes_by_scope():
    """真实日志解析结果必须带 by_scope，且按厂商×域分组。"""
    logp = os.path.join(ROOT, "logs", "monitor.log")
    if not os.path.isfile(logp):
        return
    h = parse_health(open(logp, encoding="utf-8", errors="replace").read())
    assert "by_scope" in h
    bs = h["by_scope"]
    if not bs:
        return
    for plat, scopes in bs.items():
        assert set(scopes) <= {"domestic", "international"}, (plat, scopes)
        for sc, node in scopes.items():
            att = node["ok"] + node["part"] + node["fail"]
            assert 0.0 <= node["rate"] <= 1.0, (plat, sc, node)
            assert att >= 0


def test_ui_renders_scope_badge():
    """界面在两端都有样本时要显示「国内 X% · 国际 Y%」。"""
    src = _src("webui.py")
    assert "hscope" in src
    assert "by_scope" in src
    assert "'国内 '" in src or "国内 " in src


# ── r416：通路维度（PC/H5/日历/窗历）也必须露出 ──────────────────────

def test_health_payload_carries_paths():
    """健康载荷要带分通路成功率与退役标记，否则面板只有一个厂商数。"""
    src = _src("webui.py")
    i = src.index("def _health_decorate")
    # 取到函数结束，不用固定字符窗口：插一段别的维度就会把 path_stats
    # 挤出窗口，变成假红（r430 加会话维度时踩过）。
    j = src.index("\ndef ", i + 10)
    block = src[i:j]
    assert "path_stats" in block
    assert "retired_paths" in block or "retired" in block


def test_ui_renders_path_badge():
    """界面要把通路成功率与「退役」标出来。"""
    src = _src("webui.py")
    assert "hpath" in src
    assert "退役" in src
