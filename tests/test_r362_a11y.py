# -*- coding: utf-8 -*-
"""r362 可访问性/窄屏四案源码钉（行为探针已在本机 8765 实测）：

A1 检索层模态/画廊/详情打开时，背景全局快捷键（1/2/3-7/S///R）
   仍可夺焦切页——只挡了 pvMask。修法：全局 keydown 在 pvMask 后
   追加 srxTopLayer() 守卫（详情内按 1 不再跳监控，焦点留在详情）。
A2 详情 tablist 键盘 Home/End 的 `[data-dtab]` 广播选择器把动作钮
   「同班 N 源」也算作 tab，End 焦点落到 tablist 外。修法：tab
   检测/遍历/回焦全部收窄到 `.srx-dtabs [data-dtab]`。
A3 M 键切矩阵后整表重渲，焦点落 BODY，J/K 接力断档。修法：切后
   回焦当前视图选中行/矩阵选中价格，空态回视图钮。
A4 320 概览 48 轮脉冲：4px 柱 + 3px 缝内容宽 333px 撑破 320 视口，
   触控仅 6px；详情航班格 .tj 热区纵向 -11px 压住「改期」胶囊
   下沿（交叠 27×20px）。修法：≤560 横滚 + 24px 触控格/8px 视觉柱
   且默认停最新轮；.tg 只向上扩热区 + z-index 抬高，.tj 只向下扩，
   航线行下移 10px，两热区相切不相交。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r362_a11y.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def test_top_layer_shortcut_guard():
    s = _src()
    i = s.index("document.addEventListener('keydown',e=>{\n /* Ctrl/Cmd+S")
    tail = s[i:i + 900]
    assert "typeof srxTopLayer==='function'&&srxTopLayer()" in tail
    assert tail.index("srxTopLayer()") < tail.index("e.key==='1'")


def test_detail_tabs_scoped_to_tablist():
    s = _src()
    i = s.index("$('srxDetail').addEventListener('keydown'")
    block = s[i:i + 900]
    assert "ev.target.closest('.srx-dtabs [data-dtab]')" in block
    assert "querySelectorAll('.srx-dtabs [data-dtab]')" in block
    assert "querySelector('.srx-dtabs [data-dtab=\"'+key+'\"]')" in block
    # 数据区动作钮仍可点击切到同班对照，只是不再参与键盘 tab 环
    assert "const tab=ev.target.closest('[data-dtab]');if(tab){" in s


def test_matrix_toggle_restores_focus():
    s = _src()
    i = s.index("if(ev.key==='m'||ev.key==='M')")
    block = s[i:i + 500]
    assert "srxToggleView()" in block
    assert "#srxRows .srx-row.sel" in block
    assert "#srxRows .mcell.sel" in block
    assert "$('srxViewBtn')" in block


def test_pulse_mobile_scroll_touch_cells():
    s = _src()
    i = s.index('@media(max-width:560px){\n  .pulsewrap{justify-content:flex-start')
    block = s[i:i + 520]
    assert 'overflow-x:auto' in block
    assert '.pbar{flex:0 0 24px;min-width:24px;max-width:none;align-items:center}' in block
    assert '.pbar .seg,.pbar .cap,.pbar.zero i{width:8px;max-width:8px}' in block
    assert '.pulsewrap .pbar::after{inset:0}' in block
    # 默认滚到最新轮，回看旧轮不被刷新抢位
    j = s.index("const _pw=$('pulsebars');")
    jb = s[j:j + 420]
    assert "_pw.scrollWidth>_pw.clientWidth+1" in jb
    assert "dataset.scrolled" in jb
    assert "_pw.scrollLeft=_pw.scrollWidth" in jb


def test_tg_tj_hit_areas_do_not_overlap():
    s = _src()
    assert '.tg{z-index:2}' in s
    assert '#ftable tbody tr[data-k]>td:nth-child(4) .stl.nw:has(.tj){display:block;margin-top:10px}' in s
    # tj 只向下扩 14px（触控 32px），不再向上压胶囊；tg 下沿热区
    # 与航线行上沿恰好相切（实测视觉间距 9px = tg 下扩 9px）
    assert '.tj::after{inset:0 0 -14px}' in s


def test_mobile_probe_submit_moves_above_channels():
    s = _src()
    i = s.index('grid-template-areas:"from from" "to to" "date go" "plat plat" "exit exit"')
    block = s[i:i + 320]
    assert '.srx-datefield{grid-area:date;max-width:none}' in block
    assert 'min-width:96px' in block
    # 城市字段仍整行：旧 ≤460 单列把提交钮排到渠道片之后（320 首屏不可见）
    assert 'grid-template-areas:"from" "to" "date" "plat" "go" "exit"' not in s


def test_watch_list_preserves_row_focus_on_rebuild():
    s = _src()
    i = s.index('function wsRenderList(){')
    block = s[i:i + 1900]
    assert "closest('#wsList [data-wsfocus]')" in block
    assert "closest('#wsList [data-wsexpand]')" in block
    j = block.index("box.innerHTML=list.map(wsRowHTML).join('');")
    tail = block[j:j + 450]
    assert "data-wsexpand=" in tail and "data-wsfocus=" in tail
    assert "focus({preventScroll:true})" in tail
