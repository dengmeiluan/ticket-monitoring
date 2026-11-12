# -*- coding: utf-8 -*-
"""往返底栏校验：点完两个日期后，唯一能证明"点对了"的关卡。

底栏实测文案（2026-11-05 真机截图）：
    去程：12月14日        返程：未选择         往返总价 ¥---
底栏不写年份，所以只比 (月, 日)。

这条判断错了会产出「日期对不上但价格看起来合理」的错数据 —— 最难发现的一类，
所以必须用单测钉死。
"""
from crawlers.app_fliggy import round_trip_footer_matches


def test_both_match():
    ok, _why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 19), "total": 1880.0},
        "2026-11-16", "2026-11-19")
    assert ok is True


def test_return_not_selected_is_rejected():
    """只选了去程（返程仍是「未选择」）不能算成功。"""
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": None, "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False
    assert "不符" in why


def test_wrong_return_day_is_rejected():
    """返程被点到了别的日子（差一天）必须拒绝——这正是"点偏一格"。"""
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 20), "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False
    assert "11-20" in why


def test_wrong_depart_day_is_rejected():
    ok, _why = round_trip_footer_matches(
        {"dep": (12, 14), "ret": (11, 19), "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False


def test_bad_ymd_format_is_rejected_not_crashing():
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 19)}, "2026/11/16", "2026-11-19")
    assert ok is False
    assert "格式" in why


def test_footer_none_is_rejected():
    ok, _why = round_trip_footer_matches(None, "2026-11-16", "2026-11-19")
    assert ok is False


def test_cross_year_compares_month_day_only():
    """跨年时底栏只写「1月2日」，按 (月, 日) 比较应当通过。"""
    ok, _why = round_trip_footer_matches(
        {"dep": (12, 30), "ret": (1, 2), "total": None},
        "2026-12-30", "2027-01-02")
    assert ok is True
