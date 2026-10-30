# -*- coding: utf-8 -*-
"""v1.5.295: path-level provenance persists without claiming raw HTTP."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402
import main  # noqa: E402


def test_fetch_path_and_prov_round_trip(tmp_path):
    st = PriceStorage(str(tmp_path / "p.db"))
    pid = st.save_fetch_path("ctrip", "SHA", "BJS", "2026-11-10",
                             "PC", "ok", rows=12)
    fp = FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500,
                     prov=json.dumps({"entryPath": "PC", "pathId": pid,
                                      "pathStatus": "ok",
                                      "evidenceLevel": "path",
                                      "kind": "detail"}))
    st.save(fp)
    row = st.last_lowest("SHA", "BJS", "2026-11-10")
    assert json.loads(row["prov"])["entryPath"] == "PC"
    paths = st.fetch_paths("SHA", "BJS", "2026-11-10")
    assert paths[0]["entry_path"] == "PC"
    assert paths[0]["evidence_level"] == "path"


def test_flight_price_prov_defaults_empty():
    assert FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500).prov == ""


def test_scan_source_pins_path_level_evidence():
    with open(main.__file__, encoding="utf-8") as f:
        src = f.read()
    for s in ('"entryPath"', '"pathStatus"', '"evidenceLevel": "path"',
              "storage.save_fetch_path", "p.prov = prov"):
        assert s in src, s
