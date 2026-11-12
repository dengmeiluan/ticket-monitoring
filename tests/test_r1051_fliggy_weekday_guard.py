# -*- coding: utf-8 -*-
"""日历「星期列校验」：错了要拒绝，不能记错日期。

背景：日历外推是**推断**。一旦列映射偏一列，就会把 11-08 的价记成 11-09，
账本上完全看不出来 —— 比缺数据危险。日历有硬约束：某天必然落在它星期几
对应的那一列（周日在前），用这条就能把错位推断挡掉。
"""
from datetime import date

from crawlers.app_fliggy_parse import parse_calendar_prices, weekday_col

#: 实测列中心（周日→周六）
_COLS = (104, 275, 446, 617, 788, 959, 1130)
_MONTHS = [(2026, 12, 697.0)]
_TODAY = date(2026, 11, 5)


def test_weekday_col_known_dates():
    # 2026-12-01 周二 → 第 3 列（列 0 = 周日）
    assert weekday_col(2026, 12, 1) == 2
    # 同日星期几的日期必然同列
    assert weekday_col(2026, 12, 8) == 2
    assert weekday_col(2026, 12, 15) == 2
    # 2026-11-16 周一 → 第 2 列
    assert weekday_col(2026, 11, 16) == 1


def _t(txt, x, y, w=40, h=40):
    return {"t": txt, "x": x, "y": y, "w": w, "h": h}


def _anchor_plus_shifted_price_row(shift=0):
    """锚行 1..5（第 3..7 列，星期一致）+ 一行价格（可整体右移 shift 列）。"""
    w = []
    for d, x in zip((1, 2, 3, 4, 5), (426, 595, 766, 937, 1110)):
        w.append(_t(str(d), x, 852))
    for v, x in zip((380, 380, 380, 400, 364), (422, 593, 765, 936, 1107)):
        w.append(_t("¥", x - 20, 923, 20, 30))
        w.append(_t(str(v), x, 923, 50, 30))
    # 第二周只有价格
    for i, x in enumerate(_COLS):
        xx = _COLS[min(6, max(0, i + shift))]
        w.append(_t("¥", xx - 20, 1125, 20, 30))
        w.append(_t(str(400 + i), xx, 1125, 50, 30))
    return w


def test_aligned_rows_are_accepted():
    rows = parse_calendar_prices(_anchor_plus_shifted_price_row(0),
                                 _MONTHS, today=_TODAY, extrapolate=True,
                                 cols=_COLS)
    got = {r["date"] for r in rows}
    # 第二周 8..14 应被补齐
    assert any(d.startswith("2026-12-1") for d in got)


def test_values_stay_inside_the_month():
    """无论推断如何，绝不能产出别的月份或非法日号。"""
    for shift in (0, 1, -1):
        rows = parse_calendar_prices(_anchor_plus_shifted_price_row(shift),
                                     _MONTHS, today=_TODAY,
                                     extrapolate=True, cols=_COLS)
        for r in rows:
            assert r["date"].startswith("2026-12-")
            assert 1 <= int(r["date"][-2:]) <= 31
            assert r["price"] >= 50
