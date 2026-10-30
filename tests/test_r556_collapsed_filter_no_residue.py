# -*- coding: utf-8 -*-
"""r556：选过出发日之后收起的筛选区，不得比初始收起态多出常驻行。

用户原话：「展开概览下面是可以再点击选择出发日，然后再点击收起概览
就整体收不回去了」。实测根因不在概览，而在筛选区：`.ctx-collapsed`
只收 `.srx-line:nth-child(n+2)` 与 `.srx-fmore`，漏了结果筛选条
`.srx-abar`——选日期后它一直留在收起态里，把该区从 46px 撑到 74px，
整页比初始高 28px。
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = SRC.read_text(encoding="utf-8")


def _collapsed_rule():
    m = re.search(
        r"#searchview \.srx-context\.ctx-collapsed \.srx-abar\{([^}]*)\}", TEXT)
    assert m, "缺少 .ctx-collapsed .srx-abar 规则——收起态会残留结果筛选行"
    return m.group(1)


def test_collapsed_filter_hides_result_bar():
    body = _collapsed_rule()
    assert "display:none" in body.replace(" ", ""), body


def test_result_bar_rule_sits_in_collapse_block():
    """必须在同一条「收起态」规则组里，而不是散落别处被后面的规则盖掉。"""
    i = TEXT.index("#searchview .srx-context.ctx-collapsed .srx-line:nth-child(n+2)")
    j = TEXT.index("#searchview .srx-context.ctx-collapsed .srx-abar")
    assert 0 < j - i < 900, (i, j)
    assert j > i


def test_selected_date_still_visible_when_bar_hidden():
    """收起后所选日期仍可读：列表头写「所选 YYYY-MM-DD」，按钮有数量徽标。"""
    assert "所选 '" in TEXT or "所选 " in TEXT
    tail = TEXT[TEXT.index("function srxRenderCtx()"):]
    tail = tail[:tail.index("function ", 10)]
    assert "srxCtxCount()" in tail
    assert "SRX.date" in TEXT[TEXT.index("function srxCtxCount()"):][:400]
