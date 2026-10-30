# -*- coding: utf-8 -*-
"""路径账聚合（PC/H5 可观测）：哪条路还能出数，账本说了算。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def _store(tmp_path):
    return PriceStorage(str(tmp_path / "prices.db"))


def test_path_stats_splits_pc_and_h5(tmp_path):
    st = _store(tmp_path)
    for path, status, rows in (("PC", "ok", 3), ("PC", "calendar", 0),
                               ("H5", "blocked", 0), ("H5", "empty", 0)):
        st.save_fetch_path("qunar", "SHA", "NRT", "2027-06-01", path,
                           status, rows=rows)
    node = st.path_stats(24)["qunar"]
    pc, h5 = node["paths"]["PC"], node["paths"]["H5"]
    assert (pc["attempts"], pc["ok"], pc["rate"]) == (2, 2, 1.0)
    assert (h5["attempts"], h5["blocked"], h5["empty"]) == (2, 1, 1)
    assert h5["rate"] == 0.0
    assert node["attempts"] == 4 and node["ok"] == 2
    assert node["rate"] == 0.5


def test_path_stats_window_and_empty(tmp_path):
    st = _store(tmp_path)
    assert st.path_stats(24) == {}
    st.save_fetch_path("ctrip", "SHA", "BKK", "2027-06-02", "H5", "timeout")
    s = st.path_stats(24)["ctrip"]["paths"]["H5"]
    assert s["error"] == 1 and s["attempts"] == 1


def test_recent_paths_newest_first(tmp_path):
    st = _store(tmp_path)
    st.save_fetch_path("qunar", "SHA", "NRT", "2027-06-01", "H5", "blocked",
                       note="滑块验证")
    st.save_fetch_path("qunar", "SHA", "NRT", "2027-06-01", "PC", "ok")
    rows = st.recent_paths("qunar", 5)
    assert [r["entry_path"] for r in rows] == ["PC", "H5"]
    assert rows[1]["note"] == "滑块验证"
    assert st.recent_paths("ctrip", 5) == []
