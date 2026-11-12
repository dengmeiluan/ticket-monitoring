# -*- coding: utf-8 -*-
"""r1063 T149：途牛 `PC·周历` 通路（列表空/被拦时照样出价）。

实测（2026-11-09）：
```
flight.tuniu.com/domestic/list/SHA_BJS_ST_1_0_0/?start=2026-11-16
  页面标题正常、正文 2081 字
  列表：「很抱歉，暂未查询到符合您要求的航班。」
  顶部周历：11-13 ￥470 / 11-14 ￥380 / 11-15 ￥500 / 11-16 ￥388 / 11-17 ￥380 …
```
→ "列表空" ≠ "没价"。周历做成**独立通路** `PC·周历`，与列表分开记账。

实测兜底链路（真跑到）：
```
c.fetch('SHA','BJS',['2026-11-16']) → 1 行 ¥388，last_path = PC·周历
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_week_dates_same_year_takes_min_price():
    d = TuniuCrawler._week_to_dates(
        "2026-11-16", [("11-13", 470), ("11-16", 388), ("11-16", 380)])
    assert d["2026-11-13"] == 470
    assert d["2026-11-16"] == 380, "同一日期要取最低价"


def test_week_dates_cross_year():
    d = TuniuCrawler._week_to_dates("2026-12-30", [("01-02", 999)])
    assert d == {"2027-01-02": 999}


def test_week_dates_ignores_dirty_rows():
    assert TuniuCrawler._week_to_dates(
        "2026-11-16", [("bad", 1), (None, 2), ("11-20", "x")]) == {}


def test_switch_default_off_and_config_on():
    """r1063 T154：代码默认**关闭**（单测不联网），生产由 config 显式打开。"""
    import logging
    assert TuniuCrawler({}, logging.getLogger("t"))._week_calendar_enabled() is False
    assert TuniuCrawler({"tuniu_week_calendar": True},
                        logging.getLogger("t"))._week_calendar_enabled() is True


def test_wired_as_independent_path():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    assert '"PC·周历"' in src, "周历必须是独立通路（单独进账本/面板）"
    assert "_fetch_week_calendar" in src
    # fetch 里必须有"列表/接口都没数时的兜底"
    i = src.index("def fetch(self, from_city")
    seg = src[i:src.index("def _split_pc_dates", i) if
              "def _split_pc_dates" in src[i:] else i + 12000]
    assert "_fetch_week_calendar" in seg, seg[-500:]
