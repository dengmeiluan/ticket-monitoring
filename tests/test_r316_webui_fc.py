# -*- coding: utf-8 -*-
"""forced-colors 高对比选中态（r316 审计 FC-1）：系统强制配色剥离
背景色，.on 家族的蓝底视觉归零——9 项计算属性与未选中件零差异
（实测 r316ui_d45_media.json）。修复双臂：
1. CSS 边框/轮廓档：@media(forced-colors:active) 下选中态由 outline
   CanvasText 承载（outline 不参与布局，零位移）；
2. 程序态：明细筛选片（datechips/routechips/platchips）与配置页渠道
   片的切换点补 aria-pressed 回写、重建模板带初始态——此前筛选档
   「无视觉+无程序态」双缺，forced-colors 用户只能从行数变化反推。"""
import os

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()


def test_forced_colors_media_block_covers_on_family():
    """forced-colors 块在场且覆盖选中态家族（mtab/tabs/mainnav/cnav/
    rngchip/chip 六族）；块内断言锚 outline+CanvasText（系统配色
    令牌——写死色值在 forced-colors 下被二次覆盖）。"""
    assert "forced-colors: active" in _SRC or "forced-colors:active" in _SRC
    # 块体：从 media 开头到下一个 } 前须含六族选择器与 outline 声明
    i = _SRC.find("forced-colors")
    assert i > 0
    body = _SRC[i:_SRC.find("}", _SRC.find("CanvasText", i))]
    for sel in (".mtab.on", "#tabs span.on", "#mainnav span.on",
                ".cnav.on", ".rngchip.on", ".chip.on"):
        assert sel in body, (sel, body[:200])
    assert "outline" in body and "CanvasText" in body


def test_filter_chip_toggles_write_aria_pressed():
    """筛选片四处切换点（togDate/togRoute/togChip/togPlat）回写
    aria-pressed——程序态与视觉态同拍，读屏可辨当前筛选档。"""
    for fn in ("function togDate(", "function togRoute(",
               "function togChip(", "function togPlat("):
        i = _SRC.find(fn)
        assert i > 0, fn
        body = _SRC[i:_SRC.find("\nfunction ", i + 4)]
        assert "aria-pressed" in body, fn


def test_filter_chip_templates_carry_initial_aria():
    """重建模板（buildDateChips/buildRouteChips/buildChips 的 chip
    串）带 aria-pressed 初始态——10s 轮询重建曾只翻类丢程序态
    （多入口共享件静态初始值是假单源，LESSONS 二十§1）。"""
    for anchor in ("box.innerHTML='<span class=\"chiplab\">日期：</span>'",
                   "box.innerHTML='<span class=\"chiplab\">航线：</span>'"):
        i = _SRC.find(anchor)
        assert i > 0, anchor
        tail = _SRC[i:i + 400]
        assert "aria-pressed" in tail, anchor
    # 渠道片模板（buildChips 内 chip 串）
    i = _SRC.find("const b=badge(p);")
    assert i > 0
    tail = _SRC[i:i + 400]
    assert "aria-pressed" in tail, tail[:200]
