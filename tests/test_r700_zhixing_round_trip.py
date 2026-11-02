# -*- coding: utf-8 -*-
"""r700：智行「往返」是真实能力——双列布局、总价只在左列。

真机（2026-10-31，北京⇄上海，点「往返」→「机票查询」）：

    去程(x≈25)                返程(x≈470)
    14:00        16:30        21:05       23:20
    大兴         浦东T2       浦东T1      大兴
    南航CZ8882   ¥ 706 +      东航MU5185  ¥ 0
    11:55        14:10        08:25       10:40
    吉祥HO1258   ¥ 736 +      吉祥HO1257  ¥ 26

三条必须守住的判据：
  * **总价只在左列**；右列 `¥ 0 / ¥ 26` 是返程加价，当票价就是 0 元假数据；
  * 时刻与价格要**同一张卡片**（时刻 cy=312、航班号 cy=386，跨度 74px；
    下一张卡片在 +141px 外），窗口取 26 会全空、取 90 会张冠李戴；
  * 「临近推荐」区（`¥704 起` 的火车接驳）不是往返总价，整段排除。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_roundtrip import (parse_round_trip_rows,
                                            split_columns)


def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _page():
    return ('<hierarchy>'
            + _n("去程", 25, 124, 71, 156)
            + _n("筛选", 393, 128, 429, 153)
            + _n("返程", 470, 124, 516, 156)
            + _n("筛选", 838, 128, 874, 153)
            # 第一张去程卡
            + _n("14:00", 25, 297, 193, 327)
            + _n("16:30", 358, 297, 429, 327)
            + _n("大兴", 25, 328, 57, 350)
            + _n("浦东T2", 379, 328, 430, 350)
            + _n("南航CZ8882", 25, 375, 371, 399)
            + _n("¥", 376, 379, 387, 401)
            + _n("706", 387, 373, 430, 400)
            + _n("+", 837, 373, 848, 400)
            # 右列返程卡（只有起飞时刻渲染出来）
            + _n("21:05", 470, 297, 639, 327)
            + _n("浦东T1", 470, 328, 521, 350)
            + _n("东航MU5185", 470, 376, 834, 400)
            + _n("¥", 850, 381, 861, 403)
            + _n("0", 861, 385, 875, 405)
            # 第二张去程卡
            + _n("11:55", 25, 438, 193, 468)
            + _n("14:10", 361, 438, 429, 468)
            + _n("吉祥HO1258", 25, 516, 370, 540)
            + _n("¥", 375, 520, 386, 542)
            + _n("736", 386, 514, 430, 541)
            # 临近推荐：不是往返总价
            + _n("临近推荐", 52, 579, 124, 601)
            + _n("704", 366, 633, 410, 660)
            + _n("起", 410, 634, 426, 656)
            + _n("¥", 355, 639, 366, 660)
            + '</hierarchy>')


def test_columns_split_at_filter_buttons():
    """列分界取两个「筛选」的中点，不能用标题中点（会算成 270）。"""
    mid, _w = split_columns(_page())
    assert mid > 430, mid
    assert mid < 838, mid


def test_total_price_taken_from_left_column_only():
    rows = {r["flight_no"]: r for r in parse_round_trip_rows(_page())}
    assert rows["CZ8882"]["price"] == 706
    assert rows["HO1258"]["price"] == 736
    # 右列的 ¥0 绝不能变成任何一行的价格
    assert all(r["price"] > 100 for r in rows.values()), rows


def test_departure_and_arrival_pair_within_same_card():
    rows = {r["flight_no"]: r for r in parse_round_trip_rows(_page())}
    assert rows["CZ8882"]["depart_time"] == "14:00"
    assert rows["CZ8882"]["arrive_time"] == "16:30"
    assert rows["HO1258"]["depart_time"] == "11:55"
    assert rows["HO1258"]["arrive_time"] == "14:10"


def test_nearby_recommendation_section_excluded():
    """「临近推荐」里的 ¥704 起 不是往返总价。"""
    rows = parse_round_trip_rows(_page())
    assert len(rows) == 2, rows
    assert all(r["price"] in (706, 736) for r in rows)


def test_missing_return_info_stays_empty_not_guessed():
    """返程信息同 y 带取不到就留空，绝不拿别的卡片充数。"""
    rows = {r["flight_no"]: r for r in parse_round_trip_rows(_page())}
    # 右列第一张卡在 21:05 这一带，与左列第一张卡（14:00）同 y
    assert rows["CZ8882"]["return_flight_no"] in ("MU5185", "")
    # 第二张卡那一带右列没有航班号 → 必须留空
    assert rows["HO1258"]["return_flight_no"] == ""
