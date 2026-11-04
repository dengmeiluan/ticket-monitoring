# -*- coding: utf-8 -*-
"""携程 App 采集器：导航契约与列表合并（不碰真机）。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_ctrip import AppCtripCrawler, _find_flight_tile


class FakeDev:
    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []
        self.swipes = 0

    def dump(self):
        if len(self.pages) > 1:
            return self.pages.pop(0)
        return self.pages[0]

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def swipe(self, *a, **k):
        self.swipes += 1
        return True

    def start_component(self, component):
        self.taps.append(("component", component))
        return True

    def app_start(self, pkg):
        self.taps.append(("pkg", pkg))
        return True

    def screencap(self):
        return b"fake-png"


def _xml(inner=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<hierarchy rotation="0">{inner}</hierarchy>')


def _home():
    return _xml('''
<node text="酒店" bounds="[60,190][140,250]" />
<node text="机票" bounds="[410,190][490,250]" />
<node text="火车票" bounds="[580,190][660,250]" />
''')


def _form():
    return _xml('''
<node text="上海" content-desc="depart city" bounds="[48,522][408,594]" />
<node text="北京" content-desc="arrival city" bounds="[492,522][852,594]" />
<node text="11月16日周一" content-desc="depart date" bounds="[48,595][852,667]" />
<node text="查 询" bounds="[300,840][600,910]" />
''')


def _card(no, price):
    return f'''
<node text="" resource-id="第{no}航班" content-desc="第{no}航班"
      bounds="[0,419][876,537]">
  <node text="06:40" content-desc="第{no}航班出发时间" bounds="[72,437][203,476]" />
  <node text="09:00" content-desc="第{no}航班到达时间" bounds="[267,437][398,476]" />
  <node text="{price}" content-desc="第{no}航班价格" bounds="[828,437][866,476]" />
  <node text="浦东T2" content-desc="第{no}航班出发机场+航站楼" bounds="[72,476][203,500]" />
  <node text="大兴" content-desc="第{no}航班到达机场+航站楼" bounds="[267,476][398,500]" />
  <node text="中国国航" content-desc="第{no}航班航司信息" bounds="[40,514][240,536]" />
</node>'''


def _crawler():
    return AppCtripCrawler({"android": {"enabled": True}},
                           logging.getLogger("app_ctrip_test"))


def test_calendar_reads_ocr_and_records_app_calendar(monkeypatch):
    """日历：打开弹层→截图→OCR→过滤窗口→path_note ok（不碰真机）。"""
    import contextlib
    import json
    from datetime import date
    import crawlers.app_ctrip as mod

    fixture = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "ctrip_calendar_ocr.json")
    with open(fixture, encoding="utf-8") as f:
        words = json.load(f)

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 2)

    class FakeRT:
        def ensure_ready(self):
            return True, ""

        def device(self):
            return dev

        def device_lock(self, timeout=600.0, owner=""):
            # 同真实签名（含 owner，2026-11-04 起用于锁持有者观测）
            return contextlib.nullcontext()

    calendar_xml = _xml('<node text="选择出发日期" bounds="[0,0][10,10]" />'
                        '<node text="仅看直飞" bounds="[0,0][10,10]" />')
    dev = FakeDev([_form(), _form(), _form(), _form(), calendar_xml])
    c = _crawler()
    c.runtime = lambda: FakeRT()
    c.prepare_device = lambda dev: None
    monkeypatch.setattr(mod, "_date", _FixedDate)
    monkeypatch.setattr("core.android.ocr.available", lambda: True)
    monkeypatch.setattr("core.android.ocr.ocr_words", lambda png: words)
    rows = c.calendar("SHA", "PEK", days=62)
    assert len(rows) == 62, len(rows)
    assert rows[0]["date"] == "2026-11-02"
    assert rows[0]["price"] == 420.0
    assert rows[-1]["date"] == "2027-01-02"
    assert c.paths[-1]["path"] == "app-calendar"
    assert c.paths[-1]["status"] == "ok"
    assert (244, 631) in dev.taps or dev.taps, dev.taps


def test_calendar_without_ocr_is_unsupported(monkeypatch):
    import crawlers.app_ctrip as mod
    c = _crawler()
    monkeypatch.setattr("core.android.ocr.available", lambda: False)
    assert c.calendar("SHA", "PEK") == []
    assert c.paths[-1]["path"] == "android-ocr"
    assert c.paths[-1]["status"] == "unsupported"



    c = _crawler()
    assert c.name == "app_ctrip"
    assert c.package == "ctrip.android.view"
    assert c.supports_round_trip is True
    assert "ctrip.android.view" in c.login_url()


def test_find_flight_tile_uses_top_grid_not_bottom_nav():
    page = _xml('''
<node text="机票" bounds="[410,190][490,250]" />
<node text="机票" bounds="[410,1560][490,1600]" />
''')
    n = _find_flight_tile(page)
    assert n is not None and n["cy"] == 220


def test_ensure_form_taps_home_flight_tile_when_explicit_start_lands_home():
    c = _crawler()
    dev = FakeDev([_home(), _home(), _home(), _form()])
    dev.start_component = lambda comp: False
    form = c._ensure_form(dev)
    assert form and "depart date" in form
    assert (450, 220) in dev.taps


def test_collect_rows_merges_scrolled_pages_and_dedupes():
    c = _crawler()
    pages = [
        _xml(_card("CA8322", "700 ")),
        _xml(_card("MU5099", "800 ")),
        _xml(_card("CA8322", "690 ") + _card("HU7614", "820 ")),
        _xml(_card("HU7614", "820 ")),
    ]
    dev = FakeDev(pages)
    rows = c._collect_rows(dev, pages[0])
    got = {r["flight_no"]: r["price"] for r in rows}
    assert got["CA8322"] == 690.0
    assert got["MU5099"] == 800.0
    assert got["HU7614"] == 820.0
    assert dev.swipes <= 4


def test_collect_rows_keeps_first_page_when_scroll_breaks():
    c = _crawler()
    page = _xml(_card("CA8322", "700 "))
    dev = FakeDev([page])
    dev.dump = lambda: "<hierarchy rotation=\"0\"></hierarchy>"
    rows = c._collect_rows(dev, page)
    assert [r["flight_no"] for r in rows] == ["CA8322"]


def test_radar_deals_use_ctrip_calendar(monkeypatch):
    import logging
    from datetime import date, timedelta
    import core.special_radar as sr
    calls = {}
    # 区间必须相对今天：雷达按「今天→区间末」算 days，写死 11-05..11-08
    # 会在午夜翻日后从 7 变 6（2026-11-03 实测红）。
    today = date.today()
    start = today + timedelta(days=3)
    end = today + timedelta(days=6)

    class FakeCrawler:
        paths = [{"path": "app-calendar", "status": "ok"}]

        def __init__(self, cfg, logger):
            pass

        def low_fare(self, fc, tc, days=14, anchor_ymd=""):
            calls.update(fc=fc, tc=tc, days=days)
            return [{"date": start.isoformat(), "price": 390.0},
                    {"date": (start + timedelta(days=4)).isoformat(),
                     "price": 400.0}]

    monkeypatch.setattr("crawlers.app_ctrip.AppCtripCrawler", FakeCrawler)
    q = sr.parse_query({"from": "上海", "to": "北京",
                        "start": start.isoformat(), "end": end.isoformat(),
                        "channels": ["app_ctrip"]})
    rows, st = sr._app_ctrip_deals(q, logging.getLogger("ctrip_radar_test"))
    assert st["status"] == "ok", st
    assert calls == {"fc": "SHA", "tc": "BJS", "days": 7}, calls
    assert [r.date for r in rows] == [start.isoformat()], rows
    r = rows[0]
    assert r.src == "app_ctrip" and r.src_price == 390.0
    assert r.tax_included is None and r.price_basis_label == "口径未标注"


def test_radar_reports_visible_calendar_shortfall():
    """国际档只渲染两个月：返回行早于请求区间末尾时必须写明，不冒充全覆盖。"""
    import datetime as dt
    import logging
    import core.special_radar as sr
    today = dt.date.today()
    d1 = (today + dt.timedelta(days=1)).isoformat()
    d2 = (today + dt.timedelta(days=5)).isoformat()

    class FakeCrawler:
        paths = [{"path": "app-calendar", "status": "ok"}]

        def __init__(self, cfg, logger):
            pass

        def low_fare(self, fc, tc, days=14, anchor_ymd=""):
            return [{"date": d1, "price": 1200.0},
                    {"date": d2, "price": 1300.0}]

    import crawlers.app_ctrip as ac
    orig = ac.AppCtripCrawler
    ac.AppCtripCrawler = FakeCrawler
    try:
        q = sr.parse_query({"from": "上海", "to": "东京",
                            "start": d1,
                            "end": (today + dt.timedelta(days=30)).isoformat(),
                            "channels": ["app_ctrip"]})
        rows, st = sr._app_ctrip_deals(q, logging.getLogger("ctrip_radar_test"))
    finally:
        ac.AppCtripCrawler = orig
    assert rows and st["status"] == "ok", st
    assert "本次可见日历到 %s" % d2 in st["reason"], st


def test_radar_deals_out_of_window_is_empty():
    import datetime as dt
    import logging
    import core.special_radar as sr
    far = dt.date.today() + dt.timedelta(days=70)
    q = sr.parse_query({"from": "上海", "to": "北京",
                        "start": far.isoformat(),
                        "end": (far + dt.timedelta(days=2)).isoformat(),
                        "channels": ["app_ctrip"]})
    rows, st = sr._app_ctrip_deals(q, logging.getLogger("ctrip_radar_test"))
    assert rows == [] and st["status"] == "empty", st
    assert "62" in st["reason"], st
