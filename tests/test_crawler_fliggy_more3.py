# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1048_fliggy_cal_cols.py
- tests/test_r1051_fliggy_weekday_guard.py
- tests/test_v177_fliggy_cabin.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

from crawlers.app_fliggy_parse import parse_calendar_prices, weekday_col
from crawlers.fliggy import FliggyCrawler
from datetime import date


# ---- merged from tests/test_r1048_fliggy_cal_cols.py ----

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


# ---- merged from tests/test_r1051_fliggy_weekday_guard.py ----

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


# ---- merged from tests/test_v177_fliggy_cabin.py ----

def _row(txt):
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert rows, txt
    return rows[0]


def test_fliggy_cabin_price_row_trailing_word():
    """价格行「¥9900 商务舱」行尾舱位词 → extra.cabin 落键。"""
    r = _row("海航HU7145\n中型机 788\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥9900 商务舱")
    assert r["cabin"] == "商务舱"
    assert r["price"] == 9900.0
    # 舱位词不含「N折」→ discount 不被误配
    assert "discount" not in r


def test_fliggy_cabin_fullprice_form_no_cabin():
    """「全价」满值形态：不落 cabin（宁缺勿错）；discount 落「全价」
    （无折扣可售真值，qunar/tuniu/tongcheng 同域同词面，消费端
    discount_txt 单源守卫放行）。"""
    r = _row("国航CA8564\n中型机 320\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥2400 全价")
    assert "cabin" not in r
    assert r["discount"] == "全价"


def test_fliggy_cabin_whole_line_branch_kept():
    """既有整行舱位词分支保持兼容；价格行舱位词不覆盖已有值。"""
    r = _row("海航HU7145\n中型机 788\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n"
             "商务舱\n¥9900 5.0折")
    assert r["cabin"] == "商务舱"
    assert r["discount"] == "5.0折"


def test_fliggy_cabin_dual_price_row_dropped():
    """双价行（跨舱位并列，CA8564「¥9900 商务舱/¥3960」谱系）：取低者
    为主价时必须撤 cabin——首价格行的舱位词不得标注来自第二行的低价，
    否则落库即成「商务舱 ¥3960」持久化误导。"""
    r = _row("国航CA8564\n中型机 320\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥9900 商务舱\n¥3960")
    assert r["price"] == 3960.0
    assert "cabin" not in r
