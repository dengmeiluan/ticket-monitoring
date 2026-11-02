# -*- coding: utf-8 -*-
"""r367: text-length changes must not move action buttons or health rails."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_login_cards_equal_height_and_buttons_pinned_to_bottom():
    assert (".lggrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));"
            "gap:10px;align-items:stretch}") in SRC
    assert ".lgcard{height:100%;min-width:0}" in SRC
    assert ".lgcard .btn2{margin:auto 0 0;width:100%;justify-content:center}" in SRC
    assert "@media(max-width:1199px){.lggrid{grid-template-columns:repeat(3,minmax(0,1fr))}}" in SRC
    assert "@media(max-width:700px){.lggrid{grid-template-columns:repeat(2,minmax(0,1fr))}}" in SRC


def test_health_badge_column_is_fixed_and_header_action_does_not_jitter():
    assert ("#hbody .hrow{display:grid;grid-template-columns:64px minmax(0,1fr) 120px;"
            "gap:10px;align-items:center}") in SRC
    assert ("#hbody .hbadge{width:100%;min-width:0;padding-left:6px;padding-right:6px;"
            "white-space:nowrap;text-align:center}") in SRC
    assert ("#healthcard .hact{font-size:12px;height:30px;min-width:120px;"
            "text-align:center;white-space:nowrap}") in SRC


def test_probe_city_input_and_picker_are_one_surface():
    assert ("#searchview .srx-probeform .srx-citybox{display:flex!important;"
            "align-items:center;min-width:0;width:100%;") in SRC
    assert ("background:var(--r-surface-2)!important;border-radius:8px;"
            "box-shadow:none}") in SRC
    assert "#searchview .srx-probeform .srx-citybox input{flex:1 1 0;width:auto" in SRC
    assert "background:transparent!important;box-shadow:none!important;padding:0 9px}" in SRC
    assert ("#searchview .srx-probeform .srx-citychev{width:30px;height:32px;"
            "border:0!important;") in SRC
    assert ("border-left:1px solid var(--r-hair)!important;border-radius:0 8px 8px 0;"
            "background:transparent!important;color:var(--r-ink-3);box-shadow:none!important}") in SRC


def test_health_history_reads_rotated_logs():
    fn = SRC[SRC.index("def _read_log_tail("):SRC.index("def _log_tail(")]
    assert 'for p in (logp + ".3", logp + ".2", logp + ".1", logp):' in fn
    assert "max_age_h" in fn and "st.st_mtime" in fn
    seg = SRC[SRC.index("def _health_state("):SRC.index("def _push_channel_state(")]
    assert 'for p in (logp, logp + ".1", logp + ".2", logp + ".3", php):' in seg
    assert "_read_log_tail(max_age_h=hours + 2)" in seg


def test_current_auth_uses_channel_evidence_after_saved_session(monkeypatch, tmp_path):
    from datetime import datetime
    import webui
    from crawlers import REGISTRY

    class Channel:
        session_saved_at = 1700001000.0
        login_suspect = True

        def __init__(self, cfg, logger):
            pass

    (tmp_path / "qunar").mkdir()
    (tmp_path / "qunar" / "marker").write_text("synthetic profile")
    monkeypatch.setitem(REGISTRY, "qunar", Channel)
    monkeypatch.setattr(webui._State, "cfg", {"crawler": {"user_data_dir": str(tmp_path)}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {})
    evidence = {"auth_at": datetime.fromtimestamp(1700000900).isoformat(),
                "detail_at": "", "auth_reason": "需要登录"}
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [{"plats": {"qunar": {"need_login": True}}}],
        "evidence": {"qunar": {"domestic": evidence}}})
    state = webui._login_state_view()["plats"]["qunar"]
    assert state["status"] == "saved"
    assert state["health_need_login"] is False
    evidence["auth_at"] = datetime.fromtimestamp(1700001100).isoformat()
    state = webui._login_state_view()["plats"]["qunar"]
    assert state["status"] == "login_required"
    assert state["health_need_login"] is True


def test_band_prefetch_cached_axis_and_chart_left_edge():
    assert "function srxPrefetchBand(){" in SRC
    assert "else if(typeof srxPrefetchBand==='function')setTimeout" in SRC
    assert "let x0=Math.max(win,first), x1=Math.min(now,last+_obs*.02);" in SRC
    assert "&days=14&axis='+encodeURIComponent(SRX.calAxis)" in SRC
    assert 'def _srx_calendar(frm, to, date, days=14, axis="both"):' in SRC
    assert 'now - _CAL_CACHE["at"] < 30' in SRC
    assert "ROW_NUMBER() OVER (PARTITION BY depart_date" in SRC
    assert 'if axis in ("observation", "both"):' in SRC
    assert "function srxCalKeyBoth(){" in SRC and "axis=both" in SRC
