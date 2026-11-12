# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r640_no_white_beads_on_line.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os


# ---- merged from tests/test_r640_no_white_beads_on_line.py ----

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
