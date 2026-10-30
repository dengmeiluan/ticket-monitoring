# -*- coding: utf-8 -*-
"""智行「选择日期」日历弹层解析：按 id 取日期，长窗口。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_calendar import (has_calendar_dialog, month_range,
                                           parse_date_dialog)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures", "zhixing_date_dialog_dump.xml")


def _xml():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_detects_dialog():
    assert has_calendar_dialog(_xml()) is True
    assert has_calendar_dialog("<hierarchy></hierarchy>") is False


def test_parses_real_prices():
    """真实弹层：10-30 ¥430、10-31 ¥299、11-03 ¥256（与界面一致）。"""
    prices = {r["date"]: r["price"] for r in parse_date_dialog(_xml())}
    assert prices.get("2026-10-30") == 430
    assert prices.get("2026-10-31") == 299
    assert prices.get("2026-11-03") == 256


def test_covers_multiple_months():
    """这是它相对首页日历条的价值：跨月长窗口。"""
    rows = parse_date_dialog(_xml())
    months = {r["date"][:7] for r in rows}
    assert {"2026-10", "2026-11"} <= months, months
    lo, hi = month_range(_xml())
    assert "10" in lo and "12" in hi


def test_sorted_by_date():
    keys = [r["date"] for r in parse_date_dialog(_xml())]
    assert keys == sorted(keys)


def test_missing_price_is_none_not_zero():
    for r in parse_date_dialog(_xml()):
        assert r["price"] is None or r["price"] > 0


def test_priced_ratio_is_reported():
    """多数格子应有价；数量级明显不对说明解析退化了。"""
    rows = parse_date_dialog(_xml())
    priced = [r for r in rows if r["price"]]
    assert len(priced) >= 20, len(priced)


def test_mask_marked_not_priced():
    xml = ('<hierarchy><node text="" '
           'resource-id="flight_calendar_date_cell-2026-11-05" />'
           '<node text="3??" '
           'resource-id="flight_calendar_date_cell_price_text-2026-11-05" />'
           '</hierarchy>')
    row = parse_date_dialog(xml)[0]
    assert row["price"] is None and row["masked"] is True


def test_ignores_unrelated_ids():
    xml = ('<hierarchy><node text="999" '
           'resource-id="some_other_price_text-2026-11-05" /></hierarchy>')
    assert parse_date_dialog(xml) == []
