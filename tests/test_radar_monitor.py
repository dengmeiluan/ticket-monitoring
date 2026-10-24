# -*- coding: utf-8 -*-
"""特价监控：逐日价快照、走势历史与低价日真实航班。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def _result(user="u1", prices=None):
    prices = prices or {"2026-11-10": 500, "2026-11-11": 450}
    dates = []
    for day, price in prices.items():
        dates.append({
            "date": day,
            "best": {"price": price, "channel": "ctrip", "to": "BJS",
                     "basis": "unknown", "basis_label": "口径未标注",
                     "kind": "calendar", "link": ""},
            "by_channel": {
                "ctrip": {"price": price, "to": "BJS", "basis": "unknown",
                          "kind": "calendar", "link": ""},
                "fliggy": {"price": price + 20, "to": "BJS",
                           "basis": "tax_included", "kind": "calendar",
                           "link": ""},
            },
        })
    return {"ok": True, "dates": dates,
            "query": {"user": user, "from": "SHA", "to": "BJS",
                      "nationwide": False, "start": "2026-11-10",
                      "end": "2026-11-11", "channels": ["ctrip", "fliggy"]}}


def _state(tmp_path):
    old = webui._State.cfg
    dbp = str(tmp_path / "radar.db")
    webui._State.cfg = {"output": {"db_path": dbp}}
    return old, dbp


def test_radar_snapshot_history_and_delta(tmp_path):
    old, dbp = _state(tmp_path)
    try:
        st = PriceStorage(dbp)
        assert st.save_radar_snapshot("u1", _result()["query"], _result()) == 4
        h1 = st.radar_history("u1")
        assert len(h1["dates"]) == 2 and h1["snapshots"] == 1
        assert h1["lowest"]["price"] == 450
        assert h1["dates"][0]["prev_price"] is None
        # second run: same date/channel -> previous price retained
        st.save_radar_snapshot("u1", _result()["query"],
                               _result(prices={"2026-11-10": 400,
                                               "2026-11-11": 450}))
        h2 = st.radar_history("u1")
        assert h2["snapshots"] == 2 and len(h2["series"]) == 2
        day10 = next(d for d in h2["dates"] if d["date"] == "2026-11-10")
        assert day10["price"] == 400 and day10["prev_price"] == 500
        assert h2["lowest"]["date"] == "2026-11-10"
    finally:
        webui._State.cfg = old


def test_demo_radar_feeds_monitor_and_low_day_flights(tmp_path):
    """演示库（--demo / 静态站）必须有可浏览的监控走势，而不是空态。"""
    from core.demo import build_demo_db, demo_routes
    db = str(tmp_path / "demo.db")
    build_demo_db(db)
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": db}}
    try:
        h = PriceStorage(db).radar_history("演示用户")
        assert h["snapshots"] == 3 and len(h["dates"]) == 7
        assert len({s["at"] for s in h["series"]}) == 3
        assert all(d["prev_price"] != d["price"] for d in h["dates"])
        assert h["lowest"]["date"] == demo_routes()[0]["dates"][0]
        assert {d["channel"] for d in h["dates"]} == {
            "ctrip", "fliggy", "tongcheng"}
        out = webui._radar_low_flights(
            "SHA", "URC", h["lowest"]["date"])
        assert out["found"] and out["flights"]
    finally:
        webui._State.cfg = old


def test_radar_low_flights_reads_real_detail(tmp_path):
    old, dbp = _state(tmp_path)
    try:
        st = PriceStorage(dbp)
        items = [
            {"code": "MU5101", "name": "东航", "price": 620,
             "depTime": "08:00", "arrTime": "10:00"},
            {"code": "CA1502", "name": "国航", "price": 580,
             "depTime": "09:00", "arrTime": "11:00"},
        ]
        st.save(FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 580,
                            extra=json.dumps(items, ensure_ascii=False)))
        out = webui._radar_low_flights("SHA", "BJS", "2026-11-10")
        assert out["ok"] and out["found"] is True
        assert out["flights"][0]["code"] == "CA1502"
        assert out["flights"][0]["price"] == 580
        # no detail -> honest empty, no invented flight
        none = webui._radar_low_flights("SHA", "BJS", "2026-12-31")
        assert none["found"] is False and none["flights"] == []
    finally:
        webui._State.cfg = old
