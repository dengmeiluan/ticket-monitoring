# -*- coding: utf-8 -*-
"""用**真机实测坐标**验证「列标定 + 外推」能把漏读的日号补对。

数据来自 2026-11-05 抓到的 12 月日历 OCR（1260×2800）：
    表头 12月 y=697
    第 1 行日号 y=852：1,2,3,4,5 在 x=446/615/786/957/1130
    该行价格 y=923：380/380/380/400/364
    第 2 行日号 y=1054：6,7,8,9 在 x=102/272/444/615   ← 只读到 4 个
    第 3 行价格 y=1125：400/400/394/379/380/400/380（7 列全有价）

2026-12-01 是**周二**，落在第 3 列（日一二三四五六），
所以列 0/1 属于 11 月 —— 外推必须把它们判成越界，不能算成 12 月。
"""
from datetime import date

from crawlers.app_fliggy_parse import parse_calendar_prices

_MONTHS = [(2026, 12, 697.0)]
#: 实测列中心（周日→周六）
_COLS = (104, 275, 446, 617, 788, 959, 1130)
_TODAY = date(2026, 11, 5)


def _t(txt, x, y, w=40, h=40):
    return {"t": txt, "x": x, "y": y, "w": w, "h": h}


def _real_dec_calendar():
    w = []
    # 第 1 行：日号 1..5（第 3..6 列）
    for d, x in zip((1, 2, 3, 4, 5), (426, 595, 766, 937, 1110)):
        w.append(_t(str(d), x, 852))
    for v, x in zip((380, 380, 380, 400, 364),
                    (422, 593, 765, 936, 1107)):
        w.append(_t("¥", x - 20, 923, 20, 30))
        w.append(_t(str(v), x, 923, 50, 30))
    # 第 2 行：日号只有 6..9（第 1..4 列）
    for d, x in zip((6, 7, 8, 9), (82, 252, 424, 595)):
        w.append(_t(str(d), x, 1054))
    # 第 3 行（价格行）：7 列全有价，日号一个都没读出来
    for v, x in zip((400, 400, 394, 379, 380, 400, 380),
                    (79, 251, 422, 593, 765, 936, 1107)):
        w.append(_t("¥", x - 20, 1125, 20, 30))
        w.append(_t(str(v), x, 1125, 50, 30))
    return w


def test_calibrated_extrapolation_fills_missing_week():
    rows = parse_calendar_prices(_real_dec_calendar(), _MONTHS,
                                 today=_TODAY, extrapolate=True, cols=_COLS)
    got = {r["date"]: r["price"] for r in rows}
    # 1..12 号都应该有价（10/11/12 靠外推补出来）
    for d in range(1, 13):
        assert "2026-12-%02d" % d in got, sorted(got)
    # 具体价对得上：6..9 来自日号行，10..12 来自外推
    assert got["2026-12-06"] == 400.0
    assert got["2026-12-08"] == 394.0
    assert got["2026-12-10"] == 380.0
    assert got["2026-12-12"] == 380.0


def test_extrapolation_does_not_leak_into_previous_month():
    """列 0/1 属于 11 月（12-01 是周二），不能算出 12 月 0 号/-1 号。"""
    rows = parse_calendar_prices(_real_dec_calendar(), _MONTHS,
                                 today=_TODAY, extrapolate=True, cols=_COLS)
    assert all(r["date"].startswith("2026-11") or
               r["date"].startswith("2026-12") for r in rows)
    assert all(1 <= int(r["date"][-2:]) <= 31 for r in rows)


def test_without_calibration_extrapolation_stays_off_scope():
    """不传 cols 时（未标定屏幕），外推段不应生效到不可信范围。"""
    rows = parse_calendar_prices(_real_dec_calendar(), _MONTHS,
                                 today=_TODAY, extrapolate=True)
    got = {r["date"] for r in rows}
    # 日号读到的 1..9 必须还在
    for d in range(1, 10):
        assert "2026-12-%02d" % d in got, sorted(got)
