# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r656_daily_bucket_accepts_app_extra.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sqlite3
import sys
import tempfile

from core.models import FlightPrice
from core.storage import PriceStorage
from datetime import datetime


# ---- merged from tests/test_r656_daily_bucket_accepts_app_extra.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    # day 必须是**写入当天**：refresh_daily 按 fetched_at 落在 [day 00:00,
    # day 23:59] 过滤，写死某一天则第二天起窗口永远落空 —— 断言会以
    # 「对象型 extra 没进日桶」的形式误报，看似功能坏了，其实是测试过期。
    day = datetime.now().strftime("%Y-%m-%d")
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
    st.refresh_daily("SHA", "CAN", "2026-12-04",
                     datetime.now().strftime("%Y-%m-%d"))
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
    st.refresh_daily("SHA", "CAN", "2026-12-04",
                     datetime.now().strftime("%Y-%m-%d"))
    con = sqlite3.connect(st.db_path)
    n = con.execute("SELECT n FROM price_daily WHERE kind='d'").fetchone()
    con.close()
    assert n and n[0] == 2, n
