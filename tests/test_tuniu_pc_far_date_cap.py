# -*- coding: utf-8 -*-
"""途牛 PC 远日期不查：软风控下只跑近 30 天，远日期交给 H5/API。

用户 2026-11-02 复登后实测：PC 重新搜索会出滑块，通过后仍空结果；
建议不要查太远日期。采集端保留 PC 通路，但把远日期切给 H5/API，
并写 unsupported 证据，避免一次高风险请求被误记成没有航班。
"""
import datetime as dt
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.tuniu import TuniuCrawler  # noqa: E402


def test_split_pc_dates_keeps_near_and_moves_far():
    today = dt.date(2026, 11, 2)
    near, far = TuniuCrawler._split_pc_dates(
        ["2026-11-02", "2026-11-30", "2026-12-02", "2026-12-03",
         "2027-01-20"], today=today)
    assert near == ["2026-11-02", "2026-11-30", "2026-12-02"], near
    assert far == ["2026-12-03", "2027-01-20"], far


def test_split_pc_dates_keeps_unparseable_dates():
    near, far = TuniuCrawler._split_pc_dates(
        ["not-a-date", "2026-11-02"], today=dt.date(2026, 11, 2))
    assert "not-a-date" in near and far == [], (near, far)


def test_fetch_applies_pc_window_and_leaves_evidence():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("def fetch(")
    body = src[i:src.index("\n    def ", i + 10)]
    assert "_split_pc_dates(dates)" in body
    assert "PC_MAX_AHEAD_DAYS" in body
    assert "远日期走 H5/API" in body
    assert "PC\", \"unsupported\"" in body, (
        "远日期跳过 PC 没有 unsupported 证据，账本看不出为什么没查")
    assert src.count("self._fetch_pc_dom(fc, tc, _pc_dates)") == 1
