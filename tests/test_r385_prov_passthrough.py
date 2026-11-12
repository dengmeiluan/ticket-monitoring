# -*- coding: utf-8 -*-
"""r385：/api/state 的每行明细必须带真实采集溯源。

生产实锤：flight_prices.prov 里有 {"entryPath":"PC"|"H5",
"pathStatus":"ok","kind":"detail"}，但两条取数 SQL 都没 SELECT prov，
下游 `g["_prov"]=r["prov"]` 直接落 except → 整页 1936 行 prov 全是 {}，
用户读作「补位数据来源不明、看着奇怪」。"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_user_state_query_selects_prov():
    src = _src("webui.py")
    i = src.index("def _user_state(u):")
    seg = src[i:i + 3000]
    assert 'PRAGMA table_info(flight_prices)' in seg, "未按库结构自适应 prov 列"
    assert '", prov" if _has_prov else ""' in seg, "当轮明细 SQL 未取 prov"
    assert '_has_prov else ""' in seg and '["prov"]' in seg, "prov 未随行透传"


def test_recent_platform_flights_selects_and_attaches_prov():
    src = _src("report.py")
    i = src.index("def recent_platform_flights(")
    seg = src[i:i + 4000]
    assert '", prov" if _has_prov else ""' in seg, "补位 SQL 未取 prov"
    assert '_it["_prov"] = r["prov"] or ""' in seg


def test_fallback_merge_carries_prov_into_pool():
    src = _src("webui.py")
    i = src.index("_state_stale_hours()).items():")
    seg = src[i:i + 1400]
    assert 'g["_prov"] = f.get("_prov")' in seg, "补位合并未携带 prov"


def test_prov_reaches_api_payload(tmp_path, monkeypatch):
    """端到端：真实一行带 prov → recent_platform_flights 原样带回。

    不依赖“当前时间窗”（pytest 会话里其他用例会改时区/时钟），
    直接把窗口放宽到 100 年，只验证 prov 的透传。"""
    import json as _j
    from datetime import datetime, timedelta
    import report
    db = str(tmp_path / "p.db")
    c = sqlite3.connect(db)
    c.execute(
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, platform TEXT, "
        "from_city TEXT, to_city TEXT, depart_date TEXT, price REAL, "
        "airline TEXT, flight_no TEXT, depart_time TEXT, arrive_time TEXT, "
        "fetched_at TEXT, extra TEXT, prov TEXT)")
    extra = _j.dumps([{"price": 662, "depTime": "08:05", "arrTime": "12:30",
                       "code": "MU501", "depDate": "2026-11-16"}])
    prov = _j.dumps({"entryPath": "PC", "pathStatus": "ok", "kind": "detail"})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO flight_prices (platform,from_city,to_city,"
              "depart_date,price,airline,flight_no,depart_time,arrive_time,"
              "fetched_at,extra,prov) VALUES "
              "('ctrip','SHA','BKK','2026-11-16',662,'','MU501','08:05',"
              "'12:30',?,?,?)", (now, extra, prov))
    c.commit()
    c.close()
    # conftest 的 _isolate_recent_flights 会把模块函数替换成 {}（防测试
    # 读生产库）；这里要测函数本体，走同仓惯例的 raw 别名。
    fn = getattr(report, "_recent_platform_flights_raw",
                 report.recent_platform_flights)
    out = fn(db, "SHA", "BKK", "2026-11-16", hours=24 * 365 * 100)
    assert "ctrip" in out, out
    _age, rows = out["ctrip"]
    assert rows and rows[0]["_prov"] == prov
    assert rows[0]["_row_id"] == 1
