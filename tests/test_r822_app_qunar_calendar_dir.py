# -*- coding: utf-8 -*-
"""r822：app_qunar 日历方向判据——目标日在同月但已滚出视口时要向上翻。

2026-11-02 21:58 真机现场（debug/scene/..._pickdate-cell.txt）：
日历停在 11/29-30（下面是 12 月、2027 年 1 月），目标 11/16 在视口上方；
`_visible_months()` 只看到「2026年11月」，于是原逻辑判断“目标月已可见、
只是格子没渲染”→ 每帧 sleep 等待，8 次后 pick-date-failed。

修复：优先看该月已渲染的 `q_flight_calendarDayItem#YYYY-MM-DD`：
目标日小于最小可见日 → 向上翻；大于最大可见日 → 向下翻；否则等一帧。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import _calendar_scroll_dir  # noqa: E402


def _n(text, x1, y1, x2, y2, desc=""):
    d = ' content-desc="%s"' % desc if desc else ""
    return ('<node text="%s" resource-id="" class=""%s'
            ' bounds="[%d,%d][%d,%d]" />' % (text, d, x1, y1, x2, y2))


def _xml(month, days, target_day_x=100):
    nodes = [_n(month, 36, 300, 168, 330)]
    y = 330
    for d in days:
        nodes.append(_n(str(d), target_day_x, y, target_day_x + 60, y + 60,
                        desc="q_flight_calendarDayItem#%s-%02d"
                             % (month.replace("年", "-").replace("月", "")
                                if False else "2026-11", d)))
        y += 60
    return "<hierarchy>%s</hierarchy>" % "".join(nodes)


def test_target_above_visible_days_scrolls_up():
    xml = _xml("2026年11月", [29, 30])
    assert _calendar_scroll_dir(xml, "2026-11-16") == "up"


def test_target_below_visible_days_scrolls_down():
    xml = _xml("2026年11月", [1, 2])
    assert _calendar_scroll_dir(xml, "2026-11-16") == "down"


def test_target_in_visible_days_waits_for_cell():
    xml = _xml("2026年11月", [15, 16, 17])
    assert _calendar_scroll_dir(xml, "2026-11-16") == ""


def test_target_month_after_visible_months_scrolls_down():
    xml = ("<hierarchy>"
           + _n("2026年11月", 36, 300, 168, 330)
           + _n("2026年12月", 36, 700, 168, 730)
           + "</hierarchy>")
    assert _calendar_scroll_dir(xml, "2027-01-16") == "down"


def test_target_month_before_visible_months_scrolls_up():
    xml = ("<hierarchy>"
           + _n("2026年11月", 36, 300, 168, 330)
           + _n("2026年12月", 36, 700, 168, 730)
           + "</hierarchy>")
    assert _calendar_scroll_dir(xml, "2026-10-16") == "up"


def test_no_month_info_waits():
    assert _calendar_scroll_dir("<hierarchy></hierarchy>", "2026-11-16") == ""
