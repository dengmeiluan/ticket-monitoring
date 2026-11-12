# -*- coding: utf-8 -*-
"""r340 生产检索页：真实行溯源 / 原始行回放 / 视图契约。"""
import json
import sqlite3
import sys
import os
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def test_search_view_source_contract():
    src = webui.PAGE
    for needle in ('id="searchview"', 'id="navSearch"', 'id="srxRows"',
                   'id="srxRawWrap"', 'function renderSearch()',
                   'function srxFetchRaw(', '/api/probe/raw?row=',
                   '非原站截图', 'srx-rawaudit'):
        assert needle in src, needle
    assert "v==='search'?'searchview':'cfgview'" in src
    assert "const _hv=location.hash.slice(1).split('/')[0]" in src
    assert "switchView('search',false)" in src


def test_probe_raw_replays_exact_extra(tmp_path):
    dbp = str(tmp_path / "probe.db")
    st = PriceStorage(dbp)
    extra = [
        {"price": 880, "name": "东航MU541", "code": "MU541",
         "depTime": "09:55", "arrTime": "13:40"},
        {"price": 901, "name": "上航FM830", "code": "FM830",
         "depTime": "18:10", "arrTime": "22:20"},
    ]
    fp = FlightPrice("ctrip", "SHA", "BKK", "2026-11-20", 880,
                     extra=json.dumps(extra, ensure_ascii=False))
    st.save(fp)
    conn = sqlite3.connect(dbp)
    rid = conn.execute("SELECT MAX(id) FROM flight_prices").fetchone()[0]
    conn.close()
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        out = webui._probe_raw(rid, 1)
        assert out["ok"] is True
        assert out["raw"]["code"] == "FM830"
        assert out["idx"] == 1 and out["count"] == 2
        assert out["row"]["platform"] == "ctrip"
        assert out["row"]["fetched_at"]
        assert webui._probe_raw(rid, 99)["ok"] is False
        assert webui._probe_raw(999999, 0)["err"] == "row not found"
        with pytest.raises(ValueError):
            webui._probe_raw(0, 0)
    finally:
        webui._State.cfg = old_cfg


def test_user_state_carries_provenance_fields(tmp_path):
    dbp = str(tmp_path / "state.db")
    st = PriceStorage(dbp)
    date = "2026-11-20"
    extra = [{
        "price": 880, "name": "东航MU541", "code": "MU541",
        "depTime": "09:55", "arrTime": "13:40", "depDate": date,
        "totalDuration": "4时45分", "transCity": "",
    }]
    st.save(FlightPrice("ctrip", "SHA", "BKK", date, 880,
                        extra=json.dumps(extra, ensure_ascii=False)))
    route = Route("SHA", "上海", "BKK", "曼谷", [date],
                  alert_direct=1000, alert_transfer=0)
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "probe", "routes": [route]})
    finally:
        webui._State.cfg = old_cfg
    f = stt["flights"][0]
    assert f["from"] == "SHA" and f["to"] == "BKK"
    assert f["rowId"] and f["rawIdx"] == 0
    assert f["fetchedAt"]
    assert f["th"] == 1000.0
    assert f["code"] == "MU541"

def test_state_cache_schema_guard():
    """API payload schema 升级后，旧磁盘快照不得回放（r340 实测：
    重启后 8765 仍回旧 body，provenance 字段全缺）。"""
    src = open(webui.__file__, encoding="utf-8").read()
    assert "_STATE_SCHEMA = " in src
    assert '"schema": _STATE_SCHEMA' in src
    assert 'meta.get("schema") != _STATE_SCHEMA' in src or            'meta.get("schema")' in src and "_STATE_SCHEMA" in src

def test_probe_city_resolver():
    assert webui._probe_city_code("上海") == ("SHA", "上海")
    assert webui._probe_city_code("曼谷") == ("BKK", "曼谷")
    assert webui._probe_city_code("bkk") == ("BKK", "曼谷")
    assert webui._probe_city_code("") == ("", "")


def test_probe_form_source_contract():
    src = webui.PAGE
    for needle in ('id="srxFrom"', 'id="srxTo"', 'id="srxDate"',
                   'id="srxPlatPick"', 'id="srxGo"', '主动探针',
                   '/api/probe/start', '/api/probe/task', '不入库、不推送'):
        assert needle in src, needle
    assert "function srxProbeRun()" in src
    assert "SRX.probe" in src
