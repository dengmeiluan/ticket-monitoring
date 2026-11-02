# -*- coding: utf-8 -*-
"""v1.5.298: one page plane for every large surface; login/entry read as rows."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLES = re.findall(r"<style[^>]*>(.*?)</style>", SRC, re.S)
STYLE = "\n".join(STYLES)


def test_flat_layer_is_last_and_covers_former_white_surfaces():
    flat = STYLE.index("/* ===== v298 flat surface language =====")
    for old in (
        "#montabs .mtab.on{background:var(--r-surface)!important",
        "#mainnav span.on{background:var(--r-surface)",
        "#cfgview .lgcard{",
        ".kpi.hit{background:var(--r-surface)!important}",
        ".ws-route{position:relative",
    ):
        assert STYLE.index(old) < flat, old
    for new in (
        "#hdcard{background:var(--r-canvas)!important",
        "#mainnav span.on{background:transparent!important;color:var(--r-blue)!important;\n box-shadow:inset 0 -2px 0 var(--r-blue)!important}",
        "#montabs .mtab.on{background:transparent!important;color:var(--r-blue)!important;\n box-shadow:inset 0 -2px 0 var(--r-blue)!important}",
        ".kpi.hit,.ws-kpi.hit{background:transparent!important;box-shadow:none!important;",
        "#montab-watch .ws-route{background:transparent!important;border:0!important;",
        "#montab-watch .ws-row{background:transparent!important;border:0!important;",
        "#tablecard .tw{background:transparent!important;border:0!important;",
        "#searchview .srx-listhead{background:transparent!important}",
        "#searchview .srx-mmore{background:transparent!important}",
        ".stat{background:transparent!important;border-top:1px solid var(--r-hair)!important}",
        # r1034：并排选项类控件（axis/mtab）的选中态已统一为「软蓝底 + 品牌蓝」，
        # 见 tests/test_flat_design_contract.py 的新契约；旧的「透明底」写法退役。
        "#searchview .srx-axis button.on{background:var(--r-blue-soft)!important;color:var(--r-blue)!important;",
        "#searchview .srx-mtab.on{background:var(--r-blue-soft)!important;color:var(--r-blue)!important;",
        "#cfgnav .cnav.on{background:transparent!important;color:var(--r-blue)!important;",
        "#cfgnav .cnav:hover{background:transparent!important;color:var(--r-blue)!important}",
        "#cfgview .cfgdeck{background:transparent!important;border:0!important;",
        "#cfgview .uhead2{background:transparent!important;border:0!important;",
        "#cfgview .grouplab{background:transparent!important;border:0!important;",
        "#cfgview #cfgWatch{background:transparent!important;border:0!important;",
        "#cfgview .cfgwatch-toolbar{background:transparent!important;border:0!important;",
        "#cfgview .cfgw-route.on{background:transparent!important;color:var(--r-blue)!important;",
        "#cfgview .cfgseg .chip.on{background:transparent!important;color:var(--r-blue)!important;",
        "#cfgview .rline{box-shadow:none!important;border-radius:0!important}",
        "#opscard .opsbtns>button:focus-visible,#opscard .opsbtns>button:first-child:focus-visible,",
        "#montab-watch .ws-seg{background:transparent!important;border:0!important;border-radius:0!important;",
        "#searchview .srx-mtabs,#searchview .srx-mirror .srx-mtabs{background:transparent!important;",
        ".ws-live{border-radius:0!important;background:transparent!important;border:0!important;",
        ".spmon-sum{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0;",
    ):
        assert new in STYLE, new
    assert 'id="spMonSum"' in SRC
    assert "覆盖 '+_nCh+'/'+_qCh+' 渠道" in SRC


def test_channel_links_lose_their_card_frame():
    for s in (
        ".chlink{background:transparent!important;border:0!important;border-radius:0!important;",
        "a.chlink:hover{background:transparent!important;border:0!important;color:var(--r-blue)!important}",
        ".chlink.off{background:transparent!important;border:0!important;",
        ".chband{grid-template-columns:148px minmax(0,1fr)!important",
    ):
        assert s in STYLE, s


def test_login_rows_are_single_column_table_rows_at_all_widths():
    """单列行 × 三列（名字|说明|操作），窄档折两行。

    实现从"按 grid-row 硬编码行号"改为 grid-template-areas：硬编码在
    飞猪那种多一段说明的渠道上会多占一行（实测行高 88 vs 109 参差），
    areas 让每一行自洽。意图不变——仍是单列行信息表、操作独立成列。
    """
    for s in (
        "#loginRows .lggrid{display:grid;grid-template-columns:1fr!important;gap:0!important}",
        # 名字列必须是**内容宽**（max-content），不能定宽：r708 用户实测
        # 「智行 App」在 170px 定宽下被 ellipsis 截成「智行 A…」。判据守
        # 的是三列结构与操作列定宽，不是那个具体像素值。
        "#loginRows .lgcard{display:grid;grid-template-columns:max-content minmax(0,1fr) 96px!important;",
        'grid-template-areas:"name info act"!important;',
        "#loginRows .lgcard>.lgname{grid-area:name}",
        "#loginRows .lgcard>.lgsection{grid-area:info;",
        "#loginRows .lgcard>.lgslots{grid-area:info;min-width:0}",
        "#loginRows .lgcard>.btn2,#loginRows .lgcard>.lgact{grid-area:act;",
        "#loginRows .lgcard:hover{background:transparent!important;box-shadow:none!important}",
    ):
        assert s in STYLE, s
    # 操作列定宽 + 右对齐：五行按钮右缘必须严格对齐（此前差 14px）
    assert "96px!important" in STYLE
    assert "justify-self:end" in STYLE


def test_controls_keep_boundaries_without_card_shadows():
    for s in (
        "button{box-shadow:none!important}",
        "button.warn{background:transparent!important;color:var(--r-ink-2)!important;",
        "#opscard .opsbtns>button:first-child{background:var(--r-blue)!important;",
        ".btn2{background:var(--r-surface-2)!important;color:var(--r-ink-2)!important;",
        ".ws-btn{background:var(--r-surface-2)!important;border:0!important;",
        "html[data-theme=\"dark\"] .btn2.primary,",
        "html[data-theme=\"dark\"] .ws-btn.primary,",
        "html[data-theme=\"dark\"] #opscard .opsbtns>button:first-child{color:#0b1220!important}",
    ):
        assert s in STYLE, s


def test_mobile_tabs_do_not_create_horizontal_overflow():
    assert "@media(max-width:390px){\n html #montabs{width:auto!important;margin:2px -12px 10px!important}" in STYLE
    assert "#montabs{margin:2px -12px 10px!important}" in STYLE
