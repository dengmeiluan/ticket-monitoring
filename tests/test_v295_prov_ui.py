# -*- coding: utf-8 -*-
"""v1.5.295: provenance reaches UI/CSV and raw is labeled parsed extra."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def test_probe_raw_is_labeled_parsed_extra(tmp_path):
    old = webui._State.cfg
    db = str(tmp_path / "r.db")
    webui._State.cfg = {"output": {"db_path": db}}
    try:
        st = PriceStorage(db)
        st.save(FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500,
                            extra=json.dumps([{"code": "MU1", "price": 500}]),
                            prov=json.dumps({"entryPath": "PC",
                                             "evidenceLevel": "path"})))
        row = st.last_lowest("SHA", "BJS", "2026-11-10")
        out = webui._probe_raw(row["id"], 0)
        assert out["ok"] and out["evidence_level"] == "parsed_extra"
        assert out["prov"]["entryPath"] == "PC"
    finally:
        webui._State.cfg = old


def test_ui_and_csv_source_pins():
    import webui as w
    src = open(w.__file__, encoding="utf-8").read()
    for s in ("srxEntryOf", "采集入口", "证据级别",
              '"evidence_level": "parsed_extra"',
              "解析 extra / RAW（非原始响应）",
              "解析 extra 与解析字段一致",
              '"entryPath": str((pv or {}).get("entryPath")'):
        assert s in src, s
