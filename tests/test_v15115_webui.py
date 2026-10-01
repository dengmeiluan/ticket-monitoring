# -*- coding: utf-8 -*-
"""WD P1-1/P2-1/P2-2 + EN-4：

--hdh 动态 header 高度单源：吸顶偏移原是固定像素（按 demo 无倒计时
态校准），生产 ⏱ 倒计时 chip 折行使实高 72~134 漂移——固定值全带
错位（768 实测吸顶条被盖 33px、≤540 与 header 透缝 18-29px 且随
倒计时文案漂移）。ResizeObserver 写 CSS 变量，吸顶块消费 var(--hdh)
贴实高；JS 失效 fallback 保现值零退化。761-900 固定校准块（top:76px
/补偿 106px）随动态化整块退役（变量自动跟随折行，固定校准成为冗余
覆写）；761+ 锚点补偿 88px 同步动态化（54+34 等值迁移）。
"""
import os

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = open(os.path.join(os.path.dirname(webui.__file__),
                                 "webui.py"), encoding="utf-8").read()
    return _SRC


def test_hdh_observer_writes_var():
    s = src()
    assert "ResizeObserver" in s
    # 变量挂 documentElement（:root 域全局可消费），fallback 域内保现值
    assert "setProperty('--hdh'" in s
    assert s.count("var(--hdh,") >= 5


def test_sticky_tops_consume_hdh():
    s = src()
    # 三处吸顶 top 动态化（fallback 保现值：134/134/54）
    assert "#montabs{position:sticky;top:var(--hdh,134px)" in s
    assert "top:calc(var(--hdh,134px) + var(--mtabsh))" in s
    assert "#montabs{position:sticky;top:var(--hdh,54px)" in s
    # 固定校准块退役：带内覆写值不复在（grep 全文唯一性已核）
    assert "top:76px" not in s
    assert "scroll-padding-top:106px" not in s
    # 761+ 锚点补偿随动态（88 = 54+34 等值迁移，demo 两带实测等值）
    assert "scroll-padding-top:calc(var(--hdh,54px) + 34px)" in s
    assert "scroll-padding-top:88px" not in s


def test_kpisum_link_touch_target():
    # P2-2 触控外扩家族收编（#foot a::after 同款 inset 两行，视觉零变化）
    s = src()
    assert ".kpisum a{position:relative" in s
    assert (".kpisum a::after{content:'';position:absolute;"
            "inset:-10px -4px}" in s)


def test_montab_grid_roving_vertical():
    # EN-4（挂账销账）：↑↓ 网格形制族移动——仅 montabs 挂载，
    # 脉冲柱/健康格行为面不动（单行/既有键面不受扰）
    s = src()
    assert "_rovingV" in s
    assert 'onkeydown="_roving(event,this);_rovingV(event,this)"' in s
