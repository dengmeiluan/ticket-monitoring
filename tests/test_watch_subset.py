# -*- coding: utf-8 -*-
"""关注航班是配置航线+日期明细集合中的指定航班子集。"""
import json

import pytest

import webui
from core.models import FlightPrice
from core.storage import PriceStorage


def payload(**kw):
    data = {
        "from": "SHA", "to": "BJS", "date": "2026-11-01",
        "code": "MU5101", "depTime": "08:00", "arrTime": "10:00",
        "channels": ["qunar"],
    }
    data.update(kw)
    return data


def _user(routes):
    return {"name": "u", "platforms": ["qunar"], "routes": routes}


def _state(monkeypatch, tmp_path, routes):
    dbp = str(tmp_path / "watch-subset.db")
    monkeypatch.setattr(webui._State, "cfg", {"output": {"db_path": dbp}})
    monkeypatch.setattr(webui._State, "users", [_user(routes)])
    webui._WATCH_CACHE.clear()
    return dbp


def test_watch_requires_configured_route_date(monkeypatch):
    user = {"name": "u", "platforms": ["qunar"],
            "routes": [{"from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}]}
    monkeypatch.setattr(webui._State, "users", [user])
    with pytest.raises(ValueError, match="未配置关注航线"):
        webui._watch_entry(payload(date="2027-01-09"), user="u")


def test_watch_accepts_configured_route_date_and_channels(monkeypatch):
    user = {"name": "u", "platforms": ["qunar"],
            "routes": [{"from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}]}
    monkeypatch.setattr(webui._State, "users", [user])
    entry = webui._watch_entry(
        payload(channels=["ctrip", "tongcheng"]), user="u")
    public = webui._watch_public(entry, "u")
    assert public["inScope"] is True
    assert entry["channels"] == ["ctrip", "tongcheng"]


def test_watch_scope_marks_legacy_without_route(monkeypatch):
    user = {"name": "u", "platforms": ["qunar"], "routes": []}
    monkeypatch.setattr(webui._State, "users", [user])
    entry = webui._watch_entry(payload())
    public = webui._watch_public(entry, "u")
    assert public["inScope"] is False
    assert public["scopeState"] == "route_missing"
    assert public["legacy"] is True
    assert "未匹配关注航线/日期" in public["scopeReason"]

    entry["date"] = "2020-01-01"
    public = webui._watch_public(entry, "u")
    assert public["inScope"] is False
    assert "日期" in public["scopeReason"]


def test_watch_legacy_non_identity_update_allowed(monkeypatch):
    user = {"name": "u", "platforms": ["qunar"], "routes": []}
    monkeypatch.setattr(webui._State, "users", [user])
    old = webui._watch_entry(payload())
    updated = webui._watch_entry(payload(target=800), old=old, user="u")
    assert updated["target"] == 800
    assert webui._watch_public(updated, "u")["inScope"] is False


def test_watch_route_date_range(monkeypatch):
    user = {"name": "u", "platforms": ["qunar"],
            "routes": [{"from": "SHA", "to": "BJS",
                        "start": "2026-11-01", "end": "2026-11-03"}]}
    monkeypatch.setattr(webui._State, "users", [user])
    entry = webui._watch_entry(payload(date="2026-11-02"), user="u")
    assert webui._watch_in_scope(entry, "u") is True
    with pytest.raises(ValueError, match="未配置关注航线"):
        webui._watch_entry(payload(date="2026-11-04"), user="u")


def test_watch_defaults_to_all_scan_channels(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [])
    entry = webui._watch_entry(payload(channels=None))
    assert entry["channels"] == list(webui._WATCH_PLATS)


def test_disabled_route_is_not_a_parent(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [_user([{
        "from": "SHA", "to": "BJS", "dates": ["2026-11-01"],
        "enabled": False}])])
    with pytest.raises(ValueError, match="未配置关注航线"):
        webui._watch_entry(payload(), user="u")


def test_watch_accepts_fresh_raw_candidate_before_daily(monkeypatch, tmp_path):
    dbp = _state(monkeypatch, tmp_path, [{
        "from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}])
    st = PriceStorage(dbp)
    st.save(FlightPrice("qunar", "SHA", "BJS", "2026-11-01", 880,
                        extra=json.dumps([{
                            "code": "MU5101", "name": "东航MU5101",
                            "depDate": "2026-11-01", "depTime": "08:00",
                            "arrTime": "10:00", "totalDuration": "2时",
                            "price": 880}], ensure_ascii=False)))
    entry = webui._watch_entry(payload(), user="u")
    assert entry["flightKey"]
    known, has_rows = webui._watch_known_flight(entry, deep=True)
    assert known is True and has_rows is True


def test_watch_rejects_identity_not_in_collected_detail(monkeypatch, tmp_path):
    dbp = _state(monkeypatch, tmp_path, [{
        "from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}])
    st = PriceStorage(dbp)
    st.save(FlightPrice("qunar", "SHA", "BJS", "2026-11-01", 880,
                        extra=json.dumps([{
                            "code": "MU9999", "name": "东航MU9999",
                            "depDate": "2026-11-01", "depTime": "08:00",
                            "arrTime": "10:00", "totalDuration": "2时",
                            "price": 880}], ensure_ascii=False)))
    from datetime import datetime
    st.refresh_flight_daily("SHA", "BJS", "2026-11-01",
                            datetime.now().strftime("%Y-%m-%d"))
    with pytest.raises(ValueError, match="不在此航线/日期的采集明细"):
        webui._watch_entry(payload(), user="u")


def test_missing_round_keeps_watch_in_scope(monkeypatch, tmp_path):
    dbp = _state(monkeypatch, tmp_path, [{
        "from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}])
    st = PriceStorage(dbp)
    st.save(FlightPrice("qunar", "SHA", "BJS", "2026-11-01", 880,
                        extra=json.dumps([{
                            "code": "MU9999", "name": "东航MU9999",
                            "depDate": "2026-11-01", "depTime": "08:00",
                            "arrTime": "10:00", "totalDuration": "2时",
                            "price": 880}], ensure_ascii=False)))
    from datetime import datetime
    st.refresh_flight_daily("SHA", "BJS", "2026-11-01",
                            datetime.now().strftime("%Y-%m-%d"))
    entry = webui._watch_entry(payload())
    public = webui._watch_public(entry, "u")
    assert public["inScope"] is True
    assert public["scopeState"] == "flight_missing"
    assert public["legacy"] is False
    assert "等待下一轮" in public["scopeReason"]


def test_watch_identity_is_not_merged_by_display_text(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [])
    base = webui._watch_entry(payload())
    assert webui._watch_entry(payload(date="2026-11-02"))["flightKey"] != base["flightKey"]
    assert webui._watch_entry(payload(**{"from": "PVG"}))["flightKey"] != base["flightKey"]
    assert webui._watch_entry(payload(code="FM9301"))["flightKey"] != base["flightKey"]
    assert webui._watch_entry(payload(cross="+1"))["flightKey"] != base["flightKey"]
    seg_a = webui._watch_entry(payload(code="MU541/MU542"))
    seg_b = webui._watch_entry(payload(code="MU542/MU541"))
    assert seg_a["flightKey"] == seg_b["flightKey"]


def test_watch_cap_is_explicit(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path, [{
        "from": "SHA", "to": "BJS", "dates": ["2026-11-01"]}])
    items = [{"id": "w%d" % i, "flightKey": "k%d" % i} for i in range(100)]
    monkeypatch.setattr(webui, "_watch_read", lambda: {"u": list(items)})
    monkeypatch.setattr(webui, "_watch_write", lambda data: None)
    with pytest.raises(ValueError, match="最多 100 条"):
        webui._watch_apply("u", {"op": "add", "watch": payload()})
