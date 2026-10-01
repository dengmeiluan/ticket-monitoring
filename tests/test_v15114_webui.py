# -*- coding: utf-8 -*-
"""WebUI 层（审计 W-1/W-2/EN-W3/W4/W5 = M-1/M-2 收编）：

1. W-1 ≤~430 视口视图切换器折行裁残：基础 .tabs flex-wrap:wrap
   泄漏进 #montabs 单行横滚形制（overflow-x:auto 未声明 nowrap），
   390/414 档第 4 格折行后被锁高 52px+隐滚动条裁成 10px 残条。
   修法=补 flex-wrap:nowrap（单行横滚形制归位）+ xhint 判定点/渐隐
   暗示挂上 #montabs（nowrap 后窄档真溢出，滚动条已隐须有暗示）。

2. W-2 走势入场动画首帧 rAF 时间戳可早于 t0 → p/e 为负 → 负宽
   clip 矩形按 canvas 规范归一进 y 轴标签带（clearRect 擦带+标签
   中段切片入画），后续帧永不回补=首次进入 y 轴标永久残缺。
   修法=负 p 钳零（首帧 clip 宽 0 不误伤标签带）。

3. EN-W3/M-2 走势空态清 ringNote：满编环标图例与「暂无走势数据」
   同屏互斥（图例解释的图并不存在）。

4. EN-W4 #montabs 键盘族：data-rv+方向键 _roving 单源 + Enter/Space
   激活（键穿越审计备案落地）。

5. EN-W5/M-1 触控三块声明族成员对齐：≤760 块补 .fbar .switch::before
   （≤900coarse/901+coarse 两姊妹块均有，唯一漂移成员）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15114_webui.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402

PAGE = webui.PAGE


# ---- W-2 走势 y 轴标残缺 ----

def test_w2_anim_negative_p_clamped():
    """入场动画 p 钳 [0,1]：rAF 首帧时间戳早于 t0 时 p<0 曾产负宽
    clip 矩形（canvas 规范归一进 y 轴标签带，clearRect 擦带+标签
    中段切片入画，后续帧永不回补）。"""
    assert "const p=Math.max(0,Math.min(1,(t-t0)/700))" in PAGE


def test_w2_reveal_rect_covers_label_band():
    """揭示矩形起点=画布左缘：y 轴标签带 [0,L) 必须首帧即在 clip
    内——钳零只断负宽根因，揭示矩形从 L-2 起步时标签带在任何动画
    帧都不在 clip 内，首入 y 轴标仍缺（终帧须与非动画全绘逐位等）。"""
    assert "ctx.rect(0,0,L-2+(W-L+2)*e,H)" in PAGE


# ---- W-1 视图切换器折行裁残 ----

def test_w1_montabs_nowrap_declared():
    """#montabs 单行横滚形制显式声明 nowrap：基础 .tabs
    flex-wrap:wrap 不再泄漏（折行格被锁高+隐滚动条裁残的根因）。
    #montabs 有多媒体块级联（≤760 grid 形制/≤540 横滚形制/≥761
    吸顶形制），凡声明 overflow-x:auto 的横滚形制规则必须自带
    flex-wrap:nowrap（形制与换行互斥，防未来新档位再漏）。"""
    rules = re.findall(r"#montabs\{[^}]*\}", PAGE, re.S)
    scroll = [r for r in rules if "overflow-x:auto" in r]
    assert scroll, "横滚形制规则缺席"
    assert all("flex-wrap:nowrap" in r for r in scroll)


def test_w1_xhint_selector_covers_montabs():
    """xhint 溢出判定四挂点全部含 #montabs（nowrap 后窄档真溢出，
    滚动条已隐、无暗示即复刻明细条修复前同款问题）。r247 W1 起
    四挂点同步扩至 #opscard .opsbtns（窄档单行横滚族同批重判），
    钉面随判定族扩展更新。r253 起 .tw（表内横滚提示）并入其中
    两挂点（health 渲染批/resize 批）——旧串 2 处 + 扩展串 2 处，
    四挂点不丢。"""
    assert PAGE.count(
        "querySelectorAll('.hcells,#montab-details .tabs,#montabs"
        ",#opscard .opsbtns')") == 2
    assert PAGE.count(
        "querySelectorAll('.hcells,#montab-details .tabs,#montabs"
        ",#opscard .opsbtns,.tw')") == 2


def test_w1_montabs_xhint_after_fade():
    """≤540 块 #montabs 渐隐暗示 ::after 与点亮态在案
    （明细吸顶条同款装饰层，非容器 mask——mask 会连 sticky 件淡出）。"""
    assert "#montabs.xhint::after{opacity:1}" in PAGE
    assert "#montabs::after{content:''" in PAGE


# ---- EN-W3/M-2 空态图例互斥 ----

def test_w3_empty_state_clears_ring_note():
    """空态分支清 ringNote：满编环标图例不与「暂无走势数据」同屏
    （已配置未扫描航线打开走势时图例解释的图并不存在）。"""
    assert "$('ringNote').innerHTML=''" in PAGE


# ---- EN-W4 montabs 键盘族 ----

def test_w4_montabs_roving_and_activation():
    """四 mtab 全部 data-rv+可聚焦（方向键 _roving 族移动）+
    Enter/Space 激活（showMonTab）；容器挂 _roving 委托。"""
    assert re.search(r'id="montabs"[^>]*_roving\(event,this\)', PAGE)
    for t in ("overview", "trend", "details", "health"):
        m = re.search(r'<span class="mtab[^"]*" data-t="%s"[^>]*>' % t, PAGE)
        assert m, t
        tag = m.group(0)
        assert 'data-rv' in tag and 'tabindex="0"' in tag, t
        assert 'showMonTab' in tag, t


# ---- EN-W5/M-1 触控三块成员对齐 ----

def test_w5_touch_block_member_aligned():
    """.fbar .switch::before 热区成员三块齐备（≤900coarse/≤760/
    901+coarse；≤760 曾缺——双命中姊妹块现状零暴露，防新增开关位
    时家族漂移）。"""
    assert PAGE.count(".fbar .switch::before") == 3
