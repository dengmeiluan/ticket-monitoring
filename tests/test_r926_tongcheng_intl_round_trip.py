# -*- coding: utf-8 -*-
"""r926：同程 PC 国际往返只取渠道自己的含税总价（tp），不相加两段。"""
import json
import logging
import os

from crawlers.tongcheng import TongchengCrawler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tongcheng_intl_rt.json")


def _payload():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


def test_parser_uses_channel_total_not_sum():
    p = _payload()
    date, ret = "2026-11-20", "2026-11-23"
    rows = [TongchengCrawler._parse_intl_rt_entry(e, date, ret)
            for e in p["data"]["res"]]
    rows = [r for r in rows if r]
    assert len(rows) >= 40, "真实报文应解析出 40+ 条往返"
    best = min(rows, key=lambda r: r["price"])
    assert best["price"] == 1463.0
    assert best["flight"] == "HX231"
    assert best["returnFlight"] == "HX0234"
    assert best["basis"] == "product_round_trip_total"
    assert best["priceLabel"] == "往返含税总价"
    assert best["tripType"] == "RT"
    # 报表/明细消费端的标准键必须齐全，否则新往返行会在趋势/详情里变空白
    assert best["depTime"] == "07:40" and best["arrTime"] == "10:40"
    assert best["code"] == "HX231" and best["name"] == "香港航空"
    assert best["intl"] is True and best["date"] == "2026-11-20"
    assert best["totalBasis"] == "product_round_trip_total"
    # 进入告警/趋势同一行归一化链后，时刻/航班/国际标记不能丢
    from core.alerter import _flights_from_extra
    fl = _flights_from_extra(rows, date, "tongcheng")
    assert len(fl) == len(rows)
    assert fl[0]["depTime"] == "07:40" and fl[0]["arrTime"] == "10:40"
    assert fl[0]["code"] == "HX231" and fl[0]["intl"] is True
    raw = next(e for e in p["data"]["res"]
               if e.get("lng", "").startswith("HX0231_"))
    # tp 是页面含税总价；sp+tp 才是“两段相加”，必须不相等
    assert best["price"] == float(raw["tp"])
    assert best["price"] != float(raw["sp"]) + float(raw["tp"])


def test_parser_rejects_single_leg_or_wrong_return_date():
    p = _payload()
    e = dict(p["data"]["res"][0])
    date = "2026-11-20"
    bad = dict(e)
    bad.pop("lng", None)
    assert TongchengCrawler._parse_intl_rt_entry(bad, date, "2026-11-23") is None
    bad2 = dict(e)
    bad2["lng"] = "HX0231_20261120|HX0234_20261124"
    assert TongchengCrawler._parse_intl_rt_entry(bad2, date, "2026-11-23") is None


def test_intl_fetch_dispatches_to_rt_not_calendar():
    c = TongchengCrawler({"headless": True}, logging.getLogger("r926"))
    seen = {}

    def fake(fc, tc, dates, ret_date):
        seen["args"] = (fc, tc, dates, ret_date)
        return []

    c._fetch_intl_rt = fake
    assert c._fetch_intl("SHA", "HKG", ["2026-11-20"],
                         ret_date="2026-11-23") == []
    assert seen["args"] == ("SHA", "HKG", ["2026-11-20"], "2026-11-23")


def test_report_rounds_sees_rt_rows(tmp_path):
    """新往返行必须能进走势聚类，而不是被「时刻双空」整行丢掉。"""
    import sqlite3
    import time
    from report import _rounds

    p = _payload()
    rows = [TongchengCrawler._parse_intl_rt_entry(e, "2026-11-20",
                                                  "2026-11-23")
            for e in p["data"]["res"]]
    rows = [r for r in rows if r]
    db = tmp_path / "prices.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, "
                "platform TEXT, from_city TEXT, to_city TEXT, "
                "depart_date TEXT, price REAL, extra TEXT, fetched_at TEXT)")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con.execute("INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, extra, fetched_at) VALUES (?,?,?,?,?,?,?)",
                ("tongcheng", "SHA", "HKG", "2026-11-20", 1463.0,
                 json.dumps(rows, ensure_ascii=False), now))
    con.commit()
    con.close()
    pts = _rounds(str(db), "SHA", "HKG", "2026-11-20", 24, hours=2)
    assert pts, "走势聚类没有看到新的同程国际往返行"
    assert any(x[1] for x in pts) or any(x[2] for x in pts), pts

