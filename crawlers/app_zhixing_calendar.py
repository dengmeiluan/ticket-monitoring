# -*- coding: utf-8 -*-
"""智行「选择日期」日历弹层的解析。

**为什么它比首页日历条重要**：
  首页那条只显示 7–8 天（今天起），而点开「选择日期」后是一个
  **滚动日历，覆盖两个月、每天明码标价**，且每格 resource-id 里
  直接内嵌完整的 ISO 日期：

      flight_calendar_date_cell-2026-11-15
      flight_calendar_date_cell_date_text-2026-11-15
      flight_calendar_date_cell_price_text-2026-11-15

  按 id 取日期与价格，不需要任何坐标推算、不需要年份补全，
  也不受滚动位置影响（拿到的就是当前已渲染月份）。

实测（2026-10-30）：11 月 1–30 日全部有价（¥330/¥299/¥256…），
国际/远期航线因此比首页日历条覆盖长得多。
"""
from __future__ import annotations

import re
from typing import Dict, List

_TAG_RE = re.compile(r"<node\b[^>]*>")
_ATTR_RE = {
    "text": re.compile(r'text="([^"]*)"'),
    "rid": re.compile(r'resource-id="([^"]*)"'),
}

# flight_calendar_date_cell[-_kind]-YYYY-MM-DD
_CELL_RE = re.compile(
    r"^flight_calendar_date_cell(?:[-_](date|price|info)_text)?"
    r"-(\d{4}-\d{2}-\d{2})$")

_PRICE_RE = re.compile(r"^[\u00a5\uffe5]\s*(\d{2,5})$")
_MASK_RE = re.compile(r"^\d[?？]{1,3}$")


def _attr(tag: str, name: str) -> str:
    m = _ATTR_RE[name].search(tag)
    return m.group(1) if m else ""


def has_calendar_dialog(xml: str) -> bool:
    """页面是否是「选择日期」日历弹层。"""
    return "Search_Calendar_Dialog_Title" in (xml or "") or \
        "flight_calendar_date_cell-" in (xml or "")


def parse_date_dialog(xml: str) -> List[dict]:
    """解析日历弹层：返回 [{date(ISO), price, masked}]，按日期升序。

    同一格里 price 文本可能为空（该日未放价/不可售）→ price=None，
    **不是 0**；遮罩价（`3??`）也归 None 并标 masked。
    """
    cells: Dict[str, dict] = {}
    for m in _TAG_RE.finditer(xml or ""):
        tag = m.group(0)
        rid = _attr(tag, "rid")
        cm = _CELL_RE.match(rid)
        if not cm:
            continue
        kind, date = cm.group(1) or "root", cm.group(2)
        cell = cells.setdefault(date, {"date": date, "price": None,
                                       "masked": False})
        if kind != "price":
            continue
        text = _attr(tag, "text").strip()
        if not text:
            continue
        pm = _PRICE_RE.match(text)
        if pm:
            cell["price"] = int(pm.group(1))
        elif _MASK_RE.match(text):
            cell["masked"] = True
    return sorted(cells.values(), key=lambda r: r["date"])


def month_range(xml: str) -> tuple:
    """已渲染的月份范围（用于说明"只拿到哪几个月"）。"""
    months = sorted(set(re.findall(
        r"Search_Calendar_Month_Title_(\d{4}年\d{1,2}月)", xml or "")))
    return (months[0], months[-1]) if months else ("", "")
