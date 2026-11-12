# -*- coding: utf-8 -*-
"""r1063 T150：`PC·周历` 抽象成公共件，并给携程接上。

真机实测（2026-11-09）：
```
携程国际 SHA→TYO 2026-11-16 周历：11-13 ¥1412 / 11-14 ¥1575 / 11-15 ¥1392 / 11-16 ¥1200
携程国内 SHA→BJS 2026-11-16 周历：11-13 ¥500 / 11-14 ¥420 / 11-15 ¥360 / 11-16 ¥400
兜底：_fetch_core 返回空 → fetch() 仍返回 1 行 ¥1200（source=pc_week_calendar）
```

要点：抽取只认文本形态 `MM-DD 周X ￥NNN`，不依赖 class；日期换算支持跨年；
脏数据跳过不抛（一条脏数据不该让整周兜底失效）。
"""
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers import week_calendar as WC  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_week_to_dates_same_year_min_price():
    d = WC.week_to_dates("2026-11-16", [("11-13", 1412), ("11-16", 1200),
                                        ("11-16", 1300)])
    assert d["2026-11-13"] == 1412
    assert d["2026-11-16"] == 1200, "同日取最低"


def test_week_to_dates_cross_year():
    assert WC.week_to_dates("2026-12-30", [("01-02", 999)]) == \
        {"2027-01-02": 999}


def test_week_to_dates_dirty_rows_never_raise():
    assert WC.week_to_dates("2026-11-16",
                            [("x", 1), (None, 2), ("11-20", "y")]) == {}
    assert WC.week_to_dates("bad", []) == {}


def test_ctrip_inherits_mixin_and_has_switch():
    assert issubclass(CtripCrawler, WC.WeekCalendarMixin)
    c = CtripCrawler({}, logging.getLogger("t"))
    # r1063 T154：代码默认关闭（单测不联网），生产由 config 显式打开
    assert c._week_calendar_enabled() is False
    on = CtripCrawler({"ctrip_week_calendar": True}, logging.getLogger("t"))
    assert on._week_calendar_enabled() is True


def test_ctrip_fetch_wraps_core_and_fills_week():
    """fetch() 必须是"核心采集 + 周历兜底"，核心采集改名为 _fetch_core。"""
    src = io.open(os.path.join(ROOT, "crawlers", "ctrip.py"),
                  encoding="utf-8").read()
    assert "def _fetch_core(" in src
    i = src.index("def fetch(self, from_city")
    seg = src[i:i + 500]
    assert "_fetch_core" in seg and "_fill_week" in seg
    assert '"PC·周历"' in src, "周历必须是独立通路"


def test_fliggy_inherits_mixin_and_skips_domestic():
    """飞猪：国际接周历兜底；国内页实测没有"周X ￥N"形态，必须跳过不浪费请求。"""
    from crawlers.fliggy import FliggyCrawler
    assert issubclass(FliggyCrawler, WC.WeekCalendarMixin)
    src = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                  encoding="utf-8").read()
    i = src.index("def _fill_week")
    seg = src[i:i + 2200]
    assert "is_intl_route" in seg, "国内必须跳过周历（无此结构）"
    assert "PC·周历" in seg


def test_week_js_tolerates_parenthetical_marker():
    """飞猪的日期条形态是 `11-16 周一(去) ¥282`——正则必须容忍括号后缀。"""
    assert "[（(]" in WC.WEEK_JS, "正则没容忍括号标记，飞猪会抽不到"
