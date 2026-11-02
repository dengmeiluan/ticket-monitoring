# -*- coding: utf-8 -*-
"""r660：长窗口日历的格子必须校验可见性，滚出视口的要先滚回来再点。

缺陷现场（真机实测）：弹层覆盖 2026-11-08 ~ 2027-02-06 共 91 格，屏幕
900x1600 只放得下其中一段。卷出屏幕的行**仍在 XML 里**，但 bounds 退化
成 `[11,327][90,30]`（y2 < y1，可见高度 0）。旧 `_calendar_cell` 只按
中心点算坐标，于是：
  * 点到了弹层头部 → 弹层不关 → 报「点了日期但弹层没关」；
  * 用户看到的是「日历里没有这一天」或「点了没反应」，
    实际是**那一天当时没显示在屏幕上**。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_nav import (_calendar_cell, _cell_month_scroll_hint,
                                      _needs_earlier, _pick_date, _tap_calendar_cell)


def _cell(ymd, x1, y1, x2, y2):
    return ('<node resource-id="flight_calendar_date_cell-%s" '
            'bounds="[%d,%d][%d,%d]" />' % (ymd, x1, y1, x2, y2))


def _xml(*cells):
    return '<hierarchy rotation="0">%s' % "".join(cells) + "</hierarchy>"


def test_degenerate_bounds_are_not_clickable():
    """y2 < y1 = 卷出视口，绝不能算出可点坐标。"""
    xml = _xml(_cell("2026-11-12", 542, 327, 620, 30))
    assert _calendar_cell(xml, "2026-11-12") is None


def test_visible_cell_returns_center():
    xml = _xml(_cell("2026-11-12", 542, 806, 620, 900))
    assert _calendar_cell(xml, "2026-11-12") == (581, 853)


def test_missing_cell_returns_none():
    assert _calendar_cell(_xml(), "2026-11-12") is None


def test_scroll_hint_uses_visible_cells_only():
    """卷出视口的格子不能参与范围判断，否则方向永远判不出来。"""
    xml = _xml(_cell("2026-11-08", 11, 327, 90, 30),      # 卷出（退化）
               _cell("2026-12-05", 807, 391, 886, 486),   # 可见
               _cell("2026-12-20", 100, 500, 179, 595))   # 可见
    # 目标早于可见区间 → 需往下拉看更早
    assert _cell_month_scroll_hint(xml, "2026-11-12") == "down"
    # 目标晚于可见区间 → 需往上推看更晚
    assert _cell_month_scroll_hint(xml, "2027-01-15") == "up"
    # 落在可见区间内 → 不需要方向提示
    assert _cell_month_scroll_hint(xml, "2026-12-10") is None


def test_needs_earlier_ignores_invisible_cells():
    xml = _xml(_cell("2026-11-08", 11, 327, 90, 30),
               _cell("2026-12-05", 807, 391, 886, 486))
    assert _needs_earlier(xml, "2026-11-12") is True


class _FakeDev:
    """记录 tap/swipe 的最小设备替身（只实现被测路径用到的原语）。"""

    def __init__(self, xmls):
        self.xmls = list(xmls)
        self.taps = []
        self.swipes = []

    def dump(self, retries=2):
        if len(self.xmls) > 1:
            return self.xmls.pop(0)
        return self.xmls[0]

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def swipe(self, x1, y1, x2, y2, dur=400):
        self.swipes.append((x1, y1, x2, y2))
        return True


def test_tap_scrolls_then_picks_after_cell_becomes_visible():
    """卷出视口 → 滚动一次 → 格子可见 → 点中 → 弹层关闭 → 成功。

    负控在同一个测试里：第一次 dump 的可点坐标必须为空（没瞎点），
    滚动之后才允许 tap——否则「先点了再说」也会让断言通过。
    """
    before = _xml(_cell("2026-11-12", 542, 327, 620, 30))               # 卷出
    after = _xml(_cell("2026-11-12", 542, 806, 620, 900))               # 可见
    home = ('<hierarchy><node text="11月12日" bounds="[0,0][100,40]" />'
            '</hierarchy>')                                             # 弹层已关
    dev = _FakeDev([before, after, home])
    ok, detail = _tap_calendar_cell(dev, before, "2026-11-12")
    assert ok, detail
    assert dev.swipes, "卷出视口时必须先滚动，不能直接点"
    assert dev.taps and dev.taps[0] == (581, 853), dev.taps


def test_tap_gives_up_when_date_outside_covered_range():
    """真不在覆盖范围（比最小可见日还早且拉不动）→ 明确报不在范围。"""
    xml = _xml(_cell("2026-12-05", 807, 391, 886, 486))
    dev = _FakeDev([xml])
    ok, detail = _tap_calendar_cell(dev, xml, "2026-11-01")
    assert not ok
    assert "2026-11-01" in detail
    assert not dev.taps, "看不到的格子绝不能点"


def test_pick_date_reports_visible_state_not_fake_success():
    """_pick_date 在弹层里拿不到目标格时不得返回成功。"""
    xml = _xml(_cell("2026-12-05", 807, 391, 886, 486))
    dev = _FakeDev([xml])
    ok, detail = _pick_date(dev, [], "2026-11-01", xml=xml)
    assert not ok, detail
