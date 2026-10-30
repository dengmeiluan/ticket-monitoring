# -*- coding: utf-8 -*-
"""r656：日桶必须能吃 App 渠道的 extra（对象型），否则 App 数据进不了趋势。

背景（真机实测）：智行 App 写库的 extra 是 **JSON 对象**
`{"calendar": false, "source": "app-list"}`，而浏览器渠道是 **JSON 数组**。
`refresh_daily` 里直接 `json_each(fp.extra)` 遇到对象会让整条 SQL 抛
`sqlite3.OperationalError: malformed JSON`——采集日志一切正常（「得到 8 条记录」），
但日桶一条都没写，趋势图/日报全是空，且只留下一行 ERROR。

修法：按 json_type 分流——数组逐元素展开（浏览器语义不变），
非数组用 price 列（App 语义）。
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import FlightPrice
from core.storage import PriceStorage


def _storage():
    d = tempfile.mkdtemp()
    return PriceStorage(os.path.join(d, "t.db"))


def _fp(price, extra):
    return FlightPrice(platform="app_zhixing", from_city="SHA",
                       to_city="CAN", depart_date="2026-12-04",
                       price=float(price), extra=extra)


def test_object_extra_does_not_break_daily_bucket():
    """App 的对象型 extra 不能让整条聚合 SQL 崩溃。"""
    st = _storage()
    st.save_many([
        _fp(349, '{"calendar": false, "source": "app-list"}'),
        _fp(380, '{"calendar": false, "source": "app-list"}'),
    ])
    day = "2026-10-30"
    st.refresh_daily("SHA", "CAN", "2026-12-04", day)   # 不该抛
    con = sqlite3.connect(st.db_path)
    rows = con.execute(
        "SELECT kind, n, lo, hi FROM price_daily "
        "WHERE from_city='SHA' AND to_city='CAN'").fetchall()
    con.close()
    assert rows, "对象型 extra 没进日桶"
    kind, n, lo, hi = rows[0]
    assert n == 2 and lo == 349 and hi == 380, rows


def test_array_extra_still_expands_per_element():
    """浏览器渠道的数组语义不能被改坏（逐元素、可区分中转）。"""
    st = _storage()
    st.save_many([_fp(300, '[{"price": 310, "transCity": ""},'
                            '{"price": 450, "transCity": "WUH"}]')])
    st.refresh_daily("SHA", "CAN", "2026-12-04", "2026-10-30")
    con = sqlite3.connect(st.db_path)
    rows = dict((k, (n, lo, hi)) for k, n, lo, hi in con.execute(
        "SELECT kind, n, lo, hi FROM price_daily").fetchall())
    con.close()
    assert rows.get("d", (None,))[0] == 1, rows      # 直飞 1 条
    assert rows["d"][1] == 310, rows
    assert rows.get("t", (None,))[0] == 1, rows      # 中转 1 条
    assert rows["t"][1] == 450, rows


def test_mixed_shapes_in_one_bucket():
    """两种形态混在同一航线同一天时都要算进去。"""
    st = _storage()
    st.save_many([
        _fp(300, '[{"price": 300, "transCity": ""}]'),
        _fp(360, '{"calendar": false}'),
    ])
    st.refresh_daily("SHA", "CAN", "2026-12-04", "2026-10-30")
    con = sqlite3.connect(st.db_path)
    n = con.execute("SELECT n FROM price_daily WHERE kind='d'").fetchone()
    con.close()
    assert n and n[0] == 2, n
