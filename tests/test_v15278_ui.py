# -*- coding: utf-8 -*-
"""1.5.278: mirror all-date labels, CSV/JSON status, maintenance badge,
demo probe mode, filter orphan, studio focus, city region order, CSS."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def test_mirror_rows_carry_date_in_all_date_mode():
    s = _src()
    fn = s[s.index("function srxMirrorListHTML(ch,rows){"):s.index("function srxMirrorDetailHTML")]
    assert "!SRX.date&&f.date?' · '+he(f.date.slice(5)):''" in fn


def test_csv_and_json_label_only_observe_and_calendar_stale():
    s = _src()
    fn = s[s.index("async function srxExport(){"):s.index("async function srxExportEvidence()")]
    assert "'实时 · 仅观察'" in fn
    assert "'日历/薄行'+(srxIsStale(f)?' · 补位 '+f.stale+'h':''" in fn
    assert "f.fetchedAt||(srxIsStale(f)?'补位 '+f.stale+'h':'')" in fn
    ev = s[s.index("async function srxExportEvidence(){"):s.index("function srxPayload()")]
    assert "staleH:srxIsStale(f)?Number(f.stale||0):0" in ev
    assert "onlyObserve:!Number(f.th)&&!f.probe" in ev


def test_health_maintenance_never_green_100():
    s = _src()
    assert "const maintN=st.maint||0;" in s
    assert "maintN?(shownRate>=80?'mid':'bad')" in s
    assert ")+(maintN?' · 维护':'')" in s


def test_demo_probe_mode_and_matrix_orphan_close():
    s = _src()
    assert "const pm=$('srxProbeMode');if(pm)pm.textContent=SRX.probe?" in s
    assert "(demo?'DEMO · 合成':'监控数据')" in s
    fn = s[s.index("function srxRenderRows(){"):s.index("function srxMatrixHTML()")]
    assert "if(SRX.sel&&!rows.some(f=>srxKey(f)===SRX.sel))" in fn
    assert "srxUnlockBody()" in fn


def test_studio_actions_restore_focus():
    s = _src()
    assert "document.querySelector('[data-wstoggle=\"'+w.id+'\"]')" in s
    assert "document.querySelector('[data-wsnotify=\"'+w.id+'\"]')" in s
    assert "document.querySelector('[data-wsact=\"add\"]')" in s


def test_city_region_order_and_config_regions():
    s = _src()
    assert "const RO={'国内':0,'日韩':1,'东南亚':2" in s
    assert "return (ro(a)-ro(b))||sc(a)-sc(b)" in s
    assert "'日韩':2,'东南亚':2,'南亚':2,'中东':2,'亚洲':2" in s


def test_calendar_row_key_includes_price_to_avoid_collision():
    import webui
    a = {"isCal": True, "from": "SHA", "to": "SIN", "platKey": "ctrip",
         "date": "2026-11-16", "rawIdx": None, "price": 717}
    b = dict(a, price=818)
    assert webui._srx_row_key(a) != webui._srx_row_key(b)
    assert webui._srx_row_key(a).startswith("c|SHA|SIN|ctrip|2026-11-16|")


def test_trusted_icons_are_direct_img_bic():
    src = _src()
    assert "<img class=\"'+c+'\" data-plat=\"" in src
    assert "<img class=\"bic bic-air '+(cls||'')+'\" data-code=\"" in src


def test_css_no_clipping_and_short_desktop_note():
    s = _src()
    assert ".cwf-cand .mt{grid-area:meta;font-size:10px;color:var(--mut);white-space:normal" in s
    assert "#searchview .srx-band-note{font-size:9px;margin-top:4px}" in s
    assert "#searchview .srx-band-note a{display:none}" in s
    assert "word-break:keep-all;overflow-wrap:normal" in s
    assert "#searchview .srx-dtabs{flex-wrap:wrap!important;overflow-x:visible!important;row-gap:3px}" in s
    assert ".mdgrp{display:flex;flex-wrap:wrap;white-space:normal}" in s
