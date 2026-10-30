# -*- coding: utf-8 -*-
"""v1.5.295: radar history is scoped by query, failures are ledger-only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def _q(to, start, end, channels=("ctrip",)):
    return {"from": "SHA", "to": to, "nationwide": False,
            "start": start, "end": end, "channels": list(channels)}


def _result(day, price, to="BJS", channel="ctrip"):
    return {"dates": [{
        "date": day,
        "by_channel": {channel: {
            "price": price, "to": to, "basis": "bare",
            "kind": "calendar", "link": ""}},
    }]}


def test_query_key_is_stable_and_channel_scoped(tmp_path):
    st = PriceStorage(str(tmp_path / "q.db"))
    k1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    k2 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07",
                               ("fliggy", "ctrip")))
    assert k1 != k2
    assert k1 == st.radar_query_key(
        _q("BJS", "2026-11-01", "2026-11-07"))


def test_history_does_not_mix_routes(tmp_path):
    st = PriceStorage(str(tmp_path / "h.db"))
    st.save_radar_snapshot("u", _q("BJS", "2026-11-01", "2026-11-07"),
                           _result("2026-11-01", 500, "BJS"))
    st.save_radar_snapshot("u", _q("CAN", "2026-12-01", "2026-12-07"),
                           _result("2026-12-01", 400, "CAN"),
                           run_status="ok")
    q1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    h = st.radar_history("u", query_key=q1)
    assert h["query"]["to"] == "BJS"
    assert [d["date"] for d in h["dates"]] == ["2026-11-01"]
    latest = st.radar_history("u")
    assert latest["query"]["to"] == "CAN"
    assert latest["query_key"] == st.radar_query_key(
        _q("CAN", "2026-12-01", "2026-12-07"))


def test_non_ok_run_is_ledger_only(tmp_path):
    st = PriceStorage(str(tmp_path / "r.db"))
    q = _q("BJS", "2026-11-01", "2026-11-07")
    n = st.save_radar_snapshot("u", q, _result("2026-11-01", 500),
                               run_status="cache_hit")
    assert n == 0
    h = st.radar_history("u")
    assert h["dates"] == []
    assert h["last_run"]["status"] == "cache_hit"
    assert h["query"]["to"] == "BJS"


def test_old_snapshot_table_is_migrated(tmp_path):
    import sqlite3
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE radar_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL,
        from_city TEXT NOT NULL, to_city TEXT NOT NULL,
        nationwide INTEGER NOT NULL DEFAULT 0,
        depart_date TEXT NOT NULL, channel TEXT NOT NULL,
        price REAL NOT NULL, tax_included INTEGER NOT NULL DEFAULT -1,
        basis TEXT, kind TEXT, link TEXT, query_start TEXT,
        query_end TEXT, fetched_at TEXT NOT NULL);
    """)
    c.execute("INSERT INTO radar_snapshots (user,from_city,to_city,nationwide,"
              "depart_date,channel,price,tax_included,basis,kind,link,"
              "query_start,query_end,fetched_at) VALUES "
              "('u','SHA','BJS',0,'2026-11-01','ctrip',500,1,'bare',"
              "'calendar','','2026-11-01','2026-11-07','2026-10-24 10:00:00')")
    c.commit()
    c.close()
    st = PriceStorage(p)
    h = st.radar_history("u")
    assert h["query"]["to"] == "BJS"
    assert h["dates"][0]["price"] == 500
