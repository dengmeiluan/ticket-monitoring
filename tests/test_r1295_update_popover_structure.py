# -*- coding: utf-8 -*-
"""r1295：结构门禁——`#updPop` 只装更新卡，绝不能吞掉 <footer>。

起因（2026-11-10 19:5x）：我把「版本与更新」从渠道健康搬到页脚上面时，
**漏掉了 `#updateCard` 的收尾 `</div>`**，于是 `<footer>` 被套进弹层里 ——
用户看到的就是"排版坏了"（页脚行跑进白卡、整页多出一大块）。

这类"标签少一个"的错误 `py_compile` 查不出、点开也能点，**只有看 DOM 才现形**。
所以立一条源码级门禁：区域内 `<div>` 开闭必须配平，且 footer 必须紧跟在弹层之外。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _pop_region():
    i = SRC.find('<div id="updPop"')
    assert i > 0, "找不到更新弹层"
    j = SRC.find("<footer", i)
    assert j > 0, "找不到页脚"
    return SRC[i:j]


def test_popover_divs_are_balanced():
    r = _pop_region()
    opens, closes = r.count("<div"), r.count("</div>")
    assert opens == closes, "弹层内 <div> 未配平：开 %d / 闭 %d（少一个就会吞掉后面的元素）" % (
        opens, closes)


def test_footer_is_outside_popover():
    """页脚必须整体在弹层之后（弹层区域截止到 <footer> 之前，天然满足）。"""
    i = SRC.find('<div id="updPop"')
    j = SRC.find("<footer", i)
    assert j > i
    # 弹层区域里不允许出现 footer 的开启标记
    assert "<footer" not in SRC[i:j]
    # 且 footer 之后不应再有属于弹层的收尾（粗略：footer 到 </body> 之间不再出现 updPop）
    assert SRC.count('<div id="updPop"') == 1


def test_update_card_left_the_health_pane():
    """更新卡不许再回到渠道健康里（用户 19:38 明确要求跟随"版本"那块）。"""
    h0 = SRC.find('<div id="montab-health"')
    h1 = SRC.find("</div><!-- /montab-health -->", h0)
    assert h0 > 0 and h1 > h0
    assert 'id="updateCard"' not in SRC[h0:h1], "更新卡又被塞回渠道健康了"


def test_update_card_sits_in_popover():
    i = SRC.find('<div id="updPop"')
    j = SRC.find("<footer", i)
    assert 'id="updateCard"' in SRC[i:j]
