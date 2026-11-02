# -*- coding: utf-8 -*-
"""飞猪 App 结果页 OCR 词块解析（纯函数）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_fliggy_parse import (parse_form_words, parse_words,
                                       pick_best)


def W(t, x, y, w, h):
    return {"t": t, "x": x, "y": y, "w": w, "h": h}


def _row(y, dep, arr, price, list_price, airline, fno,
         dep_air="浦东T1", arr_air="长水", tag="", day_note=""):
    out = [
        W(dep[:2], 39, y, 49, 37), W("：", 95, y + 15, 7, 21),
        W(dep[3:], 109, y, 49, 37),
        W(arr[:2], 420, y + 1, 42, 36), W("：", 468, y + 15, 7, 21),
        W(arr[3:], 482, y + 1, 42, 36),
        W(dep_air[:3], 37, y + 54, 24, 26), W(dep_air[3:], 64, y + 55, 23, 24),
        W(arr_air[:2], 476, y + 54, 24, 25), W(arr_air[2:], 503, y + 54, 24, 26),
        W(airline[:2], 69, y + 99, 21, 24), W(fno, 117, y + 103, 88, 17),
        W("￥", 735, y + 15, 14, 20), W(str(price), 753, y, 77, 37),
        W("经济舱", 721, y + 55, 24, 24),
    ]
    if list_price:
        out += [W("￥", 677, y + 18, 12, 17),
                W(str(list_price), 691, y + 18, 38, 17)]
    if tag:
        out += [W(ch, 47 + i * 24, y - 40, 21, 22) for i, ch in enumerate(tag)]
    if day_note:
        out += [W(day_note, 426, y - 30, 90, 21)]
    return out


def _three_rows():
    words = []
    words += _row(694, "09:00", "15:15", 470, None, "东航", "MU5505",
                  tag="限特定乘客")
    words += _row(896, "20:35", "00:20", 488, 528, "吉祥", "H01017",
                  dep_air="浦东T2", tag="历史低价", day_note="11.05 周四")
    words += _row(1158, "21:10", "00:55", 550, 590, "东航", "MU5822",
                  tag="可能涨价", day_note="11.05 周四")
    # 杂项：顶部日期带价格、底部栏，不应被当成航班
    words += [W("500", 80, 260, 50, 37), W("380", 300, 260, 50, 37)]
    return words


def test_parses_three_rows_with_prices_times_and_flights():
    rows = parse_words(_three_rows(), "上海", "昆明", "2026-11-02")
    assert len(rows) == 3, rows
    assert [r["price"] for r in rows] == [470, 488, 550]
    assert [r["list_price"] for r in rows] == [None, 528, 590]
    assert [r["dep_time"] for r in rows] == ["09:00", "20:35", "21:10"]
    assert [r["arr_time"] for r in rows] == ["15:15", "00:20", "00:55"]
    assert [r["flight_no"] for r in rows] == ["MU5505", "HO1017", "MU5822"]
    assert [r["airline"] for r in rows] == ["东航", "吉祥", "东航"]
    assert rows[0]["dep_airport"] == "浦东T1"
    assert rows[1]["dep_airport"] == "浦东T2"


def test_tags_and_next_day_note():
    rows = parse_words(_three_rows(), "上海", "昆明", "2026-11-02")
    assert rows[0]["tags"] == ["限特定乘客"]
    assert rows[1]["tags"] == ["历史低价"]
    assert rows[2]["tags"] == ["可能涨价"]
    assert "11.05" in rows[1]["arr_day_note"]


def test_pay_price_is_rightmost_large_digit_not_age_price():
    """右侧还有「特定年龄价 ¥470」小字，不能把它当支付价。"""
    words = _row(896, "20:35", "00:20", 488, 528, "吉祥", "H01017")
    words += [W("特定年龄价", 673, 999, 120, 26),
              W("￥", 804, 1003, 13, 19), W("470", 818, 1003, 43, 19)]
    rows = parse_words(words)
    assert len(rows) == 1
    assert rows[0]["price"] == 488


def test_same_flight_duplicates_keep_lowest_price():
    words = _row(896, "20:35", "00:20", 488, 528, "吉祥", "H01017")
    words += _row(1496, "20:35", "00:20", 460, 528, "吉祥", "H01017")
    rows = parse_words(words)
    assert len(rows) == 1
    assert rows[0]["price"] == 460


def test_ocr_misread_letter_o_as_zero_in_flight_no():
    words = _row(896, "20:35", "00:20", 488, 528, "吉祥", "H01017")
    assert parse_words(words)[0]["flight_no"] == "HO1017"


def _form_words():
    return [
        W("上", 67, 610, 48, 46), W("海", 120, 609, 49, 49),
        W("昆", 735, 611, 46, 47), W("明", 786, 611, 46, 48),
        W("11", 68, 736, 36, 40), W("月", 111, 748, 25, 28),
        W("2", 145, 735, 25, 41), W("日", 180, 749, 22, 27),
        W("今", 217, 747, 29, 30), W("天", 249, 749, 28, 27),
        W("搜", 375, 1117, 35, 37), W("索", 414, 1117, 34, 37),
        W("机", 451, 1117, 37, 37), W("票", 490, 1118, 35, 36),
    ]


def test_form_words_locate_route_date_and_search():
    form = parse_form_words(_form_words())
    assert form["dep"] == "上海" and form["arr"] == "昆明"
    assert form["date_text"].startswith("11月2日")
    assert form["dep_xy"] == (118, 633)
    assert form["arr_xy"] == (783, 635)
    assert form["search_xy"] is not None


def test_restricted_passenger_fare_not_used_as_general_lowest():
    rows = [
        {"price": 470, "tags": ["限特定乘客"]},
        {"price": 488, "tags": []},
        {"price": 550, "tags": []},
    ]
    assert pick_best(rows)["price"] == 488
    only_restricted = [{"price": 350, "tags": ["限特定乘客"]}]
    assert pick_best(only_restricted)["price"] == 350


def test_non_form_page_returns_empty_fields():
    form = parse_form_words([W("消息", 20, 20, 30, 20)])
    assert form == {"dep": "", "arr": "", "date_text": "",
                    "dep_xy": None, "arr_xy": None,
                    "date_xy": None, "search_xy": None}
