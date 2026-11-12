# -*- coding: utf-8 -*-
"""往返日历底栏解析（往返流程的唯一校验依据）。

文案取自 2026-11-05 真机截图：
    去程：12月14日        返程：未选择         往返总价 ¥---
OCR 会把每个字拆成独立词块，所以用例按词块构造。
"""
from crawlers.app_fliggy_parse import parse_round_trip_footer


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
