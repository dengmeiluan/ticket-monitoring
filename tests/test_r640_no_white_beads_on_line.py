# -*- coding: utf-8 -*-
"""r640：关注走势不得用卡片底色在折线上打洞。

用户反复报「白白的折叠遮挡短点」「走势一定不可以断档」。
原实现在聚焦系列上逐个顶点画 `arc(...,1.7)` + `fillStyle=CARD` + 1px 色环——
放大截图可见折线被切成串珠状白洞（_scratch/x_watch_zoom.png）。
采样证据已由 PCHART.line 的 vertexDots（同色实心点，不透明度 ≥.85）承担，
白心环是重复层且把线打断。

判据：关注走势的绘制段落里，不得出现「填充色 == 卡片底色」的 arc。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _watch_draw_block():
    src = _src()
    i = src.index("const focusId=WS.focus")
    j = src.index("const tgt=Number(s.w.target);", i)
    return src[i:j]


def test_watch_series_never_fills_vertices_with_card_color():
    blk = _watch_draw_block()
    hits = blk.count("fillStyle=CARD;ctx.fill()")
    assert hits == 0, (
        "关注走势又用卡片底色在折线顶点打洞（会把线切成白点）：%d 处" % hits)


def test_watch_series_keeps_same_color_vertex_dots():
    """采样证据不能一起删掉——每个点仍要有同色实心标记。"""
    src = _src()
    assert "vertexDots:true" in src, "PCHART.line 的采样点标记被删了"
    blk = _watch_draw_block()
    assert "PCHART.line(" in blk, "关注走势不再走统一内核"


def test_last_point_marker_is_solid_series_color():
    """末点仍是实心系列色（描边只在圆外，不进线体）。"""
    blk = _watch_draw_block().replace("\n", "").replace(" ", "")
    i = blk.index("constlastP=pts[pts.length-1];")
    seg = blk[i:i + 400]
    j = seg.find("consttgt=")
    draw = seg[:j] if j > 0 else seg
    assert "fillStyle=s.color;ctx.fill()" in draw, draw
    assert "fillStyle=CARD" not in draw, "末点改成卡片底色=又在线体上打洞"
