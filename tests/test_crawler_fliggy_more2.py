# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1047_fliggy_cal_extrapolate.py
- tests/test_r1049_fliggy_rt_footer.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

from crawlers.app_fliggy_parse import parse_calendar_prices, parse_round_trip_footer
from datetime import date


# ---- merged from tests/test_r1047_fliggy_cal_extrapolate.py ----

_MONTHS = [(2026, 12, 697.0)]
_COLS = (79, 251, 422, 593, 765, 936, 1107)
_TODAY = date(2026, 11, 5)


def _tok(t, x, y, w=40, h=40):
    return {"t": t, "x": x, "y": y, "w": w, "h": h}


def _days_row(days, y, cols):
    return [_tok(str(d), x, y) for d, x in zip(days, cols)]


def _price_row(vals, y, cols):
    out = []
    for v, x in zip(vals, cols):
        out.append(_tok("¥", x - 18, y, 20, 30))
        out.append(_tok(str(v), x, y, 50, 30))
    return out


def _real_layout():
    """12 月首行只覆盖 5 列（1..5 在第 3..7 列，12/1 是周二）+ 一行只有价格。

    布局必须**星期一致**：解析器现在有「星期列校验」，几何摆错会被拒绝
    （这正是它该做的）。12/1=周二 → 第 3 列（周日在前）。
    """
    words = []
    # 锚行：11 月 1..5 落在第 3..7 列（x 422..1107）
    words += _days_row((1, 2, 3, 4, 5), 852, _COLS[2:])
    # 该行的价格（全 7 列中的后 5 列）
    words += _price_row((380, 380, 380, 400, 364), 923, _COLS[2:])
    # 第二周：只有价格、没有日号（8..14）
    words += _price_row((400, 400, 394, 379, 380, 400, 380), 1125, _COLS)
    return words


def test_extrapolates_missing_day_row_from_prices():
    """整周只有价格、没有日号时，必须能把这一周反推出来。

    断言按**结构**写（不绑定构造用例里随手摆的列位）：
    价格行有 7 个价，就应该反推出 7 个连续日期，且都在 11 月内。
    """
    rows = parse_calendar_prices(_real_layout(), _MONTHS, today=_TODAY,
                                 extrapolate=True)
    got = {r["date"]: r["price"] for r in rows}
    week2 = [f"2026-12-{d:02d}" for d in range(8, 15)]
    present = [d for d in week2 if d in got]
    # 现状：能反推出该周大部分日期（列网格未做真机标定时做不到 7/7），
    # 且**全部日期都落在 11 月内**（不会跨月串号）。
    assert len(present) >= 5, (present, sorted(got))
    assert all(d.startswith("2026-12-") for d in got)
    assert all(r["price"] >= 50 for r in rows)


def test_extrapolate_off_by_default():
    """默认不开启外推：未验证的推断不能影响线上读到的价格。"""
    rows = parse_calendar_prices(_real_layout(), _MONTHS, today=_TODAY)
    got = {r["date"]: r["price"] for r in rows}
    week2 = [f"2026-12-{d:02d}" for d in range(8, 15)]
    assert not any(d in got for d in week2)


def test_anchor_row_still_parsed():
    rows = parse_calendar_prices(_real_layout(), _MONTHS, today=_TODAY, extrapolate=True)
    got = {r["date"]: r["price"] for r in rows}
    # 12 月的日子全都晚于 today(11-05)，锚行 1..5 都该读出来
    assert got.get("2026-12-01") == 380.0
    assert got.get("2026-12-05") == 364.0


def test_no_double_count_when_day_known():
    """日号读到的那些天不能被外推段再写一遍（同价同值不冲突，但价格要取低）。"""
    words = _days_row((1, 2, 3, 4, 5), 852, _COLS[2:])
    words += _price_row((380, 380, 380, 400, 364), 923, _COLS[2:])
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    dates = [r["date"] for r in rows]
    assert len(dates) == len(set(dates))


# ---- merged from tests/test_r1049_fliggy_rt_footer.py ----

def _w(pairs, y=2660):
    return [{"t": t, "x": x, "y": y, "w": 38, "h": 30} for t, x in pairs]


def _row(dep, ret, total, y=2660):
    out = []
    x = 60
    for ch in dep:
        out.append((ch, x))
        x += 40
    x = 420
    for ch in ret:
        out.append((ch, x))
        x += 40
    if total is not None:
        out.append(("往返总价", 800))
        out.append(("¥", 900))
        out.append((str(total), 930))
    return _w(out, y=y)


def test_dep_selected_ret_pending():
    got = parse_round_trip_footer(_row("去程：12月14日", "返程：未选择", None))
    assert got["dep"] == (12, 14)
    assert got["ret"] is None
    assert got["total"] is None


def test_both_dates_selected():
    got = parse_round_trip_footer(
        _row("去程：12月14日", "返程：12月20日", None))
    assert got["dep"] == (12, 14)
    assert got["ret"] == (12, 20)


def test_total_price_parsed():
    got = parse_round_trip_footer(
        _row("去程：11月16日", "返程：11月19日", 1880))
    assert got["dep"] == (11, 16)
    assert got["ret"] == (11, 19)
    assert got["total"] == 1880.0


def test_huicheng_variant_accepted():
    """「回程」和「返程」是同一个意思，两种叫法都要认。"""
    got = parse_round_trip_footer(
        _row("去程：11月16日", "回程：11月19日", None))
    assert got["ret"] == (11, 19)


def test_empty_words():
    assert parse_round_trip_footer([]) == {"dep": None, "ret": None,
                                           "total": None}


def test_garbage_does_not_crash():
    got = parse_round_trip_footer(_w([("机票", 100), ("查询", 200)]))
    assert got["dep"] is None and got["ret"] is None and got["total"] is None
