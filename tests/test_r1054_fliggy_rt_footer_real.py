# -*- coding: utf-8 -*-
"""往返日历底栏解析：用**真机截图 OCR** 锁住「不只取最后一行」这条修复。

2026-11-06 真机实证（1260×2800，fixture 为原始词块）：

    y≈2500  去程：11月16日   返程：11月19日   往返总价 ¥747
    y≈2700  [ 确定 ]

原实现只取 `rows[max(rows)]`（y 最大的那一行）→ 拿到「确定」按钮那行，
里面没有「去程/返程」→ dep/ret 全 None → 校验必然失败，
而截图里两个日期其实都已正确选中（当天实测报「落点不符：期望
11-16/11-19，实际 未选择/未选择」）。
"""
import io
import json
import os

from crawlers.app_fliggy_parse import parse_round_trip_footer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "fliggy_rt_calendar_words.json")


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_reads_both_dates_and_total_from_real_screenshot():
    got = parse_round_trip_footer(_words())
    assert got["dep"] == (11, 16), got
    assert got["ret"] == (11, 19), got
    assert got["total"] == 747.0, got


def test_confirm_button_row_does_not_mask_footer():
    """把「确定」按钮那一行单独喂进去，必须读不到日期（证明它确实没这些词）。"""
    words = _words()
    lowest = max(w["y"] for w in words)
    only_bottom = [w for w in words if abs(w["y"] - lowest) <= 18]
    got = parse_round_trip_footer(only_bottom)
    assert got["dep"] is None and got["ret"] is None
