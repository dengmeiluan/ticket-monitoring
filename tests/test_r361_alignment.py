# -*- coding: utf-8 -*-
"""r361 icon/copy collision + alignment guards.

Locks the 2026-10-22 audit fixes: the cross-day +1 marker must stay inside
its fixed column, probe fields must be content-sized with the channel picker
on the card's right edge, chart value tags need their own top band, and
compact icon rows keep explicit gaps.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def test_time_cell_reserves_room_for_cross_day_marker():
    # 44+8+44+15 + 3*3 = 120px inside a 122px column; +1 cannot cross
    # the 6px grid gutter into the status badges.
    assert STYLE.count("minmax(122px,.95fr)") == 2
    assert "#searchview .srx-times{grid-template-columns:44px 8px 44px 15px;column-gap:3px}" in STYLE
    assert "#searchview .srx-times .xday{justify-self:start}" in STYLE


def test_probe_fields_are_content_sized_and_picker_aligns_right():
    assert ('grid-template-columns:196px 14px 196px 142px auto auto minmax(0,1fr)'
            in STYLE)
    assert 'grid-template-areas:"from arr to date go exit plat"' in STYLE
    # Both area rows must name all six columns or CSS drops the declaration.
    assert ('grid-template-areas:"from arr to date go exit" '
            '"plat plat plat plat plat plat"') in STYLE
    assert "justify-content:flex-end" in STYLE
    # The 探针会话 action no longer competes for auto margins.
    assert 'style="height:26px;padding:0 8px;font-size:11px">探针会话' in SRC
    assert SRC.count("height:26px;padding:0 8px;font-size:11px") == 1


def test_chart_extreme_tags_have_a_dedicated_top_band():
    assert "const L=58,R=18,T=W>=560?36:18,B=40" in SRC
    assert "let focusTarget=null;" in SRC
    assert "const placeTop=(text,x,color,align)=>" in SRC
    assert "focusTarget={v:tgt,color:cssv('--red')||'#c22a2e'}" in SRC


def test_icon_rows_keep_legible_tiles_and_explicit_gaps():
    assert ".monwatch-ch .bic{--bic:17px;border-radius:4px}" in STYLE
    assert ".monwatch-chs{display:inline-flex;align-items:center;gap:4px;margin-right:4px}" in STYLE
    assert ".ws-ch{min-height:24px;padding:0 8px 0 7px" in STYLE
    assert ".ws-chanstrip .ws-ch .bic{--bic:15px}" in STYLE


def test_filter_summary_is_flat_and_airline_query_is_compact():
    assert "#attrchips .attrq{width:92px}" in STYLE
    assert "#attrchips .ag-wide{grid-column:1/-1;\n grid-template-columns:var(--flt-lab) 92px minmax(0,1fr)}" in STYLE
    assert "border:1px solid transparent;border-radius:var(--r3);" in STYLE
    assert "#searchview .srx-abar .srx-chip .x{font-size:11px" in STYLE


def test_price_band_is_reversible_and_click_keeps_window():
    assert "function srxCalKey(){return (SRX.pair||'')+'|'+(SRX.bandAnchor||SRX.date||'')}" in SRC
    assert "function srxBandShift(n){" in SRC
    assert "function srxBandReset(){SRX.bandAnchor='';srxRenderBand()}" in SRC
    # Day click keeps the current window anchor instead of re-anchoring.
    assert "SRX.bandAnchor=(j&&j.anchor)||SRX.bandAnchor||SRX.date;" in SRC
    assert "const anchor=SRX.bandAnchor||SRX.date;" in SRC
    assert "const key=srxCalKey();" in SRC
    assert 'onclick="srxBandShift(-14)"' in SRC
    assert 'onclick="srxBandShift(14)"' in SRC
    assert 'id="srxBandReset" onclick="srxBandReset()" hidden' in SRC
    assert "回到所选日" in SRC
