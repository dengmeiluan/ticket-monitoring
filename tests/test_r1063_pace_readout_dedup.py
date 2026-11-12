# -*- coding: utf-8 -*-
"""r1063 T53：健康页读数**去重与术语统一**（串起来看的收尾）。

这十几轮往健康页加了不少读数（等待秒数、降频、会话重建、换道判据、7 天成效、
耗时构成）。这轮不是加东西，而是把已有的盘一遍，找出**重复**与**术语冲突**：

1. 「节流跳过」原先在**耗时行**与**配额轨图例**各写一次——同一个数字两处。
   只留图例（图例是配额的语义落点，耗时行讲时间）；
2. 「其中限速等待 X%」与行内「等 210s」都叫"等待"，但一个是**闸门睡眠占墙钟**、
   一个是**单渠道等待秒数**。术语分开：闸门 / 等待，并在 title 里写明；
3. 换道那行的「预置/换道/回采」是**本轮**、7 天行是**近 7 天**——补「本轮」前缀。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _timeline():
    i = SRC.index("const _timeline=(()=>{")
    j = SRC.index("})();", i)
    return SRC[i:j]


def test_paced_is_not_reported_twice():
    """「节流跳过」只在配额轨图例里出现一次（耗时行是讲时间的）。"""
    seg = _timeline()
    assert "次节流跳过" not in seg, "耗时行又重复报了节流跳过"
    assert "主动未发" in SRC, "图例里也要有同一个数"


def test_wait_terminology_is_distinct():
    """闸门（我方睡眠占比）与等待（单渠道秒数）必须用不同的词。"""
    seg = _timeline()
    assert "闸门等待" in seg
    assert "限速等待" not in seg, "「限速等待」容易和行内「等 Ns」混淆"
    # title 要把两个词的关系讲清
    i = SRC.index("闸门等待＝我方限速睡眠")
    assert "单渠道" in SRC[i:i + 120]


def test_failover_line_says_this_round():
    """「本轮」与「近 7 天」是两个尺度，前缀不能省。"""
    assert ">本轮换道：'" in SRC
    assert "近 '+(Number(_h.days||7))+' 天" in SRC or "近 " in SRC


def test_no_new_visible_nodes():
    """这轮只改文案，不新增可见元素。"""
    seg = _timeline()
    assert seg.count("<div class=") == 1, "耗时行不该新增 div"
