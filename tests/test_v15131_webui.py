# -*- coding: utf-8 -*-
"""WebUI 收尾（r231 审计落地）：canvas「低」标注文字档令牌。

背景（_scratch/r231_wd_webui.md，P0=0/P1=0/P2=2）：
- canvas「低 ￥…」最低价标注文字随所属系列色，中转橙直用图形档
  --orange（#c96a10 对白 halo 3.78:1，11px bold 硬性欠 AA 4.5）——
  对比度扫描（DOM TreeWalker）对 canvas 像素层结构性盲区；修法=
  折线/K线两模式「低」标注橙支路消费文字级令牌 --orange-txt
  （#a45508 对白 5.41；暗色成对换谱 #e6922e 与现值零漂移，零观感
  漂移）。蓝支路 #0b62d6 对白 5.63 已过线不动。
  （配置导航选中片 hover 成员补齐的钉面同步在同族
  test_v15130_webui.test_p23 内。）
"""
import inspect
import re

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = inspect.getsource(webui)
    return _SRC


def test_canvas_mintag_orange_uses_text_token():
    s = src()
    assert "(cssv('--orange-txt')||'#a45508')" in s, \
        "canvas「低」标注橙支路未消费文字级令牌（图形档 3.78 欠 AA）"


def test_canvas_mintag_text_token_exactly_two_modes():
    body = re.search(r"const chartDraw=", src())
    assert body, "chartDraw 不在源码"
    seg = src()[body.start():body.start() + 30000]
    assert seg.count("cssv('--orange-txt')") == 2, \
        "折线/K线两模式「低」标注橙支路须恰两处挂文字级令牌（计数钉）"
