# -*- coding: utf-8 -*-
"""1.5.277: all-date identity, cabin parity, matrix groups, overlay stack,
watch channel/expiry/stale, config draft guard, city keyboard, Pages root."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ui():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
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
        assert "60–94" in t
        assert "58–88" not in t and "58–92" not in t
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        cn = f.read()
    with open(os.path.join(ROOT, "README_EN.md"), encoding="utf-8") as f:
        en = f.read()
    assert "在线演示为静态站，探针入口禁用" in cn
    assert "static site: the probe entry is disabled" in en
    assert "single-instance" in en and "systemd" in en
    assert "SHA256SUMS.txt" in en
