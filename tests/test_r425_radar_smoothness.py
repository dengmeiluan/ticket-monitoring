# -*- coding: utf-8 -*-
"""r425 雷达三项量化门禁（用户主观词「卡顿/断档/白白遮挡」的可执行判据）。

本机实测（2026-10-28，webui.py 4252 全绿时的构建）：
  A) 拖动：画布 2606px、容器 1086px，CDP 触摸拖 25 步 →
     scrollLeft 0→1520（真的滚了），帧中位/p95 = 16.7ms，超 33ms 帧 = 0。
  B) 断档：注入 22h–46h 真空窗 → 缺口 714 CSS px 全无墨，
     缺口左右各有点染料（端点未被吃掉）。
  C) 遮挡：390/460/760 三档「画布 ∩ 视口」15 个采样点全部命中 canvas。

A 与 B 需要真实画布，代价高；这里固守「代码契约」部分：
  - 画布宽度公式必须允许超出容器（否则 scrollWidth==clientWidth，拖了不动）；
  - 缺口阈值 4h 且缺口必须分段（不得跨缺口连线）；
  - 位图只在尺寸变化时重设（否则每帧重分配，读作闪烁）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui.PAGE


def test_radar_canvas_can_exceed_viewport():
    """r373 曾把画布宽度锁成可视宽：拖动指令还在、光标还是 grab，
    但 scrollWidth==clientWidth，拖了完全不动 —— 用户读作「滑动卡顿」。
    画布宽必须是「可视宽」与「点数 × 最小间距」取大（带上限）。"""
    src = _src()
    i = src.index("const baseW=Math.max(320,wrap.clientWidth||600);")
    seg = src[i:i + 700]
    assert "const W=Math.max(baseW,Math.min(units*MINPX,baseW*2.4));" in seg, seg
    assert "c.style.width=W+'px';" in seg, seg
    # 溢出时必须真的能横滚
    assert ".spmon-chartwrap{overflow-x:auto;overflow-y:hidden" in src


def test_radar_bitmap_not_reallocated_per_frame():
    """每帧重设 canvas.width/height 等于清空 + 重分配位图，悬停/节流时整幅闪
    一下，读作「不丝滑」。只在尺寸真的变了才重设。"""
    src = _src()
    i = src.index("const _bw=Math.max(1,Math.round(W*dpr))")
    seg = src[i:i + 260]
    assert "if(c.width!==_bw|c.height!==_bh){c.width=_bw;c.height=_bh;}" in seg, seg


def test_radar_gap_is_segmented_not_bridged():
    """「走势一定不可以断档」不是「必须连起来」——真实没数据的时间窗必须
    留空，且两端点要各自可见（否则走势断在看不见的地方）。
    判据：缺口阈值 4 小时，且面积/折线都按缺口分段。"""
    src = _src()
    assert "const _gapMin=4*3600*1000;" in src
    # 主系列面积填充带 gapMin（分段）
    i = src.index("if(low||sel)PCHART.area(ctx,g,x.pts.map")
    seg = src[i:i + 220]
    assert "gapMin:_gapMin" in seg, seg
    # 折线同样分段
    assert src.count("gapMin:_gapMin") >= 2, "折线与面积都应分段"


def test_radar_no_opaque_overlay_above_canvas():
    """用户实报「白白的折叠遮挡短点」。画布所在的 .spmon-chartwrap 里
    除 canvas 外只允许 .spmonChartNote（透明、且在画布外）——
    不得再塞不透明面板/遮罩进去。"""
    src = _src()
    i = src.index('<div class="spmon-chartwrap">')
    seg = src[i:src.index("</div>", src.index("spMonChartNote", i))]
    assert seg.count("<canvas") == 1, seg
    # 允许的覆盖层只有 tip（悬停才显示）、cross（发丝线，无底色）、note（透明）
    for tag in ("spMonTip", "spMonCross", "spMonChartNote", "spMonTable"):
        assert tag in seg, tag
    assert "spmon-fold" not in seg and "spmon-mask" not in seg, seg


def test_demo_health_rows_show_no_fake_rates():
    """用户实报「现在有很多都是补位数据，感觉有点奇怪，确认下真实性和解析
    的正确性」。`--demo` 的分通路账是按合成轮次迭代算的，`查询 97% ·
    明细 x / 日历 y · n 次` 与真实实测读数长得一模一样，会被当成实测引用。
    演示态该半栏只说明「合成样本」，真实实例照常给百分比与次数。

    r466 起判据从 `_demoAll` 收紧为 `_maskSynth = _demoAll && _pthDemo`：
    只看 advice 会把「演示 advice + 真库账本」也遮掉，导致同一页健康卡
    11% 与节流面板「不参与成功率」两数打架。纯演示下两者等价。"""
    src = _src()
    i = src.index("const pathTxt=")
    seg = src[i:i + 400]
    assert "_maskSynth?'':" in seg, "演示态仍在通路串里给百分比"
    # 判据必须同时要求「advice 是演示」与「账本也是合成」
    k = src.index("const _maskSynth=")
    assert "_demoAll&&_pthDemo" in src[k:k + 60], "遮蔽条件丢了账本来源判断"
    j = src.index("const _qbit=_maskSynth")
    q = src[j:j + 420]
    assert "'合成样本 · 不参与成功率'" in q, q
    assert "'查询 <b>'+_rate(_qr)+'</b> · 明细 '" in q, "真实实例的次数口径被误删"
    # _demoAll / _pthDemo 都必须早于这两处定义（TDZ）
    assert src.index("const _demoAll=Object.keys(ch)") < i
    assert src.index("_pthDemo=!!_pj.demo") < i
