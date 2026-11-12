# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r323_daily_bucket_kind.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as _dt
import json
import os
import sys

from core.models import FlightPrice
from core.storage import PriceStorage


# ---- merged from tests/test_r323_daily_bucket_kind.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DAY = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
_MD = _DAY[5:]          # 面板口径的 MM-DD


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


def test_sub_band_price_never_enters_daily_bucket(tmp_path):
    """¥20 优惠卡不得成为日桶 lo/close（2026-11-03 生产实证）。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp(20.0, [_elem(20.0, "", "")], _DAY + " 08:00:00"),
        _fp(500.0, [_elem(500.0, "MU1")], _DAY + " 09:00:00"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day=_DAY)
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    assert len(d) == 1, d
    assert d[0]["lo"] >= 100.0, d


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
            _DAY + " 08:00:00", code="UQ2599"),
        # 混装行2：行价 1369（=转元素 min），元素 1710 直 + 1369 转
        _fp(1369.0, [_elem(1710.0, "CZ6400"),
                     _elem(1369.0, "MU5800", trans_city="兰州")],
            _DAY + " 12:00:00", code="CZ6400"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day=_DAY)
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
        _fp(1710.0, [_elem(1710.0, "CZ1")], _DAY + " 08:00:00",
            code="CZ1"),
        _fp(1369.0, [_elem(1369.0, "MU1", trans_city="兰州"),
                     _elem(1500.0, "MU2", trans_city="兰州")],
            _DAY + " 12:00:00", code="MU1"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day=_DAY)
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    t = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["n"] == 1 and d[0]["lo"] == 1710.0, d
    assert len(t) == 1 and t[0]["n"] == 2 and t[0]["lo"] == 1369.0, t


def test_direct_row_extra_array_stays_d(tmp_path):
    """直飞行（元素无 transCity）仍入 'd' 桶。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp(1500.0, [_elem(1500.0, "CZ1")], _DAY + " 08:00:00"),
        _fp(1400.0, [_elem(1400.0, "CZ2")], _DAY + " 12:00:00",
            code="CZ2"),
    ])
    st.refresh_daily("URC", "SHA", "2026-11-01", day=_DAY)
    d = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="d")
    t = st.daily_series("URC", "SHA", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["n"] == 2, d
    assert d[0]["lo"] == 1400.0 and d[0]["close"] == 1400.0, d
    assert t == [], t
