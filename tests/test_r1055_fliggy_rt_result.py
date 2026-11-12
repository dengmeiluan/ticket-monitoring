# -*- coding: utf-8 -*-
"""往返结果页解析（真机 fixture）：总价以「往返总价」为准，起价在卡片区。

真机截图实证（2026-11-06，1260×2800）：

    顶部 y≈290  「50元国内机票优惠券待使用」  ← 营销数字，不是票价
    卡片区     去程 `南航 320(中) ¥682 起` / 返程 `厦航 321(中) +¥0`
    底部 y≈2677 标签「往返总价」，y≈2739 `¥747`

关键语义：**返程列是加价不是绝对价**，总价只能取底部那个数；
顶部优惠券的「50」和底部的「747」都不能混进"去程起价"。
"""
import io
import json
import os

from crawlers.app_fliggy_parse import parse_round_trip_result

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "fliggy_rt_result_words.json")


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_total_comes_from_bottom_bar():
    got = parse_round_trip_result(_words())
    assert got["total"] == 747.0, got


def test_dep_min_is_card_price_not_coupon():
    """去程起价应是卡片区的 ¥682，不能是顶部优惠券的「50」。"""
    got = parse_round_trip_result(_words())
    assert got["dep_min"] == 682.0, got


def test_coupon_number_is_not_treated_as_fare():
    """把卡片区之外的价格全抹掉，起价必须变成 None 而不是退化成 50。"""
    words = [w for w in _words() if not (600 <= float(w.get("y") or 0) <= 2600)]
    got = parse_round_trip_result(words)
    assert got["dep_min"] is None, got


def test_no_label_means_no_total():
    """没有「往返总价」标签时不能拿去程价冒充往返价。"""
    words = [w for w in _words() if str(w.get("t")) != "价"
             and str(w.get("t")) != "总"]
    got = parse_round_trip_result(words)
    assert got["total"] is None, got


def test_empty_words():
    assert parse_round_trip_result([]) == {"total": None, "dep_min": None}
