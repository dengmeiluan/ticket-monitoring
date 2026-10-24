# -*- coding: utf-8 -*-
"""1.5.275 audit-wave pins: honesty, watch-form guards, HTTP cache, chart/a11y."""
import io
import os

import pytest

import webui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(webui.__file__, encoding="utf-8").read()


def test_http11_enables_conditional_requests():
    assert 'protocol_version = "HTTP/1.1"' in SRC
    assert 'self.send_header("Content-Length", "0")' in SRC


def test_probe_synthetic_never_claims_raw():
    assert '"raw": None if synthetic else raw_item,' in SRC
    assert "渠道 extra 为空时不得把解析值伪装成 raw" in SRC


def test_calendar_switch_closes_detail():
    seg = SRC[SRC.index("function srxCalPick"):]
    seg = seg[:seg.index("function srxMoreRows")]
    assert "srxDetail" in seg and "srxDmask" in seg
    assert "d.classList.remove('open')" in seg


def test_filters_rerender_mirror():
    assert SRC.count("srxRenderRows();srxRenderMirror()") >= 3
    assert "function srxApplyFilterChange(" in SRC
    seg = SRC[SRC.index("function srxApplyFilterChange("):]
    assert "srxRenderMirror()" in seg[:300]
    sf = SRC[SRC.index("function srxSetFilter"):]
    assert "srxApplyFilterChange()" in sf[:300]


def test_watch_add_rejects_duplicate_instead_of_overwrite():
    seg = SRC[SRC.index("def _watch_apply"):]
    seg = seg[:2500]
    assert "该航班已在关注清单" in seg
    assert 'items.insert(0, entry)' in seg


def test_watch_edit_allows_identity_and_explains():
    # r365：编辑态身份字段可编（航线/日期/航班/时刻/舱位/经停），服务端
    # 重建 flightKey/id；不再要求“移除后重加”。
    assert "function cfgWatchIdentityEditable()" in SRC
    assert "cfgWatchLockIdentity" not in SRC
    assert "可改航线/日期/航班/舱位/渠道/目标" in SRC
    assert "#cwCands button" in SRC and "#cwKnown" in SRC
    assert "trans:(($('cwTrans')||{}).value||'').trim(),cross:" in SRC


def test_watch_time_and_code_validation():
    assert "航班号格式应如 MU541 或 MU541/MU542" in SRC
    assert "起降时刻需为 00:00–23:59" in SRC
    assert r"^[A-Z0-9]{2}\d{1,4}(?:/[A-Z0-9]{2}\d{1,4})*$" in SRC


def test_watch_entry_normalizes_zero_target_and_rejects_bad_fields():
    base = {"from": "SHA", "to": "BKK", "date": "2026-11-16",
            "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
            "channels": ["qunar"], "target": 0}
    entry = webui._watch_entry(dict(base))
    assert entry["target"] is None
    with pytest.raises(ValueError):
        webui._watch_entry(dict(base, code="NOT A FLIGHT"))
    with pytest.raises(ValueError):
        webui._watch_entry(dict(base, depTime="25:99"))


def test_overview_best_trend_and_per_card_studio():
    assert "function jumpUserBest(i,date)" in SRC
    assert "jumpUserBest(${i},'${(xd&&xd.date)||(xt&&xt.date)||''}')" in SRC
    assert "function monWatchStudio(id)" in SRC
    assert 'data-monwatchstudio="' in SRC


def test_chart_theme_and_span_labels():
    assert "VIEW==='mon'&&MONTAB==='watch'&&typeof wsDrawChart==='function'" in SRC
    assert "覆盖 '+_sp" in SRC
    assert "const points=(tr.points||[]).length,days=Math.min(tr.days||WS.range,WS.range)" in SRC
    assert "else if(t.state==='wait')wait++" in SRC


def test_search_row_actions_are_roving_tab_stops():
    assert "function srxRowFocus(row)" in SRC
    assert 'onfocus="srxRowFocus(this)"' in SRC
    assert SRC.count('tabindex="-1" data-flighttrend="1"') == 1
    assert SRC.count('tabindex="-1" data-openbtn="1"') == 1


def test_route_trend_flags_do_not_claim_hits():
    # 长窗日桶仍写 flag=0（不得标真达标），但同时下发真实 OHLC；
    # K 线不再把单日 lo 复制成开=收=高=低。
    assert ('pts = lambda rows: [[r["day"], r["lo"], 0, r["open"], '
            'r["close"],\n                         r["hi"]] for r in rows]') in SRC


def test_mirror_age_is_route_scoped_and_stale_calendar_counted():
    seg = SRC[SRC.index("function srxChAge"):]
    assert "srxMirrorScope().filter(f=>f.platKey===ch)" in seg[:500]
    assert "const fallback=rows.filter(f=>srxIsStale(f)).length;" in SRC
    assert "补位·日历·不判达标" in SRC


def test_demo_exempt_from_real_time_staleness_but_live_not():
    assert "const stale=!(S&&S.demo)&&ageH!=null" in SRC
    assert "const _aged=q=>{if(S&&S.demo)return q;" in SRC


def test_mobile_row_actions_are_touch_sized():
    assert "grid-template-columns:26px minmax(0,1fr) auto 118px" in SRC
    assert "width:36px;height:36px;border:1px solid var(--line);background:var(--card)" in SRC
    assert "@media(pointer:coarse){.btn2{min-height:36px}}" in SRC


def test_health_detail_rate_excludes_calendar_only_rounds():
    src = io.open(os.path.join(ROOT, "core", "health.py"),
                  encoding="utf-8").read()
    assert 'det_att = att - st["cal_only"]' in src
    assert 'st["detail_rate"] = (st["detail_ok"] / det_att) if det_att else 0.0' in src
    # r365：用户面徽标/tooltip 统一全尝试轮分母，仅日历轮计入分母不计成功
    assert "${detOk}/${att}" in SRC
    assert "${detOk}/${detAtt}" not in SRC
