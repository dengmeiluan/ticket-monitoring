# -*- coding: utf-8 -*-
"""v1.5.293 语义收口回归：关注子集继承、告警口径、探针状态、走势筛选。"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402
from report import _rounds  # noqa: E402


def _user(**route):
    base = {"from": "SHA", "to": "BJS", "dates": ["2026-11-16"]}
    base.update(route)
    return {"name": "u", "routes": [base]}


def _entry(**kw):
    e = {"from": "SHA", "to": "BJS", "date": "2026-11-16",
         "code": "MU541", "depTime": "09:55", "arrTime": "11:40",
         "trans": "", "cross": "", "stop": False, "cabin": "经济",
         "airline": "东方航空", "channels": ["ctrip"]}
    e.update(kw)
    return e


def test_watch_route_allows_enforces_parent_conditions():
    ok, _ = webui._watch_route_allows(_entry(), {"from": "SHA", "to": "BJS"})
    assert ok is True
    ok, why = webui._watch_route_allows(
        _entry(trans="PVG"), {"direct_only": True})
    assert ok is False and "直飞" in why
    ok, why = webui._watch_route_allows(
        _entry(depTime="23:30"), {"dep_time_max": "20:00"})
    assert ok is False and "出发时段" in why
    ok, why = webui._watch_route_allows(
        _entry(channels=["ctrip"]), {"channels": ["qunar"]})
    assert ok is False and "渠道" in why
    ok, why = webui._watch_route_allows(
        _entry(code="9C6217", airline="春秋航空"), {"no_lcc": True})
    assert ok is True  # no_lcc needs an explicit lcc flag, not inference
    ok, why = webui._watch_route_allows(
        _entry(code="MU541", airline="东方航空"), {"airlines": "!MU"})
    assert ok is False and "排除" in why


def test_watch_scope_flags_entry_outside_parent_filters(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [_user(direct_only=True)])
    in_scope, reason, state = webui._watch_scope_detail(
        _entry(trans="PVG"), "u")
    assert in_scope is False
    assert state == "route_filtered"
    assert "直飞" in reason


def test_watch_entry_rejects_identity_outside_parent_filters(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [_user(direct_only=True)])
    payload = {"from": "SHA", "to": "BJS", "date": "2026-11-16",
               "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
               "trans": "PVG", "cross": "", "stop": False, "cabin": "经济舱"}
    try:
        webui._watch_entry(payload, user="u")
        assert False, "must reject a transfer flight under direct_only"
    except ValueError as e:
        assert "父航线适用条件" in str(e)


class _Storage:
    def __init__(self):
        self.state = {}

    def get_alert_state(self, key):
        return self.state.get(key)

    def set_alert_state(self, key, value):
        self.state[key] = value


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp="", **kw):
        self.sent.append((title, desp))
        return True


def _alert(monkeypatch, price, eff):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    monkeypatch.setattr(webui, "_watch_list", lambda user: {"watches": [{
        "id": "w1", "code": "MU541", "from": "SHA", "to": "BJS",
        "date": "2099-01-01", "depTime": "09:55", "active": True,
        "notify": True, "target": 1020, "inScope": True,
        "channels": ["ctrip"]}]})
    monkeypatch.setattr(webui, "_watch_trend", lambda user, wid, days=2: {
        "current": {"price": price, "eff": eff, "platform": "ctrip", "at": now}})
    monkeypatch.setattr(webui, "_watch_parent_route", lambda w, u: None)
    monkeypatch.setattr(webui, "_watch_user_index", lambda u: 0)
    import logging
    st, n = _Storage(), _Notifier()
    sent = webui._watch_alert_round(
        "u", n, st, logging.getLogger("v293-test"), base_url="")
    return sent, n


def test_watch_alert_uses_eff_not_raw_list_price(monkeypatch):
    # 裸价 1000 低于目标，但达标口径 eff=1050 未达标：不得推送
    sent, n = _alert(monkeypatch, 1000, 1050)
    assert sent == 0 and n.sent == []
    # eff 低于目标才推送
    sent, n = _alert(monkeypatch, 1000, 990)
    assert sent == 1 and len(n.sent) == 1


def test_probe_result_status_keeps_typed_failures():
    assert webui._probe_result_status([], [{"status": "unsupported"}]) == "unsupported"
    assert webui._probe_result_status([], [{"status": "parse_error"}]) == "parse_error"
    assert webui._probe_result_status([], [{"status": "session_busy"}]) == "session_busy"
    assert webui._probe_result_status([], [{"status": "timeout"}]) == "timeout"
    assert webui._probe_result_status([], [{"status": "empty"}]) == "empty"


def test_long_window_trend_applies_route_conditions(tmp_path):
    """30/90/180 天长窗日桶也必须套用直飞/航司/时段/价格/渠道条件。"""
    dbp = str(tmp_path / "trendlong.db")
    st = PriceStorage(dbp)
    day = datetime.now().strftime("%Y-%m-%d")
    rows = [
        ("MU5101", "09:00", "11:00", "", "", False, 1200),   # only survivor
        ("MU5102", "09:00", "11:00", "", "", True, 1100),    # stop
        ("CA5103", "09:00", "11:00", "", "", False, 1000),   # airline
        ("MU5104", "09:00", "11:00", "PVG", "", False, 900),  # transfer
        ("MU5105", "09:00", "11:00", "", "+1天", False, 1300),  # cross
        ("MU5106", "23:00", "23:59", "", "", False, 1400),   # dep window
        ("MU5107", "09:00", "11:00", "", "", False, 1600),   # price max
    ]
    with st._conn() as c:
        for code, dep, arr, trans, cross, stop, price in rows:
            key = webui._srx_flight_key({
                "from": "SHA", "to": "BJS", "date": "2026-11-10",
                "code": code, "depTime": dep, "arrTime": arr,
                "trans": trans, "cross": cross, "stop": stop})
            c.execute(
                "INSERT INTO flight_daily (from_city,to_city,depart_date,"
                "flight_key,cabin,day,platform,n,lo,hi,open,close,fetched_max)"
                " VALUES ('SHA','BJS','2026-11-10',?,'经济',?,'ctrip',1,?,?,?,?,?)",
                (key, day, price, price, price, price, day + " 10:00:00"))
    out = webui._trend_from_flights(
        st, "SHA", "BJS", "2026-11-10", 90,
        route={"direct_only": True, "exclude_stop": True, "no_cross": True,
               "airlines": "MU", "price_max": 1500,
               "dep_time_min": "06:00", "dep_time_max": "20:00",
               "channels": ["ctrip"]})
    assert out is not None
    assert out["direct"] == [[day, 1200.0, 0, 1200.0, 1200.0, 1200.0]]
    assert out["transfer"] == []


def test_rounds_respects_direct_only_route(tmp_path):
    dbp = str(tmp_path / "rounds.db")
    st = PriceStorage(dbp)
    extra = [
        {"code": "MU5101", "price": 1000, "depTime": "09:00",
         "arrTime": "11:00", "totalDuration": "2时"},
        {"code": "MU5102", "price": 800, "depTime": "08:00",
         "arrTime": "20:00", "transCity": "PVG",
         "totalDuration": "12时", "transitServiceLabel": "行李直挂"},
    ]
    st.save(FlightPrice("ctrip", "SHA", "BJS", "2026-11-16", 1000,
                        extra=json.dumps(extra, ensure_ascii=False)))
    plain = _rounds(dbp, "SHA", "BJS", "2026-11-16", "23:59", hours=48)
    gated = _rounds(dbp, "SHA", "BJS", "2026-11-16", "23:59", hours=48,
                    rc={"direct_only": True})
    assert any(r[1] is not None for r in plain)
    assert any(r[2] is not None for r in plain)
    assert all(r[1] is not None for r in gated)
    assert all(r[2] is None for r in gated)
