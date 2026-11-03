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


def test_user_state_exposes_mc_latest_without_fake_od(tmp_path):
    db = _make_db(tmp_path)
    webui._State.cfg = {"output": {"db_path": db}, "schedule": {}}
    users = [{
        "name": "u", "platforms": ["ctrip"],
        "routes": [
            {"from": "SHA", "from_name": "上海", "to": "OSA",
             "to_name": "大阪", "dates": ["2026-11-20", "2026-11-23"],
             "alert_threshold": 1500, "segments": SEGS_A},
            {"from": "PEK", "from_name": "北京", "to": "SHA",
             "to_name": "上海", "dates": ["2026-12-01"],
             "alert_direct": 800, "alert_transfer": 700},
        ],
    }]
    out = webui._user_state(users[0])
    assert len(out["routesArr"]) == 1, "多程不得混进逐日单程走势"
    mc = out["mcRoutes"]
    assert len(mc) == 1
    assert mc[0]["label"] == "SHA→TYO→OSA"
    assert mc[0]["latest"]["price"] == 1298.0
    assert mc[0]["supported"] is True and mc[0]["expired"] is False
    assert [x["flight_no"] for x in mc[0]["latest"]["legs"]] == [
        "9C8515", "MM304"]

    only_mc = {"name": "u", "platforms": ["qunar"], "routes": [
        {"from": "SHA", "to": "OSA", "dates": ["2020-01-01"],
         "segments": [{"from": "SHA", "to": "TYO", "date": "2020-01-01"},
                      {"from": "TYO", "to": "OSA", "date": "2020-01-03"}]}]}
    out = webui._user_state(only_mc)
    assert out["mcRoutes"][0]["supported"] is False
    assert out["mcRoutes"][0]["expired"] is True
    assert out["mcRoutes"][0]["latest"] is None


def test_normalize_mc_users_derives_ends_and_dates():
    users = [{"name": "u", "routes": [
        {"from": "", "to": "", "dates": [], "segments": SEGS_A},
        {"from": "PEK", "to": "SHA", "dates": ["2026-12-01"]},
    ]}]
    webui._normalize_mc_users(users)
    mc, plain = users[0]["routes"]
    assert mc["from"] == "SHA" and mc["to"] == "OSA"
    assert mc["dates"] == ["2026-11-20", "2026-11-23"]
    assert mc["from_name"] == "上海" and mc["to_name"] == "大阪"
    assert "segments" not in plain, "单 O-D 不得被写入多程键"
    with pytest.raises(ValueError, match="多程行程不合法"):
        webui._normalize_mc_users([{"routes": [{"segments": SEGS_A[:1]}]}])


@pytest.fixture()
def config_server(tmp_path, monkeypatch):
    import io
    import logging
    import yaml
    cfg_path = str(tmp_path / "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30}}
    with io.open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(base, f, allow_unicode=True)
    monkeypatch.setattr(webui, "DEMO", {"on": False})
    st = webui._State
    for attr, val in (("cfg", dict(base)), ("boot_cfg", dict(base)),
                      ("users", []), ("alerters", []), ("job", None),
                      ("report_push", None), ("reload_cb", None),
                      ("config_path", cfg_path), ("version", "test"),
                      ("login_saved_cb", None),
                      ("logger", logging.getLogger("mcapi"))):
        monkeypatch.setattr(st, attr, val, raising=False)
    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1], cfg_path
    finally:
        srv.shutdown()
        srv.server_close()


def _post(base, payload):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        base + "/api/config", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with op.open(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_config_post_round_trips_multicity(config_server):
    import io
    import yaml
    base, cfg_path = config_server
    payload = {"users": [{
        "name": "u", "platforms": ["ctrip"],
        "routes": [{"from": "", "to": "", "dates": [],
                    "alert_threshold": 1500, "segments": SEGS_A}]}],
        "globals": {}}
    code, out = _post(base, payload)
    assert code == 200 and out.get("ok"), out
    saved = yaml.safe_load(io.open(cfg_path, encoding="utf-8"))
    route = saved["users"][0]["routes"][0]
    assert route["from"] == "SHA" and route["to"] == "OSA"
    assert route["dates"] == ["2026-11-20", "2026-11-23"]
    assert route["from_name"] == "上海" and route["to_name"] == "大阪"
    assert [s["from"] for s in route["segments"]] == ["SHA", "TYO"]

    bad = {"users": [{"name": "u", "routes": [
        {"segments": SEGS_A[:1]}]}], "globals": {}}
    code, out = _post(base, bad)
    assert code == 400 and "多程行程不合法" in out["err"]
    after = yaml.safe_load(io.open(cfg_path, encoding="utf-8"))
    assert len(after["users"][0]["routes"][0]["segments"]) == 2, \
        "坏配置不得落盘"
