# -*- coding: utf-8 -*-
"""日历「按日号 OCR 直接定位」的单元测试。

为什么走 OCR 而不是几何：几何推算法两条独立来源都算对
（`22..28 @ y=1458`、`29,30 @ y=1660` → 行距 202、首行 852），
但按它点下去日期不变；而日号本身是能被 OCR 读出来的
（实测 `22 x=83 y=1458`），直接点它的中心最稳、与滚动无关。

坐标取自 2026-11-05 真机实测（1260×2800）：
    11 月表头 y=697，12 月表头 y=1830；
    22..28 在 y≈1458（x 83/255/426/598/769/940/1112），29,30 在 y≈1660。
"""
from crawlers.app_fliggy import _cal_day_xy_by_ocr

_MONTHS = [(2026, 11, 697.0), (2026, 12, 1830.0)]
_COLS = (83, 255, 426, 598, 769, 940, 1112)


def _w(t, x, y, ww=40, hh=40):
    return {"t": t, "x": x, "y": y, "w": ww, "h": hh}


def _row(days, y, cols=_COLS):
    return [_w(str(d), x, y) for d, x in zip(days, cols)]


def _nov():
    return (_row((22, 23, 24, 25, 26, 27, 28), 1458)
            + [_w("29", 83, 1660), _w("30", 255, 1660)])


def test_finds_day_by_number():
    xy = _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 23, _MONTHS)
    assert xy is not None
    # 23 号在 x=255 那一列，中心 = 255 + 40/2
    assert xy[0] == 275
    assert 1458 <= xy[1] <= 1498


def test_finds_last_row_day():
    xy = _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 29, _MONTHS)
    assert xy is not None
    assert 1660 <= xy[1] <= 1700


def test_missing_day_returns_none():
    assert _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 15, _MONTHS) is None


def test_day_outside_month_band_is_ignored():
    """12 月的日号不能被当成 11 月的（区间按表头切）。"""
    words = _nov() + _row((1, 2, 3, 4, 5, 6, 7), 2390)
    # 11 月区间里不存在 3 号 → 必须 None，不能跨月误取
    assert _cal_day_xy_by_ocr(None, words, 2026, 11, 3, _MONTHS) is None
    # 12 月区间里 3 号存在
    assert _cal_day_xy_by_ocr(None, words, 2026, 12, 3, _MONTHS) is not None


def test_three_digit_price_is_not_a_day():
    """价格（如 820）不能当日号用——只接受 ≤2 位、1..31。"""
    words = [_w("820", 83, 1458), _w("950", 255, 1458),
             _w("700", 426, 1458), _w("680", 598, 1458),
             _w("21", 769, 1458)]
    # 820/950/700/680 都被排除，只剩 21 一个，行内不足 4 个 → 不应命中 820
    assert _cal_day_xy_by_ocr(None, words, 2026, 11, 21, _MONTHS) is not None
    xy = _cal_day_xy_by_ocr(None, words, 2026, 11, 21, _MONTHS)
    assert 769 <= xy[0] <= 809


def test_no_months_returns_none():
    assert _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 23, []) is None
