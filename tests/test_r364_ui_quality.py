# -*- coding: utf-8 -*-
"""r364 UI quality: first-paint watch hydration, progressive trend loading,
wide-screen width continuity, dense-search legibility and icon/text safety."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLES = re.findall(r"<style[^>]*>(.*?)</style>", SRC, re.S)
R364 = STYLES[1]


def _between(start, end):
    return SRC[SRC.index(start):SRC.index(end, SRC.index(start))]


def test_config_watch_does_not_cache_empty_before_config_ready():
    fn = _between("async function loadCfgWatch(force){", "/* 未保存草稿守卫")
    assert "if(!CFG){" in fn and "if(!user){" in fn
    assert "CFG_WATCH.loadedAt=0" in fn
    assert "CFG_WATCH.retryT=setTimeout" in fn
    assert "CFG_WATCH.queued" in fn
    # loadCfg 预热前必须破缓存，否则首屏 0 条会挂到手动刷新
    load_cfg = _between("async function loadCfg(){", "/* ===== r351")
    assert "try{CFG_WATCH.loadedAt=0}catch(e){}" in load_cfg


def test_watch_trend_has_hard_timeout_and_progress():
    assert "function wsTrendLoading()" in SRC
    assert "loading…" in SRC or "读取真实采集点" in SRC
    assert "AbortController" in SRC
    assert "setTimeout(()=>{try{ctl.abort()}catch(e){}},12000)" in SRC
    assert "WS._trendTotal" in SRC and "WS._trendDone" in SRC


def test_wide_layout_continuity_not_capped_at_narrow_console():
    assert ".wrap{max-width:min(1716px,max(1180px,92vw));" in R364
    assert ".wrap{max-width:1220px" not in R364
    assert "@media(min-width:1919px){\n #hdcard{margin-left:0;margin-right:0}" in R364


def test_search_first_paint_actions_are_content_sized_and_not_clipped():
    assert '#searchview .srx-more-btn{display:inline-flex!important' in R364
    assert '#searchview .srx-hero-act:not(.open) .srx-btn[data-sec]{display:none!important}' in R364
    assert "grid-template-columns:repeat(2,minmax(0,1fr))!important" in R364
    assert 'data-sec onclick="srxOpenGallery()"' in SRC
    assert "srx-more-btn" in SRC


def test_dense_search_does_not_squeeze_airline_name_or_field_meter():
    assert "#searchview .srx-fl .sub .srx-airline em{display:none}" in R364
    assert "#searchview .srx-fl .srx-fieldmeter{display:none}" in R364
    assert "#searchview .srx-times .arr{text-align:left}" in SRC
    assert "#searchview .srx-times{grid-template-columns:44px 8px 44px 15px" in SRC


def test_table_and_health_regressions_locked():
    assert "#ftable th:hover{background:var(--r-surface-3)!important}" in R364
    assert "#ftable tr.qual td.price{color:var(--ok-txt)!important}" in R364
    assert "#tabs span:hover:not(.on){background:var(--r-surface)!important" in R364
    assert "#healthcard .hcells{padding:11px 0;margin:-9px 0}" in R364
    assert "@media(pointer:coarse) and (min-width:901px)" in R364


def test_aircraft_icon_enters_config_candidate_cards():
    fn = SRC[SRC.index("function cfgWatchCandidateHTML"):]
    fn = fn[:fn.index("</button>")]
    assert "srxPlaneIcon(f.plane||f.planeSize)" in fn


def test_airline_icon_enters_overview_kpi_flight_line():
    assert "${srxAirIcon(brief.name)||''}" in SRC
    assert "srxPlaneIcon(brief.plane||brief.planeSize)" in SRC


def test_search_render_avoids_megabyte_inline_logo_html():
    assert "function srxLogoURL(im){" in SRC
    assert "URL.createObjectURL(new Blob([arr],{type:mime}))" in SRC
    assert "src=\"'+srxLogoURL(im)+'\"" in SRC
    assert "id=\"srxRows\"" in SRC


def test_search_poll_uses_etag_304():
    assert "let LOADN=false,LASTETAG='',STATE_ERR='';" in SRC
    assert "If-None-Match" in SRC and "if(r.status===304){health();pulse();return;}" in SRC
    assert "const _et=r.headers.get('ETag');if(_et)LASTETAG=_et;" in SRC


def test_gpu_expensive_filters_removed_from_sticky_header_and_plane_icons():
    assert "backdrop-filter:none!important" in R364
    assert ".bic-plane{filter:none!important}" in SRC
    assert "html[data-theme=\"light\"] .bic-plane{filter:none!important" in SRC


def test_watch_sync_star_icon_rewrite_is_state_guarded():
    fn = _between("function srxWatchSync(){", "async function srxWatchLoad")
    assert "if(btn.dataset.wst!==wst){" in fn


def test_mobile_first_page_is_capped_and_load_more_stays_available():
    assert "const SRX_MOBILE_PAGE=24;" in SRC
    assert "const SRX_PAGE=50;" in SRC
    assert ("function srxRowCap(){return innerWidth<=1100&&SRX.limit===SRX_PAGE"
            "?SRX_MOBILE_PAGE:SRX.limit}") in SRC
    assert "const shown=srxShownRows(rows);" in SRC
    assert "const base=srxRowCap();" in SRC
    fn = _between("function srxMoreRows(){", "function srxClearFilters")
    assert "SRX.limit=(SRX.limit===SRX_PAGE?SRX_MOBILE_PAGE:SRX.limit)+SRX_MOBILE_PAGE" in fn
    assert "else SRX.limit+=SRX_PAGE;" in fn
    assert "srxRenderRows();" in fn


def test_empty_filter_render_does_not_refilter_or_rebuild_group_index():
    assert "function srxRowsHTML(rows,all){" in SRC
    assert "const freshAt=all.filter(" in SRC
    assert "if(rows.length)srxBuildGroupIdx();" in SRC
    assert "srxRowsHTML(rows,all)" in SRC
    fn = _between("function srxAvailChans(){", "function srxMirrorHTML(){")
    assert "const all=srxMirrorScope(),cnt={},real={};" in fn
    assert "return {chans,cnt,all};" in fn


def test_search_rows_scroll_with_page_and_no_hover_paint_transition():
    for line in SRC.splitlines():
        if "#searchview .srx-mtabs{" in line or "#searchview .srx-mobilebar{" in line:
            assert "position:sticky" not in line, line
    assert ("#searchview .srx-mirror{max-height:calc(100vh - var(--hdh,54px) - 18px);"
            "overflow:auto}") in SRC
    assert "transition:background .12s,box-shadow .12s" not in SRC
    # 唯一允许的页面级冻结仍是控制台顶栏
    assert "position:sticky;top:0;z-index:50;" in SRC
