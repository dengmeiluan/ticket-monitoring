# -*- coding: utf-8 -*-
"""r275 WebUI 层（审计两案收编）：

P3-1 配置搜索漏收编两枚动作钮 + 0 命中档孤儿头：
  - 删除用户钮实际 DOM 是 .ucard>div>button.danger（模板多包一层），
    收编选择器 .ucard>.danger 恒不命中=死选择器；
  - 「➕ 添加航线」钮（.ucard 直接子级 btn2）不在任何收编清单；
  - 0 命中档：grouplab 恒 display=''——A-D 分区头/用户卡头/全局
    subsec 头残留成孤儿头（无命中字段却有结构头悬空）。
P3-2 #montabs tablist 纯性破缺：uchip（role=button，r253 加）晚于
tabAria 落地未回查——ARIA tablist 须纯 tab 子集；按 #tabs/#cfgnav
同律降 button 形态（aria-pressed 播报，功能无缺），roving tabIndex
随 tablist 形制一并退役（button 形态下全员可 Tab）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r275_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_WEBUI = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()


# ---- P3-1：配置搜索收编 ----

def test_p31_dead_danger_selector_retired():
    """死选择器 .ucard>.danger 禁复活（删除钮实际 DOM 多包一层 div，
    子代选择器恒不命中）。"""
    assert _WEBUI.count(".ucard>.danger") == 0, \
        "死选择器 .ucard>.danger 复活"


def test_p31_danger_selector_alive_both_sites():
    """删除钮收编改 .ucard button.danger（后代选择器）：清空复位清单
    与过滤清单两处在案。r281 容器壳收尾扫的 ROWS 口径合法新增第三处
    （动作件命中时宿主容器不得被误隐）——计数钉随合法新写点 +1。"""
    assert _WEBUI.count(".ucard button.danger") == 3, \
        "删除钮收编选择器应恰在 cfgSearchClear+cfgFilter+容器收尾扫三处"


def test_p31_add_route_btn_covered_both_sites():
    """「➕ 添加航线」钮收编：模板侧专类 + 两处清单按类收编（按钮
    实为 ucard 孙级——折叠包裹层内，子代选择器恒不命中与删除钮
    同族病；类与清单两段互锁，任一侧漂移即红）。"""
    assert 'class="btn2 addrbtn"' in _WEBUI, "添加航线钮缺专类"
    assert _WEBUI.count("#cfgview .addrbtn") == 2, \
        "添加航线钮收编应恰在 cfgSearchClear+cfgFilter 两处"


def test_p31_zero_hit_orphan_heads_hidden():
    """0 命中档孤儿头隐藏：结构头（分区/用户卡/静态卡头/全局
    subsec）按命中数显隐（n?'':'none'），搜索清空路径同清单复位
    （清空复位清单与过滤清单同步纪律）。"""
    assert _WEBUI.count("#cfgview .grouplab,#cfgview .uhead2,"
                        "#cfgview .uhead,#cfgview .subsec") == 2, \
        "孤儿头显隐联合选择器应恰在清空+过滤两处"


# ---- P3-2：#montabs 降 button 形态 ----

def test_p32_montabs_tablist_retired():
    """tablist 形制退役（禁复活）：#montabs 不再设 role=tablist，
    .mtab 不再挂 role=tab/tab↔tabpanel 关联/aria-selected（fltBtn 的
    button 语境 aria-controls 合法在案，不在此列）。"""
    assert "setAttribute('role','tablist')" not in _WEBUI, \
        "tablist 形制复活"
    assert "setAttribute('role','tab')" not in _WEBUI, \
        "tab 角色复活"
    assert "setAttribute('aria-controls','montab-'" not in _WEBUI, \
        "tab↔tabpanel 关联复活"
    assert "aria-selected" not in _WEBUI, "aria-selected 复活"


def test_p32_mtab_pressed_semantics_alive():
    """实效档在场：.mtab 走 aria-pressed 播报（#tabs 同律，mkact 已
    赋 role=button），面板可访问名回写保留。"""
    import re
    assert re.search(
        r"querySelectorAll\('\.mtab'\)\.forEach\(x=>\s*"
        r"x\.setAttribute\('aria-pressed'", _WEBUI), \
        ".mtab aria-pressed 回写缺席"
    assert "PNAME" in _WEBUI, "面板可访问名映射缺席"


def test_p32_roving_tabindex_retired():
    """roving tabIndex 随 tablist 形制退役（button 形态下全员可 Tab）：
    tabAria 的 .mtab 块状循环（roving 载体）不复活。"""
    assert "document.querySelectorAll('.mtab').forEach(x=>{" not in _WEBUI, \
        "tabAria .mtab 块状循环复活（roving tabIndex 载体）"
