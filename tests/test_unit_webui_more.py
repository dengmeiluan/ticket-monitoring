# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r262_webui.py
- tests/test_v225_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import sys


# ---- merged from tests/test_r262_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    return webui_full_src()


def test_scroll_padding_dead_decls_retired():
    src = _src()
    # 两处死档清零：≤760 合并块头部固定档、541-760 带内注记档
    # （同带内三段式实效档按源码序覆盖，固定档任何视口不可达）
    assert "html{scroll-padding-top:calc(var(--hdh,76px) + 34px)}" not in src, \
        "≤760 块头 hdh+34 死档复活（被同带三段式实效档覆盖）"
    assert "scroll-padding-top:calc(var(--hdh,76px) + 40px)" not in src, \
        "541-760 带内 hdh+40 注记档复活（同带三段式实效档覆盖）"
    # calc 形态声明收敛 4 处：≤900 块与 761+ 块同串 hdh54+34、≤760
    # 块与 ≤540 块三段式（同值补档声明族计数钉，新档须连带清点；
    # 备案：≤900 hdh54+34 疑似全带被后置档接替的同族潜在死档，
    # Soldier Minor-2 在案，删除须先 live 复测 761-900 带 computed）
    assert src.count("scroll-padding-top:calc(") == 4, \
        "scroll-padding calc 声明数漂移：新补偿档须复核同值补档族"
    # 三段式实效档在位（≤760 与 ≤540 两带，含筛选条高项，JS 失效
    # 0px 兜底回落）
    assert src.count(
        "scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh)"
        " + var(--tabsh,0px) + 4px)") == 2, \
        "≤760/≤540 两带三段式实效补偿档缺失"


# ---- merged from tests/test_v225_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    return webui_full_src()


def test_ssub_wrap_gate_covers_761_900():
    """W1：换行放行媒体门覆盖 761-900 带。旧 ≤760 门是 391-509 修复
    上提时的同病灶残余带（768 实测 sw143/cw138 截断「用时 Ns」尾段）；
    基类 nowrap+ellipsis 在 >900 保持（宽屏单行形制不回退）。"""
    src = _page()
    assert "@media(max-width:900px){.stat .ssub{white-space:normal}}" in src
    assert "@media(max-width:760px){.stat .ssub{white-space:normal}}" not in src
    # 基类形制仍在（省略号语义 >900 档有效）
    assert ".stat .ssub{font-size:11px" in src
    assert "white-space:nowrap" in src.split(".stat .ssub{")[1][:200]


def test_kline_doji_min_body_height():
    """W2：doji 桶（开=收）实体高下限 3px——1.5px 短横成排后与达标
    红虚线同色同形，远看是第二条阈值线。空心/实心两分支同下限。"""
    src = _page()
    assert src.count("Math.max(3,yB-yT)") == 2, src.count("Math.max(3,yB-yT)")
    assert "Math.max(1.5,yB-yT)" not in src
