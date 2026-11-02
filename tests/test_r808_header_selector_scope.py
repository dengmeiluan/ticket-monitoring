# -*- coding: utf-8 -*-
"""r808 门禁：`header` 选择器必须带作用域。

背景：源里曾有一条**裸 `header{...}`**（background:var(--card) +
border-bottom + position:sticky + box-shadow + 负 margin 出血）。页面上
一共 8 个 `<header>`——页面页头 `#hdcard`、关注卡头 `.ws-head`、筛选面板
里 5 个 `.srf-card>header`、明细分组头——全都吃到这条样式：每张小卡顶着
一片**白色通栏横带**（左右各外扩 18px）并自带一条分割线。
用户两次点名：「折叠起来了，但是有很多分割线，很不干净」「很多页面布局
对齐对称衔接都出现问题了」。当时 DOM 量到 `.srf-card>header` 是
margin:-18px / padding:9px 18px 2px / 白色底 / 高 31px。

判据：`<style>` 里不得再出现「整段就是裸 header」的选择器。
负控：把 `#hdcard{` 改回 `header{` 即红。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
_RAW = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)
# 注释里写了 `border-bottom`、`header{...}` 之类的历史说明，不能当 CSS 读
STYLE = re.sub(r"/\*.*?\*/", "", _RAW, flags=re.S)


def _selectors():
    out, depth, buf = [], 0, ""
    for ch in STYLE:
        if ch == "{":
            if depth == 0:
                out.append(buf.strip())
            depth += 1
            buf = ""
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            buf = ""
            continue
        if depth == 0:
            buf += ch
    return out


def test_no_bare_header_selector():
    bad = []
    for sel in _selectors():
        if not sel or sel.startswith("@"):
            continue
        for part in sel.split(","):
            # 只有「整段就是一个裸 header」才是缺陷——`X>header` / `.a header`
            # 都是带作用域的，属于正常组件写法。
            if part.strip() == "header":
                bad.append(part.strip())
    assert not bad, (
        "裸 header 选择器回来了——它会同时命中页面页头、关注卡头与筛选面板里"
        "每张卡的头，给卡片加白色通栏横带和分割线：%r" % bad)


def test_page_header_is_scoped_and_sticky():
    assert "#hdcard{background:var(--card);border-bottom:1px solid var(--line2)" in STYLE
    i = STYLE.index("#hdcard{")
    seg = STYLE[i:i + 500]
    assert "position:sticky;top:0;z-index:50" in seg, seg


def test_card_headers_draw_no_band():
    """卡头不许自绘表面（背景/下边线/负 margin）。"""
    i = STYLE.index("#searchview .srf-card>header{")
    seg = STYLE[i:STYLE.index("}", i)]
    for bad in ("border-bottom", "background", "margin"):
        assert bad not in seg, (bad, seg)
