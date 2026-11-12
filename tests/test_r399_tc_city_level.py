# -*- coding: utf-8 -*-
"""r399：同程窗历是**城市级**最低价，不能当成该机场的票价。

实测（真实接口，同一天同一出发地）：

```
SHA→LHR n=90 first4=[('2026-10-27',2492),('2026-10-28',2507),...]
SHA→LGW n=90 first4=[('2026-10-27',2492),('2026-10-28',2507),...]  ← 完全一致
SHA→NRT n=90 first4=[('2026-10-27',1624),('2026-10-28',1412),...]
SHA→HND n=90 first4=[('2026-10-27',1624),('2026-10-28',1412),...]  ← 完全一致
```

按机场码打这个接口，同一城市的两个机场返回逐日同价——它给的是城市
最低价。行按配置的机场码落库（用户按机场关注），但若不标注，读者会把
「SHA→LHR ¥2492」读成希思罗的票价，而它可能落在盖特威克。

守卫钉：机场码≠城市码时必须带 `cityLevel=true`；单机场城市不误标。
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402


def _row(fc, tc, from_city, to_city):
    c = TongchengCrawler({}, logging.getLogger("t_r399"))
    r = c._intl_window_row(from_city, to_city, fc, tc, "2026-11-16", 1000.0)
    return r, json.loads(r.extra)[0]


def test_multi_airport_city_is_marked_city_level():
    """NRT 订票但查的是 TYO → 必须标城市级。"""
    r, e = _row("SHA", "TYO", "SHA", "NRT")
    assert r.to_city == "NRT", "行仍按配置的机场码存"
    assert e["cityLevel"] is True, e
    assert e["cityCodes"] == "SHA-TYO", e


def test_london_marked_city_level():
    r, e = _row("SHA", "LON", "SHA", "LHR")
    assert e["cityLevel"] is True, e


def test_single_airport_city_not_marked():
    """BKK 这种城市即机场的不该被误标成城市级。"""
    r, e = _row("SHA", "BKK", "SHA", "BKK")
    assert e["cityLevel"] is False, e


def test_source_still_traceable():
    """标注不应破坏原有溯源字段。"""
    r, e = _row("SHA", "TYO", "SHA", "NRT")
    assert e["source"] == "tc_window_calendar"
    assert e["price"] == 1000.0
    assert e["depTime"] == "" and e["arrTime"] == ""
