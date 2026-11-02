# -*- coding: utf-8 -*-
"""v1.5.297: radar multi-date contract, flat entry, legend/focus fixes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_radar_and_flat_source_pins():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    for s in ("date_series", "spMonDeltaTxt", "no-target",
              ".mon-legend>span>b", ".ws-legend{display:grid",
              ".chband{grid-template-columns:148px",
              ".chlink{display:flex", "min-height:36px!important",
              "_wtab.textContent=ws.length?(' · '+ws.length)",
              "每线=一个出发日期", "spMonLow(sel,q,(low||{}).date)",
              "选中日 · 非最低", ".spmon-lowdate .seltag",
              "SPMON_RUN_LABEL", "spMonHistBody", "线尾圆点=最新采集价",
              "window.addEventListener('resize'", ".spmon-run{display:grid",
              ".hdiag-l span{white-space:nowrap}",
              ".hdiag-l span:not(:last-child)::after",
              "#searchview .srx-probefoot{grid-template-columns:1fr;gap:4px 0}",
              "<th>标记</th>", "'最低日 · 选中'", ".rad-pair{display:inline-flex",
              ".spmon-histempty{", "口径较上次变化", "含口径变化日",
              ".spmon-basiswarn", "(low&&low.date?low:null)",
              ".spmon.is-empty .spmon-main", ".spmon.is-empty #spMonCal{display:block}",
              "spMonTip", "c.addEventListener('pointermove',move)", "SPMON.geo=null",
              ".sprad-fld{", ".spmon-run .note{white-space:normal",
              "addEventListener('pointerdown',function(e)",
              "isLow?'<span class=\"lowtag\">最低日</span>'"):
        assert s in src, s


def test_config_has_one_flat_entry_surface():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert 'class="chband"' in src
    assert "border-bottom:1px solid var(--r-hair)!important" in src
    assert "#loginRows .lgslot{background:transparent" in src
