# -*- coding: utf-8 -*-
"""r980：特价雷达数据不足时不再留一整块 340px 灰底画布。

旧实现数据不足分支只在画布底部写一行脚注，空态覆盖层仍按 340px 画布
居中，读作「图画坏了 / 大片空白」。现在 sparse 态收成 168px，脚注
（与空态同义）同时收掉，避免在矮盒里被裁成半行。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_sparse_chart_collapses_to_compact_height():
    import webui
    src = webui.PAGE
    i = src.index(".spmon-chartwrap.is-sparse{")
    seg = src[i:i + 220]
    assert "min-height:168px!important" in seg, seg
    assert "height:168px!important" in seg, seg
    assert ".spmon-chartwrap.is-sparse canvas{height:150px!important}" in src
    assert ".spmon-chartwrap.is-sparse #spMonChartNote{display:none!important}" in src, \
        "矮盒里同义脚注会被裁成半行"


def test_sparse_class_is_set_and_cleared_on_both_empty_branches():
    import webui
    src = webui.PAGE
    # 绘制入口先复位，数据够画线时不残留矮画布
    i = src.index("function spMonDraw(dateSeries,selDate,lowDate){")
    head = src[i:i + 900]
    assert "classList.remove('is-sparse')" in head, head
    # K 线不足两天 + 折线不足两次采集两个分支都要加
    k = src.index("仅 '+he(candles[0].d)+' 一个采集日")
    assert "classList.add('is-sparse')" in src[k - 520:k], "K 线空态没有收成矮盒"
    t = src.index("当前范围只有 '+times.length+' 次采集")
    assert "classList.add('is-sparse')" in src[t - 520:t], "折线空态没有收成矮盒"
    # 覆盖层高度必须按收后的画布重新量，不能沿用收前的 H
    assert "Math.min(H,c.clientHeight||H)" in src, \
        "空态覆盖层仍按收前的画布高度居中"
