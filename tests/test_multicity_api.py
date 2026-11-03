# -*- coding: utf-8 -*-
"""/api/multicity 只读面：真库读到整单总价，空态诚实且 GET 不建库建表。"""
import json
import os
import sqlite3
import sys
import threading
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402
from core.multicity import build_mc_extra, segments_key  # noqa: E402
from core.storage import PriceStorage  # noqa: E402

SEGS_A = [{"from": "SHA", "to": "TYO", "date": "2026-11-20"},
          {"from": "TYO", "to": "OSA", "date": "2026-11-23"}]
SEGS_B = [{"from": "PEK", "to": "SIN", "date": "2026-12-01"},
          {"from": "SIN", "to": "DPS", "date": "2026-12-05"}]
LEGS_A = [{"flight_no": "9C8515", "from": "SHA", "to": "TYO",
           "date": "2026-11-20"},
          {"flight_no": "MM304", "from": "TYO", "to": "OSA",
           "date": "2026-11-23"}]
LEGS_B = [{"flight_no": "CA975", "from": "PEK", "to": "SIN",
           "date": "2026-12-01"},
          {"flight_no": "QZ501", "from": "SIN", "to": "DPS",
           "date": "2026-12-05"}]


def _make_db(tmp_path):
    db = str(tmp_path / "prices.db")
    st = PriceStorage(db)
    st.save_itinerary("ctrip", segments_key(SEGS_A), SEGS_A, 1298.0, LEGS_A)
    st.save_itinerary("ctrip", segments_key(SEGS_B), SEGS_B, 2600.0, LEGS_B)
    return db


def test_payload_reads_page_total_and_legs(tmp_path):
    db = _make_db(tmp_path)
    out = webui._multicity_payload(segments_key=segments_key(SEGS_A),
                                   demo=False, db_path=db)
    assert out["ok"] is True and out["count"] == 1
    item = out["items"][0]
    assert item["platform"] == "ctrip"
    assert item["total_price"] == 1298.0
    assert item["extra"]["tripType"] == "MC"
    assert len(item["extra"]["legs"]) == 2
    assert "legs_json" not in item


def test_payload_filters_and_clamps_limit(tmp_path):
    db = _make_db(tmp_path)
    both = webui._multicity_payload(demo=False, db_path=db)
    assert both["count"] == 2
    one = webui._multicity_payload(route_id=segments_key(SEGS_B),
                                   demo=False, db_path=db)
    assert [x["segments_key"] for x in one["items"]] == [segments_key(SEGS_B)]
    assert webui._multicity_payload(limit=1, demo=False,
                                    db_path=db)["count"] == 1
    out = webui._multicity_payload(limit="999", demo=False, db_path=db)
    assert out["limit"] == 500
    out = webui._multicity_payload(limit="oops", demo=False, db_path=db)
    assert out["limit"] == 200


def test_payload_empty_states_are_honest(tmp_path):
    missing = str(tmp_path / "nope.db")
    out = webui._multicity_payload(demo=False, db_path=missing)
    assert out == {"ok": True, "demo": False, "route_id": "",
                   "segments_key": "", "limit": 200, "items": [], "count": 0,
                   "note": "库尚未创建"}
    assert not os.path.exists(missing), "GET 不得创建数据库"

    legacy = str(tmp_path / "legacy.db")
    with sqlite3.connect(legacy) as c:
        c.execute("CREATE TABLE other (x INTEGER)")
    out = webui._multicity_payload(demo=False, db_path=legacy)
    assert out["count"] == 0 and "尚无多程表" in out["note"]
    with sqlite3.connect(legacy) as c:
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "itinerary_daily" not in names, "GET 不得建多程表"

    db = _make_db(tmp_path)
    demo = webui._multicity_payload(demo=True, db_path=db)
    assert demo["items"] == [] and demo["demo"] is True
    assert "演示" in demo["note"]


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    monkeypatch.setattr(webui, "DEMO", {"on": False})
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db}}, raising=False)
    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _get(url):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(url, timeout=20) as r:
        return json.loads(r.read().decode())


def test_endpoint_serves_filtered_payload(live_server):
    key = segments_key(SEGS_A)
    out = _get(live_server + "/api/multicity?segments_key=" + key)
    assert out["ok"] is True and out["count"] == 1
    assert out["segments_key"] == key
    assert out["items"][0]["total_price"] == 1298.0
    none = _get(live_server + "/api/multicity?route_id=no-such-route")
    assert none["ok"] is True and none["items"] == []
