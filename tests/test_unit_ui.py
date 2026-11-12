# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r364_ui_quality.py
- tests/test_v15277_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import re


# ---- merged from tests/test_r364_ui_quality.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
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


# ---- merged from tests/test_v15277_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_all_date_row_open_never_pins_global_date():
    s = _ui()
    fn = s[s.index("function srxOpenDetail(k){"):s.index("function srxCloseDetail()")]
    assert "SRX.date=_f0.date" not in fn
    assert "SRX.date=_f0.date" not in s


def test_list_and_matrix_show_date_in_all_date_mode():
    s = _ui()
    assert "!SRX.date&&f.date?'<span style=\"color:var(--mut);font-variant-numeric:tabular-nums\"" in s
    assert "!SRX.date&&_g0.date?'<span style=\"color:var(--mut)\"> · '" in s


def test_matrix_groups_before_slice_and_discloses_truncation():
    s = _ui()
    fn = s[s.index("function srxMatrixHTML(){"):s.index("/* ---------- mirror ---------- */")]
    assert "srxGroup(rows)" in fn
    assert "srxGroup(rows.slice(0,SRX.limit))" not in fn
    assert "完整同班组" in fn
    assert "selGrp" in fn


def test_stale_is_six_hour_not_any_nonzero_age():
    s = _ui()
    assert "function srxIsStale(f){return !!f.isStale||(f.rowId==null&&Number(f.stale)>6)}" in s


def test_cabin_filter_and_watch_use_one_classifier():
    s = _ui()
    assert "function srxWatchCabin(f){const c=srxCabinClass(f)" in s
    # 检索与明细同一空值律：缺舱位维度的行不被指定舱位档静默滤除
    assert "const _cabMissing=!cab||cab==='未知'||String(cab).indexOf('票种:')===0;" in s
    assert "if(F.cabin==='eco'&&!_cabMissing&&!(cab==='经济'||cab==='超级经济'))return false;" in s
    assert "if(F.cabin==='biz'&&!_cabMissing&&!(cab==='公务'||cab==='头等'))return false;" in s
    assert "if(FLT.cabins.size&&cabinOf(f)&&!FLT.cabins.has(cabinOf(f)))return false;" in s


def test_row_watch_defaults_to_source_channel():
    s = _ui()
    assert "channels:(f.platKey?[f.platKey]:SRX_PLAT_KEYS.slice(0,1))" in s
    assert "不替用户静默订阅五渠道" in s
    fn = s[s.index("async function srxWatchToggleDo(f,old){"):s.index("function srxWatchToggleByKey(fk,cab)")]
    assert "channels:SRX_PLAT_KEYS.slice()" not in fn


def test_expired_watch_never_claims_hit():
    s = _ui()
    assert "function srxWatchExpired(w)" in s
    assert "if(srxWatchExpired(w))return{state:'wait',text:'航班日期已过 · 不判达标'" in s
    assert "if(srxWatchExpired(w))return {cls:'out',text:'已过期'};" in s
    assert "const expired=srxWatchExpired(w);" in s
    assert "expired?'航班日期已过 · 不判达标'" in s


def test_config_quote_honors_6h_and_paused_state():
    s = _ui()
    fn = s[s.index("function cfgWatchQuote(w){"):s.index("function cfgWatchTargetState(w,q){")]
    assert "stale=!(S&&S.demo)&&ageH!=null&&ageH>6" in fn
    fn2 = s[s.index("function cfgWatchTargetState(w,q){"):s.index("function cfgWatchFiltered(){")]
    assert "if(q.stale)return 'wait';" in fn2
    assert "srxWatchExpired(w)||w.active===false||w.inScope===false" in fn2


def test_config_watch_draft_guard_and_cross_day_7():
    s = _ui()
    assert "function cwDiscardGuard(ok){" in s
    assert "CFG_WATCH.dirty=true;" in s
    assert "typeof CFG_WATCH!=='undefined'&&!!CFG_WATCH.dirty" in s
    assert '<option value="+7天">+7 天</option>' in s
    assert "航班日期已过（'+date+'），不能新增关注" in s


def test_overlay_top_layer_and_z_order():
    s = _ui()
    assert "#searchview #srxModalmask{z-index:139}" in s
    assert "#searchview .srx-modal{z-index:140}" in s
    assert "#toasts{z-index:300}" in s   # toast 必须高于登录/推送弹层（220/221）
    assert "if(srxTopLayer()==='detail')srxCloseDetail();" in s
    assert "if(srxTopLayer()==='gallery')srxCloseGallery();" in s
    assert "function srxLockBody()" in s and "function srxUnlockBody()" in s
    assert "el.setAttribute('inert','')" in s


def test_detail_tabs_are_a_real_tablist():
    s = _ui()
    assert 'aria-controls="srxDTabPanel" role="tab" tabindex=' in s
    assert 'id="srxDTabPanel" role="tabpanel" aria-labelledby="srxTab_' in s
    assert "ev.key==='ArrowRight'?i+1:i-1" in s


def test_city_exact_text_is_a_query_and_home_end_work():
    s = _ui()
    assert "const q=String((inp.dataset&&inp.dataset.code)?'':(inp.value||'')).trim().toLowerCase();" in s
    assert "if(ev.key==='ArrowDown'||ev.key==='ArrowUp'||ev.key==='Home'||ev.key==='End')" in s
    assert 'class="srx-cityopt' in s and 'tabindex="-1" class="srx-cityopt' in s
    assert "if(ev.target&&ev.target.closest&&ev.target.closest('.cp-city')&&ev.key!=='Tab')cityPanelKey(ev);" in s


def test_demo_health_and_gallery_are_labeled_demo():
    s = _ui()
    assert "DEMO · 合成演示 raw" in s
    assert "DEMO · 合成演示行" in s
    assert "DEMO · 合成关注（非真实报价）" in s
    assert "演示站为静态数据，不发起真实外网探针" in s


def test_pages_root_redirect_and_readme_truth():
    idx = os.path.join(ROOT, "docs", "index.html")
    assert os.path.exists(idx)
    with open(idx, encoding="utf-8") as f:
        h = f.read()
    assert 'http-equiv="refresh" content="0; url=./site/"' in h
    for name in ("README.md", "README_EN.md"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            t = f.read()
        assert "127–250" in t
        assert "60–94" not in t and "58–88" not in t and "58–92" not in t
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        cn = f.read()
    with open(os.path.join(ROOT, "README_EN.md"), encoding="utf-8") as f:
        en = f.read()
    assert "在线演示为静态站，探针入口禁用" in cn
    assert "static site: the probe entry is disabled" in en
    assert "single-instance" in en and "systemd" in en
    assert "SHA256SUMS.txt" in en
