# -*- coding: utf-8 -*-
"""飞猪价格日历（低价源）解析：日号 + 下方价格的对齐。

坐标全部来自 2026-11-05 在 1260×2800 真机上量到的值：
    11 月表头 y=697，日号行 y=1458（列 x 83/255/426/598/769/940/1112），
    价格行 y=1528（比日号低 ~70px）；无价的日子 OCR 出来是「查看」。
"""
from datetime import date

from crawlers.app_fliggy_parse import parse_calendar_prices

_MONTHS = [(2026, 11, 697.0), (2026, 12, 1830.0)]
_COLS = (83, 255, 426, 598, 769, 940, 1112)
_TODAY = date(2026, 11, 5)


def _tok(t, x, y, w=40, h=40):
    return {"t": t, "x": x, "y": y, "w": w, "h": h}


def _day_row(days, y=1458, cols=_COLS):
    out = []
    for d, x in zip(days, cols):
        out.append(_tok(str(d), x, y))
    return out


def test_reads_price_under_day():
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30),     # 22 下方
              _tok("950", 955, 1528, 60, 30)]    # 27 下方
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    got = {r["date"]: r["price"] for r in rows}
    assert got == {"2026-11-22": 820.0, "2026-11-27": 950.0}


def test_view_text_means_no_price():
    """「查看」不是价格；该日不进结果（不能编造 0 元）。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("查看", 426, 1528, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_price_far_below_is_not_matched():
    """价格必须在日号下方 25..130px；太远的是下一行的价，不能张冠李戴。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1458 + 300, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_past_days_are_skipped():
    words = _day_row((1, 2, 3, 4, 5, 6, 7))
    words += [_tok("700", 83, 1528, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_nearest_price_below_wins_in_one_cell():
    """同一格内取**最靠近日号**的那个价格（不是最低价）。

    真实日历每格只有一个价；出现两个数字时（如价格 + 折扣角标），
    离日号最近的那个才是当日最低价。
    """
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30),
              _tok("790", 96, 1600, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["price"] for r in rows] == [820.0]


def test_duplicate_date_across_screens_takes_lowest():
    """同一日期在两屏里都读到（滚动重叠），取更低的价格。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30)]
    # 同一屏里 22 号又被读到一次（把它放在 11 月区间内的另一行）
    words += _day_row((22, 23, 24, 25, 26, 27, 28), y=1250)
    words += [_tok("790", 98, 1320, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["price"] for r in rows] == [790.0]


def test_second_month_band_is_used():
    """第二个月（12 月）的日号必须归到 12 月，不能记成 11 月。"""
    words = _day_row((1, 2, 3, 4, 5, 6, 7), y=2390)
    words += [_tok("680", 83, 2460, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["date"] for r in rows] == ["2026-12-01"]


def test_no_months_returns_empty():
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    assert parse_calendar_prices(words, []) == []


def test_row_needs_at_least_four_days():
    """少于 4 个日号的一行不算日号行（价格行/零碎数字会被排除）。"""
    words = [_tok("8", 83, 1458), _tok("9", 255, 1458)]
    words += [_tok("820", 98, 1528, 60, 30)]
    assert parse_calendar_prices(words, _MONTHS, today=_TODAY) == []


def test_last_row_with_two_days_keeps_its_price():
    """月份最后一行常常只有 1–2 天（11 月 29/30），它的价格不能丢。

    这类日期往往就是月底/节假日的高价位，丢了会让日历价系统性偏低。
    「向下补一行」的规则专门处理这个。
    """
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("29", 83, 1660), _tok("30", 255, 1660)]
    words += [_tok("740", 98, 1730, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    got = {r["date"]: r["price"] for r in rows}
    assert got.get("2026-11-29") == 740.0
