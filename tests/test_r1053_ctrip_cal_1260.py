# -*- coding: utf-8 -*-
"""携程价格日历：1260×2800 下的真实 OCR fixture 必须能解析出逐日价。

背景（2026-11-06 实测）：`_app_ctrip_deals` 一直返回
「OCR 未读到日历价」，而同一张截图里 OCR 明明读到了 `2026年11月` 和
`¥340/¥384/¥420`。根因是两处 **900×1600 标定值**：

1. `_month_headers` 只取 `x <= 240` 的词块 —— 1260 宽下月头是
   `2026`x=47 `年`x=163 `1`x=216 `1`x=245 `月`x=271，后两段被丢掉，
   标题拼不全 → 认不出月份 → 整图 0 行；
2. 列号用 `col = round((cx - COL0) / COL_STEP)`，而 `COL_STEP=126`
   是 900/7；1260 下是 180，列号落不到 0..6，行全被丢弃。

fixture 是**真机截图 OCR 的原始词块**（`tests/fixtures/
ctrip_cal_1260_words.json`，249 块），不依赖设备。
"""
import io
import json
import os
from datetime import date

from crawlers.app_ctrip_calendar import _month_headers, parse_calendar_words

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "ctrip_cal_1260_words.json")

#: 截图拍摄日：2026-11-06（fixture 里的「今天/明天/后天」按这个日期生成）
TODAY = date(2026, 11, 6)


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_month_headers_need_scaled_left_bound():
    """左栏界限不缩放时认不出月份——这正是 0 行的第一因。"""
    w = _words()
    assert _month_headers(w, x_max=240.0) == [], "240 界限下不该认出完整月份"
    got = _month_headers(w, x_max=336.0)
    assert (2026, 11) in [(y, m) for y, m, _cy in got], got


def test_parses_daily_prices_at_1260():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    assert len(rows) >= 40, "1260 档应解析出整月逐日价，实际 %d 行" % len(rows)
    got = {r["date"]: r["price"] for r in rows}
    # 抽几个真机读到的值做锚（截图 OCR 原文：今天 500 / 明天 350 / 后天 400）
    assert got.get("2026-11-06") == 500.0
    assert got.get("2026-11-07") == 350.0
    assert got.get("2026-11-08") == 400.0
    # 11-10 是 ¥340（当天最低之一）
    assert got.get("2026-11-10") == 340.0


def test_weekday_label_matches_today():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    by = {r["date"]: r for r in rows}
    assert by["2026-11-06"]["weekday"] == "今天"
    assert by["2026-11-07"]["weekday"] == "明天"


def test_no_900_geometry_would_misparse():
    """不传宽度（按 900 基准）时解析不出东西——反证宽度标定是必需的。"""
    rows = parse_calendar_words(_words(), today=TODAY)
    assert rows == []


def test_all_dates_inside_visible_months():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    for r in rows:
        assert r["date"].startswith(("2026-11", "2026-12", "2027-01")), r
        assert r["price"] >= 10
