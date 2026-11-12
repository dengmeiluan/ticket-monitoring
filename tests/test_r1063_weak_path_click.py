# -*- coding: utf-8 -*-
"""r1063 T199：通路弱环**可点**（行内链接 → 真查询自检）。

用户要"一切可干预"：看到弱环应当能立刻动手，而不是"看到数字、再去别处找按钮"。
约束是微信级扁平 —— 不新增控件样式，用行内 `<a>`（继承 `.snote` 字号颜色）。

两次踩坑（都是真机验证抓到的）：
1. 外层 `esc(top.join(' · '))` 把注入的 `<a>` **转义成文本**（实测 links=0，
   页面上看到的是 `<a href="#" …` 字样）；
2. `async function srxWeakProbe` 一度写在渲染函数**内部**，行内 onclick
   只能解析全局名 → 点击报 `srxWeakProbe is not defined`。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_probe_helper_exists_and_is_top_level():
    """必须是顶层函数：放在渲染函数里，行内 onclick 解析不到（实测报错）。"""
    w = _w()
    assert "async function srxWeakProbe" in w
    i = w.index("async function srxWeakProbe")
    # 顶层函数的特征是行首一个空格（本项目全局函数都是 1 空格缩进）
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", (
        "srxWeakProbe 不是顶层函数：行内 onclick 会报 not defined")


def test_weak_items_are_links_not_escaped():
    """弱环条目要渲染成真正的链接，不能被外层 esc 转成文本。"""
    w = _w()
    i = w.index("通路弱环（近24h）")
    seg = w[i - 400:i + 400]
    assert "srxWeakProbe" in seg, "弱环条目没有绑定自检"
    assert "'通路弱环（近24h）：'+top.join(' · ')" in w, (
        "外层 esc 会把 <a> 转义成文本（实测 links=0）")


def test_link_carries_plat():
    w = _w()
    i = w.index("onclick=\"return srxWeakProbe")
    seg = w[i:i + 200]
    assert "esc(r.plat)" in seg, "链接必须带上渠道名，否则自检不知道点的是谁"
