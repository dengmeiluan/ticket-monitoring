# -*- coding: utf-8 -*-
"""长窗走势口径：有真实航班级日桶时不得混入日历价池。"""
import sqlite3
from datetime import datetime

import webui
from core.storage import PriceStorage


def test_long_trend_prefers_flight_daily_over_calendar_pool(tmp_path):
    dbp = str(tmp_path / "basis.db")
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        st = PriceStorage(dbp)
        today = datetime.now().strftime("%Y-%m-%d")
        with st._conn() as c:
            c.execute(
                "INSERT INTO price_daily (from_city,to_city,depart_date,day,kind,n,lo,hi,open,close,avg,fetched_max) "
                "VALUES ('SHA','BKK','2026-11-16',?,'d',1,100,100,100,100,100,?)",
                (today, today + " 00:00:00"))
            c.execute(
                "INSERT INTO flight_daily (from_city,to_city,depart_date,day,flight_key,platform,cabin,n,lo,hi,open,close,fetched_max) "
                "VALUES ('SHA','BKK','2026-11-16',?,'SHA|BKK|MU541|2026-11-16|09:55|13:40|||0','ctrip','经济',2,820,900,820,900,?)",
                (today, today + " 01:00:00"))
            c.execute(
                "INSERT INTO flight_daily (from_city,to_city,depart_date,day,flight_key,platform,cabin,n,lo,hi,open,close,fetched_max) "
                "VALUES ('SHA','BKK','2026-11-16',?,'SHA|BKK|MU542|2026-11-16|10:55|14:40|曼谷|+1天|0','qunar','经济',1,780,780,780,780,?)",
                (today, today + " 02:00:00"))
        out = webui._trend_payload({"from": ["SHA"], "to": ["BKK"],
                                    "date": ["2026-11-16"], "days": ["30"]})
        assert out["ok"] is True
        assert out["basis"] == "flight_daily"
        assert out["direct"] and out["transfer"]
        assert out["direct"][-1][1] == 820   # 不含日历价 100
        assert out["transfer"][-1][1] == 780
    finally:
        webui._State.cfg = old_cfg


def test_long_trend_payload_applies_route_conditions(tmp_path):
    dbp = str(tmp_path / "basis_route.db")
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        st = PriceStorage(dbp)
        today = datetime.now().strftime("%Y-%m-%d")
        with st._conn() as c:
            for key, plat, price in (
                    ("SHA|BKK|MU541|2026-11-16|09:55|13:40|||0", "ctrip", 900),
                    ("SHA|BKK|CA542|2026-11-16|10:55|14:40|||0", "ctrip", 800),
                    ("SHA|BKK|MU543|2026-11-16|11:55|15:40|曼谷||0", "ctrip", 700)):
                c.execute(
                    "INSERT INTO flight_daily (from_city,to_city,depart_date,"
                    "flight_key,platform,cabin,day,n,lo,hi,open,close,fetched_max)"
                    " VALUES ('SHA','BKK','2026-11-16',?,?,'经济',?,1,?,?,?,?,?)",
                    (key, plat, today, price, price, price, price,
                     today + " 01:00:00"))
        out = webui._trend_payload({
            "from": ["SHA"], "to": ["BKK"], "date": ["2026-11-16"],
            "days": ["30"], "rdirect": ["1"], "rairlines": ["MU"],
            "rpmax": ["1000"]})
        assert out["ok"] is True and out["filtered"] is True
        assert out["transfer"] == []
        assert [p[1] for p in out["direct"]] == [900]
    finally:
        webui._State.cfg = old_cfg


def test_long_trend_filtered_without_flight_daily_does_not_use_calendar(tmp_path):
    dbp = str(tmp_path / "basis_empty.db")
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        st = PriceStorage(dbp)
        today = datetime.now().strftime("%Y-%m-%d")
        with st._conn() as c:
            c.execute(
                "INSERT INTO price_daily (from_city,to_city,depart_date,day,kind,n,lo,hi,open,close,avg,fetched_max) "
                "VALUES ('SHA','BKK','2026-11-16',?,'d',1,100,100,100,100,100,?)",
                (today, today + " 00:00:00"))
        out = webui._trend_payload({
            "from": ["SHA"], "to": ["BKK"], "date": ["2026-11-16"],
            "days": ["30"], "rdirect": ["1"]})
        assert out["ok"] is True
        assert out["basis"] == "flight_daily_filtered_empty"
        assert out["direct"] == [] and out["transfer"] == []
        assert "未用日历价替代" in out["note"]
    finally:
        webui._State.cfg = old_cfg
