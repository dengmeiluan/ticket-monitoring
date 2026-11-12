# -*- coding: utf-8 -*-
"""r805at：去哪儿 App「选日期」首次点击没生效时要重试。

同一根因的另一处（与 r805as 的设城市同型）：账本 78 条 timeout 里有
**33 条 `pick-date-failed`**，集中在 2027-01-29/30（各 12 次），而
2027-02-14 成功 10 次——不是「远期日期不支持」，是日期行那一下没点中。

`_pick_date` 原实现**只点一次**日期行，点不中就 `return False`。日期行
同样是 RN 元素，滚动/转场后那一帧的坐标会点不中。修法：2 次尝试
（每次等 6s，最坏耗时与原来的 12s 持平），没等到弹层就用**新 dump 的
坐标**再点一次。

**本用例只覆盖逻辑层**（替身设备）；真机端到端复验仍待做。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATE_TV = "com.Qunar:id/atom_flight_tv_dep_date"


def _n(rid, text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="%s" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, rid, x1, y1, x2, y2))


class Dev:
    """第 N 次点日期行才真的打开日历弹层。"""

    def __init__(self, open_on_tap=2):
        self.open_on_tap = open_on_tap
        self.date_taps = 0
        self.opened = False
        self.date_text = "11月16日"

    def dump(self):
        if self.opened:
            return ('<hierarchy>'
                    + _n("", "选择日期", 400, 60, 700, 110)
                    + _n("", "2027年1月", 60, 200, 400, 240)
                    + _n("", "29", 500, 500, 560, 560)
                    + '</hierarchy>')
        return ('<hierarchy>' + _n(DATE_TV, self.date_text, 60, 500, 300, 560)
                + '</hierarchy>')

    def tap(self, x, y):
        if self.opened and 500 <= y <= 560:
            self.opened = False
            self.date_text = "1月29日"
            return True
        if not self.opened and 500 <= y <= 560:
            self.date_taps += 1
            if self.date_taps >= self.open_on_tap:
                self.opened = True
            return True
        return True

    def window_size(self):
        return (1080, 1920)

    def swipe(self, *a, **k):
        return True

    def input_text(self, s):
        return True

    def keyevent(self, k):
        return True


def _crawler():
    from crawlers.app_qunar import AppQunarCrawler
    return AppQunarCrawler.__new__(AppQunarCrawler)


def test_retaps_date_row_when_calendar_did_not_open(monkeypatch):
    import crawlers.app_qunar as mq
    monkeypatch.setattr(mq, "_sleep", lambda s: None)
    dev = Dev(open_on_tap=2)
    ok = _crawler()._pick_date(dev, dev.dump(), "2027-01-29")
    assert ok is True, "首次点不中后应重试并成功（实际 False）"
    assert dev.date_text == "1月29日", "日期没真的换过去：%s" % dev.date_text
    assert dev.date_taps == 2, (
        "日期行被点了 %d 次；首次点不中时必须重试一次" % dev.date_taps)


def test_single_tap_still_works(monkeypatch):
    import crawlers.app_qunar as mq
    monkeypatch.setattr(mq, "_sleep", lambda s: None)
    dev = Dev(open_on_tap=1)
    assert _crawler()._pick_date(dev, dev.dump(), "2027-01-29") is True
    assert dev.date_taps == 1, "一次就点开时不该重复点"


class CalDev:
    """日历停在 start 月；向下拉（露出更早月份）才回到目标月。

    现场实证（debug/scene/qunar_app_20261101_175947_pickdate-cell.txt）：
    目标 2027-01-30，弹层停在「2027年7月/8月」——原实现未渲染就往下滑，
    越滑越远，8 次后必然失败。
    """

    def __init__(self, start=(2027, 2)):
        self.y, self.m = start
        self.swipes = []
        self.closed = False

    def _shift(self, n):
        idx = self.y * 12 + (self.m - 1) + n
        self.y, self.m = idx // 12, idx % 12 + 1

    def _nm(self):
        y, m = self.y, self.m
        return (y + 1, 1) if m == 12 else (y, m + 1)

    def dump(self):
        if self.closed:
            return ('<hierarchy>' + _n("", "1月30日", 60, 500, 300, 560)
                    + '</hierarchy>')
        ny, nm = self._nm()
        return ('<hierarchy>'
                + _n("", "选择日期", 400, 60, 700, 110)
                + _n("", "%d年%d月" % (self.y, self.m), 36, 307, 154, 330)
                + _n("", "%d年%d月" % (ny, nm), 36, 700, 154, 723)
                + _n("", "30", 68, 400, 82, 440)
                + _n("", "30", 68, 800, 82, 840)
                + '</hierarchy>')

    def tap(self, x, y):
        if 400 <= y <= 440:
            self.closed = True
        return True

    def swipe(self, x1, y1, x2, y2, dur=0):
        self.swipes.append((y1, y2))
        self._shift(-1 if y2 > y1 else 1)
        return True

    def window_size(self):
        return (1080, 1920)

    def input_text(self, s):
        return True

    def keyevent(self, k):
        return True


def test_calendar_scrolled_past_target_swipes_back(monkeypatch):
    """弹层停在其后月份时，必须往**上**翻回去，不能继续往后滑。"""
    import crawlers.app_qunar as mq
    monkeypatch.setattr(mq, "_sleep", lambda s: None)
    dev = CalDev(start=(2027, 2))
    assert _crawler()._pick_date(dev, dev.dump(), "2027-01-30") is True
    assert dev.swipes and dev.swipes[0] == (600, 1200), (
        "第一次翻页方向错了（应为向上翻回更早的月份）：%r" % (dev.swipes,))
