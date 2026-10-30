# -*- coding: utf-8 -*-
"""price_daily 元素级分桶钉（r323 观测立案修复）。

生产 flight_prices 行=渠道×查询、extra 元素=航班明细，全库 7,372 行
混装（同 row 直飞+中转元素并存，extra 元素数组形态 127,677 元素
price 键 100% 在场）——**行级分桶不良定义**，唯一正确粒度是元素级：
每元素按自身 transCity 归桶、元素 price 参与聚合，行价列不参与。
`$.transCity` 根路径对数组恒 NULL（第一代缺陷：42 桶全 'd'、直飞桶
被中转组合价污染）；「any 元素带 transCity 整行判转」（第二代缺陷：
混装行的直飞元素被错误卷进中转桶）皆在本钉射程内。fixture 一律按
生产混装形态构造。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r323_daily_bucket_kind.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def _elem(price, code, trans_city=None):
    el = {"price": price, "code": code, "name": code,
          "depTime": "08:00", "arrTime": "11:00"}
    if trans_city is not None:
        el["transCity"] = trans_city
    return el


def _fp(price, elements, fetched, frm="URC", to="SHA",
        date="2026-11-01", code="MU1"):
    return FlightPrice(
        platform="qunar", from_city=frm, to_city=to,
        depart_date=date, price=price, airline="", flight_no=code,
        depart_time="08:00", arrive_time="11:00",
        extra=json.dumps(elements, ensure_ascii=False),
        fetched_at=fetched)


def test_mixed_row_elements_split_buckets(tmp_path):
    """混装行按元素归桶：d 收直元素价、t 收中转元素价，行价列不参与。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        # 混装行1：行价 1624（=直元素 min），元素 1624 直（键缺席）+
        # 1980 直（空串 transCity——部分渠道行构造器恒写键的生产实证
        # 形态，全库 62,413 元素）+ 1970 转
        _fp(1624.0, [_elem(1624.0, "UQ2599"),
                     _elem(1980.0, "HU7887", trans_city=""),
                     _elem(1970.0, "GS7511", trans_city="兰州")],
            "2026-10-10 08:00:00", code="UQ2599"),
        # 混装行2：行价 1369（=转元素 min），元素 1710 直 + 1369 转
        _fp(1369.0, [_elem(1710.0, "CZ6400"),
                     _elem(1369.0, "MU5800", trans_city="兰州")],
            "2026-10-10 12:00:00", code="CZ6400"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day="2026-10-10")
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    t = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="t")
    assert len(d) == 1, d
    assert d[0]["n"] == 3 and d[0]["lo"] == 1624.0 \
        and d[0]["hi"] == 1980.0, d
    assert len(t) == 1, t
    assert t[0]["n"] == 2 and t[0]["lo"] == 1369.0 \
        and t[0]["hi"] == 1970.0, t


def test_single_kind_rows_still_bucket(tmp_path):
    """单一形态行（纯直飞/纯中转元素）仍各归各桶——分桶粒度迁移零回归。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp(1710.0, [_elem(1710.0, "CZ1")], "2026-10-10 08:00:00",
            code="CZ1"),
        _fp(1369.0, [_elem(1369.0, "MU1", trans_city="兰州"),
                     _elem(1500.0, "MU2", trans_city="兰州")],
            "2026-10-10 12:00:00", code="MU1"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day="2026-10-10")
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    t = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["n"] == 1 and d[0]["lo"] == 1710.0, d
    assert len(t) == 1 and t[0]["n"] == 2 and t[0]["lo"] == 1369.0, t


def test_direct_row_extra_array_stays_d(tmp_path):
    """直飞行（元素无 transCity）仍入 'd' 桶。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp(1500.0, [_elem(1500.0, "CZ1")], "2026-10-10 08:00:00"),
        _fp(1400.0, [_elem(1400.0, "CZ2")], "2026-10-10 12:00:00",
            code="CZ2"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day="2026-10-10")
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    t = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["n"] == 2, d
    assert d[0]["lo"] == 1400.0 and d[0]["close"] == 1400.0, d
    assert t == [], t
