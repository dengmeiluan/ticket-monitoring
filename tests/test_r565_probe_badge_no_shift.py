# -*- coding: utf-8 -*-
"""r565：探针卡头「DEMO · 合成」小标与标题两态零位移。

用户原话：「展开的时候，demo 合成的位置抖动偏移了」。
运行时实测（390/760）：收起态卡片被密度层强制回 display:block，
b/em 退回行内盒，height 失效只剩半行距，展开态是 flex 项（块盒），
于是标题顶 279.1 → 277.1（-2px）、小标 -1.5px。
负控：把 display 改回 inline，抖动 +2.0/+1.5 立即复现。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _text():
    import webui
    return open(webui.__file__, encoding="utf-8").read()


def _narrow_block(src):
    i = src.index("@media(max-width:760px){")
    j = src.index("\n  }\n", i)
    return src[i:j]


def _rule(block, sel):
    i = block.index(sel)
    b = block.index("{", i)
    e = block.index("}", b)
    return block[b + 1:e]


def test_title_and_badge_are_block_level_in_narrow_tier():
    block = _narrow_block(_text())
    b = _rule(block, "#searchview .srx-probehead>b")
    em = _rule(block, "#searchview .srx-probehead>em")
    assert "display:block" in b.replace(" ", ""), b
    assert "display:block" in em.replace(" ", ""), em


def test_title_has_fixed_height_so_line_box_cannot_grow():
    block = _narrow_block(_text())
    b = _rule(block, "#searchview .srx-probehead>b").replace(" ", "")
    assert "height:19.5px" in b, b
    assert "line-height:1.5" in b, b
    assert "align-self:flex-start" in b, b


def test_collapsed_card_is_still_block_not_flex():
    """收起态必须是 block——这条是抖动的来源，不能被「统一成 flex」改掉。"""
    src = _text()
    line = "#searchview .srx-probe:not(.open){display:block!important;padding:0!important}"
    assert line in src


def test_badge_keeps_placeholder_when_collapsed():
    """收起态 em 必须靠 visibility:hidden 占位。

    ≤900 档还有一条组规则把 em 写成 display:none，它靠后面同选择器
    的 `display:block!important;visibility:hidden!important` 覆盖——
    判据取源码里最后一条（同特异性下带 !important 者胜），而不是逐条禁。
    """
    src = _text()
    hits = list(re.finditer(
        r"\.srx-probe:not\(\.open\) \.srx-probehead>em\{([^}]*)\}", src))
    assert hits, "collapsed badge rule missing"
    body = hits[-1].group(1).replace(" ", "")
    assert "visibility:hidden" in body, body
    assert "display:none" not in body, body
