# -*- coding: utf-8 -*-
"""携程 App 价格日历 OCR 解析（真机截图 OCR 词块夹具）。"""
import json
import os
from datetime import date

from crawlers.app_ctrip_calendar import parse_calendar_words

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "ctrip_calendar_ocr.json")
INTL_FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                            "ctrip_calendar_intl_ocr.json")


def _rows():
    with open(FIXTURE, encoding="utf-8") as f:
        words = json.load(f)
    return parse_calendar_words(words, today=date(2026, 11, 2))


def _intl_rows():
    with open(INTL_FIXTURE, encoding="utf-8") as f:
        words = json.load(f)
    return parse_calendar_words(words, today=date(2026, 11, 2))


def test_parses_three_months_from_real_ocr():
    rows = _rows()
    by = {r["date"]: r for r in rows}
    assert len(rows) == 62
    assert len(by) == 62, "日期重复"
    # 11 月：2 号今天 ¥420、3 号 OCR 把 390 认成 3g0 也要还原
    assert by["2026-11-02"]["price"] == 420.0
    assert by["2026-11-02"]["weekday"] == "今天"
    assert by["2026-11-03"]["price"] == 390.0
    assert by["2026-11-03"]["weekday"] == "明天"
    assert by["2026-11-08"]["price"] == 350.0
    assert by["2026-11-30"]["price"] == 410.0
    # 12 月 / 次年 1 月没有被 11 月覆盖
    assert by["2026-12-01"]["price"] == 400.0
    assert by["2026-12-31"]["price"] == 490.0
    assert by["2027-01-01"]["price"] == 400.0
    assert by["2027-01-02"]["price"] == 400.0
    assert [r["date"] for r in rows] == sorted(by)


def test_intl_calendar_uses_actual_row_pitch_and_merges_split_price():
    """国际档日历行距 107px（国内 88px），OCR 还会把 1001 拆成 1+001。

    截图为 2026-11-02 真机 SHA→NRT 弹层：可见 11 月整月 + 12 月到 26 日，
    12-27 之后的格子在屏幕外，不能凭最后一行反推。
    """
    rows = _intl_rows()
    by = {r["date"]: r for r in rows}
    assert len(rows) == 54, "应有 11-03..11-30 + 12-01..12-26"
    assert len(by) == 54, "日期重复"
    assert by["2026-11-03"]["price"] == 1345.0
    # 这一周（11-22..28）行距漂移曾整周丢失
    assert by["2026-11-22"]["price"] == 1068.0
    assert by["2026-11-28"]["price"] == 969.0
    assert by["2026-11-30"]["price"] == 949.0
    assert by["2026-12-01"]["price"] == 928.0
    assert by["2026-12-20"]["price"] == 901.0
    # ¥1 是把 ¥1001 拆成 1 + 001 后只取了后一段
    assert by["2026-12-22"]["price"] == 1001.0
    assert by["2026-12-26"]["price"] == 1166.0
    assert "2026-12-27" not in by, "屏幕外日期不能造"
    assert [r["date"] for r in rows] == sorted(by)


def test_empty_or_non_calendar_input_returns_empty():
    assert parse_calendar_words([], today=date(2026, 11, 2)) == []
    assert parse_calendar_words(
        [{"t": "机票", "x": 10, "y": 10, "w": 20, "h": 10}],
        today=date(2026, 11, 2)) == []
    # 有月份标题但没有价格 → 不造日期
    only_head = [{"t": "2026", "x": 25, "y": 361, "w": 58, "h": 21},
                 {"t": "年", "x": 85, "y": 361, "w": 25, "h": 27},
                 {"t": "11", "x": 113, "y": 361, "w": 28, "h": 20},
                 {"t": "月", "x": 142, "y": 361, "w": 22, "h": 25}]
    assert parse_calendar_words(only_head, today=date(2026, 11, 2)) == []
