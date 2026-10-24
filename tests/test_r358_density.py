# -*- coding: utf-8 -*-
"""r358 density pass: quiet tab/toolbar surfaces, collapsed probe, config fields,
watch chart tag collision, raw-row transient failure."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def test_tab_and_toolbar_groups_share_one_surface():
    for needle in (
        "#montabs .mtab{border-color:transparent;background:transparent",
        "#montabs .mtab.on{background:var(--blue)",
        "#searchview .srx-hero-act{background:color-mix",
        "#searchview .srx-hero-act .srx-btn{border-color:transparent;background:transparent",
        "#searchview .srx-hero-act .srx-btn:last-child{grid-column:1/-1}",
        "#searchview .srx-band .srx-day{background:color-mix",
    ):
        assert needle in STYLE, needle


def test_probe_collapses_to_one_line_before_expand():
    for needle in (
        "#searchview .srx-probe:not(.open) .srx-probehead>span",
        "#searchview .srx-probe:not(.open) .srx-probehead>em{display:none}",
        "#searchview .srx-probe:not(.open) .srx-probehead{margin-bottom:0}",
    ):
        assert needle in STYLE, needle


def test_config_cells_are_tinted_not_boxed_and_ua_is_not_blank():
    for needle in (
        "#cfgview .glcell{border-color:transparent;background:color-mix",
        "#cfgview .glcell input::placeholder",
        "#cfgglobals .glgrid .glcell:only-child{display:grid",
        "#cfgglobals .glgrid .glcell:only-child>.glab{grid-column:1;grid-row:1",
        ">div:not(.glab):not(.gsub){grid-column:2;grid-row:1}",
    ):
        assert needle in STYLE, needle
    assert "glcell=(lab,id,onch,val,sub,type,unit,ph)" in SRC
    assert "+(ph?' placeholder=\"'+esc(ph)+'\"':'')" in SRC
    assert "'text',null,'留空 = 内置桌面 UA'" in SRC
    assert "'text',null,'127.0.0.1'" in SRC
    assert "'text',null,'http://127.0.0.1:7897'" in SRC


def test_detail_header_keeps_close_at_top_right():
    for needle in (
        "#searchview .srx-dhead>.srx-dtop{flex:1 1 100%}",
        "#searchview .srx-dhead>.srx-dtop .srx-dtitle{flex:1 1 auto}",
        "#searchview .srx-dhead>.srx-dtop .srx-close{margin-left:2px}",
        "#searchview .srx-dhead>.srx-dacts{flex:1 1 100%;justify-content:flex-end}",
    ):
        assert needle in STYLE, needle


def test_watch_chart_tags_avoid_each_other():
    assert "function wsTagRect(ctx,text,x,y,align){" in SRC
    assert "function wsBoxHit(a,b){" in SRC
    assert "const tagBoxes=[];" in SRC
    # r361: extreme/price tags live in a 36px top band, outside the plot.
    assert "const L=58,R=18,T=W>=560?36:18,B=40" in SRC
    assert "let focusTarget=null;" in SRC
    chart = SRC[SRC.index("const placeTop=(text,x,color,align)=>{"):
                SRC.index("if(focusTarget)placeTop")]
    for needle in ("wsTagRect(ctx,text,x,16,align)", "wsBoxHit(t,box)",
                   "let nx=hit.x-box.w-6;", "if(nx<2)nx=hit.x+hit.w+6;",
                   "if(Math.abs(nx-box.x)<.5)break;"):
        assert needle in chart, needle
    assert ("if(focusTarget)placeTop('目标 '+wsMoney(focusTarget.v),"
            "W-R-2,focusTarget.color,'right');") in SRC
    assert "placeTop('低 '+wsMoney(mn.v),X(mn.t),s.color,'center');" in SRC
    assert "placeTop('高 '+wsMoney(mx.v),X(mx.t),s.color,'center');" in SRC


def test_detail_fields_say_loading_before_raw_arrives():
    assert "const pending=!raw&&f&&f.rowId!=null" in SRC
    assert "正在回放原始行，字段状态稍后更新" in SRC
    assert "pending&&st[0]==='miss'?['wait','读取中']:st" in SRC
    assert "#searchview .srx-fst.none,#searchview .srx-fst.wait{color:var(--mut)}" in STYLE


def test_price_band_signals_horizontal_scroll_at_768():
    assert "function srxBandHint(){" in SRC
    assert "box.addEventListener('scroll',srxBandHint,{passive:true})" in SRC
    assert "requestAnimationFrame(srxBandHint)" in SRC
    assert "#searchview .srx-band-days.xhint:not(.xend)" in STYLE
    assert "#searchview .srx-band-days.xend{-webkit-mask-image:none" in STYLE


def test_mobile_source_cards_signal_horizontal_scroll():
    assert "function srxBriefHint(){" in SRC
    assert "el.addEventListener('scroll',srxBriefHint,{passive:true})" in SRC
    assert "if(which==='overview')setTimeout(()=>{srxBriefHint();srxBandHint();},60)" in SRC
    assert "#searchview .srx-brief.xhint:not(.xend)" in STYLE


def test_demo_health_log_replays_the_clicked_round_and_channel():
    seg = SRC[SRC.index('elif self.path.startswith("/api/logtail"):'):
              SRC.index('elif self.path.startswith("/api/srx/links"):')]
    assert "2026-09-09 14:00" not in seg
    assert '_dt.strptime(_ts, "%Y-%m-%d %H:%M")' in seg
    assert '_p = q.get("plat", [""])[0] or "qunar"' in seg
    assert '_ts = q.get("ts", [""])[0] or _dt.now()' in seg
    assert '"plat": _p, "ts": _ts, "demo": True' in seg


def test_raw_row_failure_is_short_lived_and_explained():
    assert "Date.now()-(_c._soft||0)<5000" in SRC
    assert "if(j&&j.ok){SRX_RAW[k]=j;return j}" in SRC
    assert "该行已被新一轮采集替换" in SRC
    assert "!_rc.ok&&Date.now()-(_rc._soft||0)>5000" in SRC
    assert "SRX_RAW[k]=j;return j})\n  .catch" not in SRC
