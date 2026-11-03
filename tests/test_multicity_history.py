# -*- coding: utf-8 -*-
"""多程整单历史：只追加真实落库点，latest 仍只保留最新一行。"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402
from core.multicity import segments_key  # noqa: E402
from core.storage import PriceStorage  # noqa: E402

SEGS = [{"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "TYO", "to": "OSA", "date": "2026-11-23"}]
LEGS = [{"flight_no": "9C8515", "from": "SHA", "to": "TYO",
         "date": "2026-11-20"},
        {"flight_no": "MM304", "from": "TYO", "to": "OSA",
         "date": "2026-11-23"}]
KEY = segments_key(SEGS)


def _seed(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    for ts, price in (("2026-11-03 10:00:00", 1298.0),
                      ("2026-11-03 10:30:00", 1200.0),
                      ("2026-11-03 11:00:00", 1180.0)):
        st.save_itinerary("ctrip", KEY, SEGS, price, LEGS, fetched_at=ts)
    return st


def test_history_appends_while_latest_stays_one(tmp_path):
    st = _seed(tmp_path)
    hist = st.itinerary_history(KEY)
    assert [p[1] for p in hist] == [1298.0, 1200.0, 1180.0]
    assert hist[0][0] == "2026-11-03T10:00:00"
    latest = st.itineraries(segments_key=KEY, limit=5)
    assert len(latest) == 1 and latest[0]["total_price"] == 1180.0


def test_history_is_idempotent_per_second(tmp_path):
    st = _seed(tmp_path)
    st.save_itinerary("ctrip", KEY, SEGS, 1180.0, LEGS,
                      fetched_at="2026-11-03 11:00:00")
    assert len(st.itinerary_history(KEY)) == 3, "同一秒重放不得灌重复点"


def test_user_state_exposes_history_and_missing_table_is_empty(tmp_path):
    st = _seed(tmp_path)
    webui._State.cfg = {"output": {"db_path": st.db_path}, "schedule": {}}
    out = webui._user_state({
        "name": "u", "platforms": ["ctrip"],
        "routes": [{"from": "SHA", "to": "OSA",
                    "dates": ["2026-11-20", "2026-11-23"],
                    "alert_threshold": 1500, "segments": SEGS}]})
    assert len(out["mcRoutes"][0]["history"]) == 3
    assert out["mcRoutes"][0]["history"][-1][1] == 1180.0

    empty = str(tmp_path / "empty.db")
    with sqlite3.connect(empty):
        pass
    assert webui._multicity_history(empty, KEY) == []
    with sqlite3.connect(empty) as c:
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "itinerary_history" not in names, "只读历史查询不得建表"
