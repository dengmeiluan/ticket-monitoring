# -*- coding: utf-8 -*-
"""r338 WebUI 审计 P3 四案钉（W1 审计 _scratch/r338_webui_audit.md）。

P3-1 header 内容轴带内偏移：391-599 带 header 左右 padding 恒 18px、
出血 margin 却随 clamp(12px,3vw,18px) 走——h1 左缘（18px）比卡轴
（3vw=11.7~18px）偏右 6px→0（W1 实测 391 带偏 6px、450 带 4.5px、
600 归零）。修法 padding 与出血同函数：padding:9px clamp(12px,3vw,18px)，
「相抵律」从盒缘扩展到内容缘，全带 h1 左缘==卡片内容左缘。
（W1 现场复核+截图三证；几何实效由本轮真机探针复测，源码钉锁声明
形态与两函数咬合。）

P3-2 明细次行换乘词段断词：webui 明细 .stl 行「换乘·X（Y出）」段
裸排（同数组机场段/机型段均 <span class="nw"> 包裹），td .stl 容器
放开换行（white-space:normal）下宽屏折行出孤字尾行（W1 实测 1920 带
「换乘·胶东T|T1」末行 11.7px 孤字，4 行中转同病灶）。修法同构包
<span class="nw">（td .stl.nw 升特异度版已在案兜住）。

P3-3 .flab 文字区 hover 零反馈：cursor:pointer 在场（可点语义声明）
而 hover 无任何视觉反馈（W1 12 通道实测零变化）——补 color 提亮档
.flab:hover{color:var(--tx)}（次级灰 → 正文色，语义=悬停可交互）。

P3-4 注释漂移随 P3-1 同文件修（.wrap 注释「≤540 的 10px」实为
≤390 块，540 块无 wrap/header 覆写——W1 双证）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r338_webui_p3.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
                encoding="utf-8").read()


def test_p3_1_header_padding_matches_bleed_function():
    """P3-1：header 左右 padding 与出血 margin 同一 clamp 函数（全带）。"""
    src = _src()
    # 实效档：基础块 header 水平 padding=clamp(12px,3vw,18px)——与
    # margin:0 calc(-1*clamp(12px,3vw,18px)) 同函数，391-599 带内
    # 内容缘逐点==卡轴（出血相抵后 header 左缘=视口缘，padding 落
    # 3vw==wrap 内容缘）；≥600 cap 18px 桌面语言不变
    assert "padding:9px clamp(12px,3vw,18px)" in src
    # 置尾覆写块同函数（≤760 移动端合并块声明序在基础块后，同特异性
    # 恒压——漏改它则 391-760 全带被压回恒 18px，探针实锤）：上下
    # 12px 移动档保留，左右随出血函数
    assert "header{padding:12px clamp(12px,3vw,18px)}" in src
    # 禁复活：恒 18px 旧形态（基础块 391-599 带偏 6px / ≤760 块压回恒值）
    assert "padding:9px 18px;display:flex" not in src
    assert "header{padding:12px 18px}" not in src


def test_p3_2_transfer_terminal_word_nowrap():
    """P3-2：换乘词段整词 nowrap（同数组机场段/机型段同构）。"""
    src = _src()
    # 实效档：换乘段包 <span class="nw">——「换乘·X（Y出）」是含
    # 语义的中文词组+航站楼码，裸排在 td .stl（white-space:normal）
    # 容器里宽屏折行出孤字
    assert '<span class="nw">换乘·' in src
    # 禁复活：裸排形态零命中（同数组其余 nw 段不受此断言约束）
    assert "f.transTerminal?'换乘·'+he(" not in src


def test_p3_3_flab_hover_feedback():
    """P3-3：.flab hover 有视觉反馈（color 提亮档）。"""
    src = _src()
    assert ".flab:hover{color:var(--tx)}" in src
