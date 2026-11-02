# -*- coding: utf-8 -*-
"""r702：单程采集前必须把「往返」档复位，否则整轮静默错价。

真机（2026-10-31）踩到的两个连锁故障，都源自首页停在往返档：

  1. 单程流程 `_pick_date` 拿到的是**两段式往返日期弹层**（选完去程还要
     选返程、再按「确定」），判据 `弹层关掉了 && 首页日期行=目标日` 永不
     成立 → `pick-date-failed`，整轮 0 行；
  2. 更危险的是没报错的情形：结果页是往返页，往返总价被当成单程价落库。

复位判据用**返程日期位在不在**（`atom_flight_ll_back_date`），不用
RadioButton 的 `checked`——同一渲染帧里 checked 会滞后，实测点完仍读
到上一次的状态。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers.app_qunar as q


class _FakeDev:
    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []
        self.dumps = 0

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def dump(self):
        self.dumps += 1
        i = min(self.dumps, len(self.pages) - 1)
        return self.pages[i]


def _home(round_trip):
    xml = ('<hierarchy>'
           '<node text="单程" resource-id="com.Qunar:id/atom_flight_single_rb"'
           ' class="android.widget.RadioButton" bounds="[51,418][550,460]" />'
           '<node text="往返" resource-id="com.Qunar:id/atom_flight_round_rb"'
           ' class="android.widget.RadioButton" bounds="[550,418][1049,460]" />'
           '<node text="" resource-id="com.Qunar:id/atom_flight_ll_dep_date"'
           ' class="android.widget.LinearLayout" bounds="[48,564][205,609]" />')
    if round_trip:
        xml += ('<node text="" resource-id="com.Qunar:id/atom_flight_ll_back_date"'
                ' class="android.widget.LinearLayout"'
                ' bounds="[1343,564][1552,609]" />')
    return xml + '</hierarchy>'


class _Crawler(q.AppQunarCrawler):
    def __init__(self):
        super().__init__({}, None)


def test_round_trip_home_is_switched_to_single():
    dev = _FakeDev([_home(True), _home(False)])
    xml = _Crawler()._switch_to_single(dev, _home(True))
    assert dev.taps, "停在往返档却没点「单程」"
    # 点的是单程 RadioButton 的中心 (300, 439)，不是往返那颗 (799, 439)
    assert dev.taps[0] == (300, 439)
    assert q._ID_BACK_DATE_LL not in xml


def test_single_home_is_left_alone():
    c = _Crawler()
    dev = _FakeDev([_home(False)])
    xml = c._switch_to_single(dev, _home(False))
    assert dev.taps == [], "已经是单程档，不该白点一下"
    assert xml == _home(False)


def test_single_fetch_switches_before_picking_dates():
    """单程入口本身要调复位——只测 `_switch_to_single` 会漏掉这里。"""
    import inspect
    src = inspect.getsource(q.AppQunarCrawler._fetch_locked)
    assert "_switch_to_single" in src, \
        "单程流程没复位档位：往返档下会 pick-date-failed 或把往返价当单程价"


def test_back_date_marker_is_distinct_from_dep_date():
    # 判据必须是「返程位」，不能是泛化的日期位 id：单程档也有 dep_date
    assert q._ID_BACK_DATE_LL != q._ID_DEP_DATE_LL
    assert q._ID_BACK_DATE_LL.endswith("back_date")
