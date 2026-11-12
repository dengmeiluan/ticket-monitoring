# -*- coding: utf-8 -*-
"""同程 App 采集器：契约与日历定位（不碰真机）。"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import (AppTongchengCrawler, _city_hits,
                                   _find_city_hit, _form_slot, _letter_xy)


def _xml(body=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<hierarchy rotation="0">{body}</hierarchy>')


def _node(text, x1, y1, x2, y2, desc=""):
    return (f'<node text="{text}" content-desc="{desc}" '
            f'bounds="[{x1},{y1}][{x2},{y2}]" />')


def _crawler():
    return AppTongchengCrawler({"android": {"enabled": True}},
                               logging.getLogger("app_tongcheng_test"))


def test_contract():
    c = _crawler()
    assert c.name == "app_tongcheng"
    assert c.package == "com.tongcheng.android"
    assert c.supports_round_trip is True
    assert "com.tongcheng.android" in c.login_url()
    assert c._is_domestic("SHA", "PEK") is True
    assert c._is_domestic("SHA", "NRT") is False


def test_day_cell_matches_selected_cell_with_label_prefix():
    page = _xml(
        _node("2026年11月", 300, 440, 600, 480) +
        _node("出发\n16\n¥373", 170, 690, 246, 738,
              "出发\n16\n¥373") +
        _node("2026年12月", 300, 956, 600, 996) +
        _node("16\n¥360", 410, 1206, 490, 1254, "16\n¥360"))
    c = _crawler()
    assert c._day_cell(page, 2026, 11, 16) == (208, 714)


def test_day_cell_does_not_pick_same_day_in_other_month():
    page = _xml(
        _node("2026年11月", 300, 440, 600, 480) +
        _node("2026年12月", 300, 956, 600, 996) +
        _node("16\n¥360", 410, 1206, 490, 1254, "16\n¥360"))
    c = _crawler()
    assert c._day_cell(page, 2026, 11, 16) is None
    assert c._day_cell(page, 2026, 12, 16) == (450, 1230)


def test_calendar_window_collects_both_months_and_filters_window():
    from datetime import date
    from crawlers.app_tongcheng import _weekday_label
    page = _xml(
        _node("价格日历", 200, 240, 400, 280) +
        _node("仅看直飞", 700, 320, 800, 360) +
        _node("2026年11月", 300, 440, 600, 480) +
        _node("今天\n¥450", 170, 540, 246, 588) +
        _node("5\n¥360", 570, 540, 646, 588) +
        _node("2026年12月", 300, 956, 600, 996) +
        _node("5\n¥560", 570, 1056, 646, 1104) +
        _node("31\n¥999", 570, 1256, 646, 1304))
    c = _crawler()
    dev = FakeDev(page)
    anchor = date(2026, 11, 2)
    rows = c._calendar_window(dev, page, anchor, 40)
    assert dev.swipes == 0, "两月都在首屏时不该滚动"
    got = [(r["date"], r["price"]) for r in rows]
    assert got == [("2026-11-02", 450.0), ("2026-11-05", 360.0),
                   ("2026-12-05", 560.0)], got
    assert rows[0]["weekday"] == "今天"
    assert rows[1]["weekday"] == _weekday_label(date(2026, 11, 5), anchor)


class FakeDev:
    def __init__(self, page):
        self.page = page
        self.taps = []
        self.swipes = 0
        self.keys = 0
        self.back_to = ""

    def dump(self):
        return self.page

    def dump_u2(self):
        return ""

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def swipe(self, *a, **k):
        self.swipes += 1
        return True

    def keyevent(self, key):
        self.keys += 1
        if self.back_to:
            self.page = self.back_to
        return True


def _form_page():
    return _xml(
        _node("上海", 39, 443, 410, 489, "上海") +
        _node("北京", 490, 443, 861, 489, "北京") +
        _node("11月16日 周一", 39, 540, 450, 585, "11月16日 周一") +
        _node("机票查询", 39, 800, 861, 866, "机票查询"))


def test_form_slot_uses_dynamic_node_coords():
    page = _form_page()
    assert _form_slot(page, "dep", "上海") == (224, 466)
    assert _form_slot(page, "arr", "北京") == (675, 466)
    assert _form_slot(page, "date") == (244, 562)


def test_far_date_skips_before_touching_calendar():
    import datetime as dt
    c = _crawler()
    dev = FakeDev(_form_page())
    far = (dt.date.today() + dt.timedelta(days=c.MAX_AHEAD_DAYS + 1)).isoformat()
    assert c._pick_date(dev, far) is False
    assert dev.taps == [], dev.taps
    assert c.paths[-1]["status"] == "unsupported"


def test_pick_date_backs_out_of_result_page(monkeypatch):
    """同日多日期：上一日停在结果 WebView，必须先退回表单再点日期位。"""
    import crawlers.app_tongcheng as mod
    result_page = _xml(_node("上海→北京", 20, 200, 800, 260))
    form = _form_page()
    dev = FakeDev(result_page)
    dev.back_to = form
    c = _crawler()
    monkeypatch.setattr(mod, "is_calendar", lambda x: True)
    monkeypatch.setattr(c, "_day_cell", lambda *a: (100, 200))
    assert c._pick_date(dev, "2026-11-16") is True
    assert dev.keys == 1, dev.keys
    assert (244, 562) in dev.taps, dev.taps


def test_pick_date_reports_when_result_page_wont_back_out(monkeypatch):
    import crawlers.app_tongcheng as mod
    result_page = _xml(_node("上海→北京", 20, 200, 800, 260))
    dev = FakeDev(result_page)
    c = _crawler()
    monkeypatch.setattr(mod, "_wait", lambda *a, **k: dev.dump())
    assert c._pick_date(dev, "2026-11-16") is False
    assert dev.taps == [], dev.taps
    assert c.paths[-1]["status"] == "timeout"


def test_radar_deals_use_calendar_source(monkeypatch):
    """雷达 adapter 必须调同程日历、按请求区间过滤并标「口径未标注」。"""
    import datetime as dt
    import logging
    import core.special_radar as sr
    calls = {}

    class FakeCrawler:
        paths = [{"path": "app-calendar", "status": "ok"}]

        def __init__(self, cfg, logger):
            pass

        def low_fare(self, fc, tc, days=14, anchor_ymd=""):
            calls.update(fc=fc, tc=tc, days=days, anchor=anchor_ymd)
            _d0 = dt.date.today()
            return [
                {"date": _d0.isoformat(), "price": 360.0},
                # 区间外的一天，必须被过滤掉
                {"date": (_d0 + dt.timedelta(days=4)).isoformat(),
                 "price": 400.0},
            ]

    monkeypatch.setattr("crawlers.app_tongcheng.AppTongchengCrawler",
                        FakeCrawler)
    # **用相对日期**：parse_query 拒绝"开始日期早于今天"，
    # 写死具体日期会在跨过午夜后必然失败（2026-11-06 实际踩到）。
    _t0 = dt.date.today()
    q = sr.parse_query({"from": "上海", "to": "北京",
                        "start": _t0.isoformat(),
                        "end": (_t0 + dt.timedelta(days=3)).isoformat(),
                        "channels": ["app_tongcheng"]})
    rows, st = sr._app_tongcheng_deals(q, logging.getLogger("tc_radar_test"))
    assert st["status"] == "ok", st
    assert calls == {"fc": "SHA", "tc": "BJS", "days": 4,
                     "anchor": _t0.isoformat()}, calls
    assert [r.date for r in rows] == [_t0.isoformat()], rows
    r = rows[0]
    assert r.src == "app_tongcheng" and r.src_price == 360.0
    assert r.tax_included is None and r.price_basis_label == "口径未标注"


def test_radar_deals_out_of_window_is_empty_with_reason(monkeypatch):
    import datetime as dt
    import logging
    import core.special_radar as sr
    far = dt.date.today() + dt.timedelta(days=61)
    q = sr.parse_query({"from": "上海", "to": "北京",
                        "start": far.isoformat(),
                        "end": (far + dt.timedelta(days=2)).isoformat(),
                        "channels": ["app_tongcheng"]})
    rows, st = sr._app_tongcheng_deals(q, logging.getLogger("tc_radar_test"))
    assert rows == [] and st["status"] == "empty", st
    assert "60" in st["reason"], st
    """热门城市格顺序会变：坐标必须取当前页面，不能再信固定表。"""
    page = _xml(
        _node("上海", 153, 760, 381, 820, "上海") +
        _node("广州", 399, 760, 627, 820, "广州") +
        _node("上海", 153, 973, 381, 1033, "上海"))
    assert _city_hits(page, "上海") == [(267, 790), (267, 1003)]
    assert _city_hits(page, "北京") == []


def test_letter_xy_reads_current_index_column():
    page = _xml(_node("A", 37, 1301, 97, 1351, "A") +
                _node("S", 37, 1645, 97, 1695, "S"))
    assert _letter_xy(page, "S") == (67, 1670)
    assert _letter_xy(page, "Z") is None


def test_city_hit_skips_suggestion_card():
    page = _xml(
        _node("揭阳\n北京", 130, 470, 230, 520) +
        _node("上海", 220, 910, 314, 936) +
        _node("上海", 470, 700, 530, 730))
    hit = _find_city_hit(page, "上海")
    assert hit is not None and hit["cy"] == 923


def test_intl_calendar_without_direct_only_is_recognized_and_parsed():
    """国际日历没有「仅看直飞」，但有「价格走势」；不能因此判成没打开。"""
    from datetime import date
    from crawlers.app_tongcheng_parse import is_calendar, parse_calendar_days
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tongcheng_calendar_intl.xml")
    with open(path, encoding="utf-8") as f:
        xml = f.read()
    assert "仅看直飞" not in xml
    assert "价格走势" in xml
    assert is_calendar(xml)
    nov = parse_calendar_days(xml, 2026, 11, today=date(2026, 11, 3))
    assert nov[3] == 1495.0 and nov[7] == 1357.0 and nov[10] == 881.0
    dec = parse_calendar_days(xml, 2026, 12, today=date(2026, 11, 3))
    assert dec[1] == 923.0


def test_intl_result_uses_payable_price_not_crossed_list_price():
    """国际卡把划线列表价和实付价拆成两个节点：实付取最低，列表价保留。"""
    from crawlers.app_tongcheng_parse import parse_result_rows
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tongcheng_intl_result.xml")
    with open(path, encoding="utf-8") as f:
        rows = parse_result_rows(f.read())
    by = {r["flight_no"]: r for r in rows}
    assert by["9C8515"]["price"] == 875.0
    assert by["9C8515"]["list_price"] == 902.0
    assert "已省" in by["9C8515"]["discount_note"]
    assert by["GK036"]["price"] == 985.0
    assert by["GK036"]["list_price"] == 992.0
    assert by["MM876"]["price"] == 1004.0
    assert by["IJ006"]["price"] == 1061.0
    assert all(r["price"] != 27.0 for r in rows)


def _rt_picker_page():
    return _xml(
        _node("价格日历", 150, 230, 320, 290) +
        _node("价格走势", 550, 230, 770, 290) +
        _node("2026年11月", 300, 380, 600, 440) +
        _node("1", 60, 470, 114, 508) +
        _node("去程\n16\n¥2153", 170, 640, 246, 688) +
        _node("22\n¥2279", 60, 727, 114, 775) +
        _node("2026年12月", 300, 896, 600, 956) +
        _node("5\n¥2003", 780, 976, 846, 1024) +
        _node("确  定", 300, 1490, 600, 1546))


def test_round_trip_picker_cells_stay_in_month():
    c = _crawler()
    page = _rt_picker_page()
    assert c._range_day_cell(page, 2026, 11, 16) == (208, 664)
    assert c._range_day_cell(page, 2026, 11, 22) == (87, 751)
    assert c._range_day_cell(page, 2026, 12, 5) == (813, 1000)
    assert c._range_day_cell(page, 2026, 11, 31) is None


def test_round_trip_footer_allows_empty_return_after_dep_tap():
    c = _crawler()
    dep_only = _xml(_node(
        "日\n一\n二\n三\n四\n五\n六\n去程: 11-17\n返程: 未选择\n"
        "往返总价：￥--\n*所选日期均为出发地日期", 100, 1900, 800, 1960))
    assert c._rt_footer(dep_only) == (11, 17, None, None)
    both = _xml(_node(
        "去程: 11-17\n返程: 11-22\n往返总价：￥2420", 100, 1900,
        800, 1960))
    assert c._rt_footer(both) == (11, 17, 11, 22)


def test_round_trip_pick_dates_confirms_and_verifies_form(monkeypatch):
    """点去程→返程→确定，必须校验表单两个日期都真的变了。"""
    import crawlers.app_tongcheng as mod
    from crawlers.app_tongcheng_parse import parse_round_trip_form

    form = _xml(
        _node("上海", 150, 400, 300, 436) +
        _node("东京", 600, 400, 750, 436) +
        _node("11月16日\n周一", 180, 490, 310, 538) +
        _node("11月19日\n周四", 580, 490, 730, 538) +
        _node("机票查询", 39, 680, 861, 746))
    final = _xml(
        _node("上海", 150, 400, 300, 436) +
        _node("东京", 600, 400, 750, 436) +
        _node("11月17日\n周二", 180, 490, 310, 538) +
        _node("11月22日\n周日", 580, 490, 730, 538) +
        _node("机票查询", 39, 680, 861, 746))
    picker = _rt_picker_page()

    class RtDev(FakeDev):
        def tap(self, x, y):
            super().tap(x, y)
            if (x, y) == (245, 514):
                self.page = picker
            elif (x, y) == (450, 1518):
                self.page = final
            return True

    dev = RtDev(form)
    c = _crawler()
    state = {"picked": 0}

    def pick(dev_, y, m, d):
        state["picked"] += 1
        return True

    monkeypatch.setattr(mod, "_wait", lambda *a, **k: dev.dump())
    monkeypatch.setattr(mod, "is_calendar", lambda x: True)
    monkeypatch.setattr(c, "_tap_range_day", pick)
    monkeypatch.setattr(
        c, "_rt_footer",
        lambda page: (11, 17, None, None) if state["picked"] <= 1
        else (11, 17, 11, 22))
    assert c._pick_round_trip_dates(dev, "2026-11-17", "2026-11-22") is True
    assert state["picked"] == 2
    assert (245, 514) in dev.taps and (450, 1518) in dev.taps
    assert parse_round_trip_form(final)["dep_date"] == "11月17日"
    assert parse_round_trip_form(final)["ret_date"] == "11月22日"


def test_round_trip_pick_dates_rejects_return_before_departure():
    c = _crawler()
    dev = FakeDev(_form_page())
    assert c._pick_round_trip_dates(dev, "2026-11-22", "2026-11-17") is False
    assert dev.taps == []
    assert c.paths[-1]["status"] == "unsupported"


def test_fetch_round_trip_builds_marked_rows_from_real_page(monkeypatch):
    """结果页 → FlightPrice：每条 extra 必须是 RT + 回程日 + 页面总价口径。"""
    import crawlers.app_tongcheng as mod
    from crawlers.app_tongcheng_parse import parse_round_trip

    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tongcheng_roundtrip.xml")
    with open(path, encoding="utf-8") as f:
        result = f.read()
    parsed = parse_round_trip(result)
    assert parsed and parsed["total"] == 2209.0

    form = _xml(
        _node("上海", 150, 400, 300, 436) +
        _node("东京", 600, 400, 750, 436) +
        _node("11月16日\n周一", 180, 490, 310, 538) +
        _node("11月19日\n周四", 580, 490, 730, 538) +
        _node("机票查询", 39, 680, 861, 746))

    class RtDev(FakeDev):
        def tap(self, x, y):
            super().tap(x, y)
            if (x, y) == (450, 713):
                self.page = result
            return True

    dev = RtDev(form)
    c = _crawler()
    monkeypatch.setattr(c, "_ensure_form", lambda d: form)
    monkeypatch.setattr(c, "_set_round_trip_mode", lambda *a: True)
    monkeypatch.setattr(c, "_set_route", lambda *a: True)
    monkeypatch.setattr(c, "_pick_round_trip_dates", lambda *a: True)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    rows = c._fetch_round_trip_locked(
        dev, "SHA", "NRT", ["2026-11-16"], "2026-11-19")
    assert len(rows) == 1
    r = rows[0]
    assert r.price == 2209.0 and r.flight_no == "9C8515"
    assert r.depart_time == "21:10" and r.arrive_time == "01:05"
    ex = json.loads(r.extra)
    assert len(ex) == 7
    assert all(e["tripType"] == "RT" for e in ex)
    assert all(e["backDate"] == "2026-11-19" for e in ex)
    assert all(e["totalBasis"] == "page_roundtrip_total" for e in ex)
    assert all(e["retLoaded"] is True for e in ex)
    assert ex[0]["return_flight"] == "9C6218"
    assert ex[0]["return_surcharge"] == 0.0
    ok = [p for p in c.paths if p["path"] == "往返" and p["status"] == "ok"]
    assert ok and ok[-1]["rows"] == 7, c.paths


def test_fetch_round_trip_marks_ret_loaded_false_when_return_bar_missing(
        monkeypatch):
    """返程栏 30s 没加载完：仍可按去程行总价落账，但必须显式 retLoaded=false。"""
    import crawlers.app_tongcheng as mod

    form = _xml(
        _node("上海", 150, 400, 300, 436) +
        _node("东京", 600, 400, 750, 436) +
        _node("11月16日\n周一", 180, 490, 310, 538) +
        _node("11月19日\n周四", 580, 490, 730, 538) +
        _node("机票查询", 39, 680, 861, 746))
    parsed = {
        "total": 2209.0,
        "outbounds": [{
            "flight_no": "9C8515", "airline": "春秋航空",
            "dep_time": "21:10", "arr_time": "01:05", "arr_date": "",
            "dep_airport": "浦东T2", "arr_airport": "羽田机场T3",
            "duration": "2时55分", "seats": "余2张", "price": 2209.0}],
        "returns": [], "selected_return": None,
        "dep_date": "11-16", "ret_date": "11-19", "note": "",
    }
    dev = FakeDev(form)
    c = _crawler()
    monkeypatch.setattr(c, "_ensure_form", lambda d: form)
    monkeypatch.setattr(c, "_set_round_trip_mode", lambda *a: True)
    monkeypatch.setattr(c, "_set_route", lambda *a: True)
    monkeypatch.setattr(c, "_pick_round_trip_dates", lambda *a: True)
    monkeypatch.setattr(mod, "parse_round_trip", lambda page: parsed)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mod, "_RT_RET_WAIT_S", 0)
    rows = c._fetch_round_trip_locked(
        dev, "SHA", "NRT", ["2026-11-16"], "2026-11-19")
    assert len(rows) == 1
    ex = json.loads(rows[0].extra)
    assert all(e["retLoaded"] is False for e in ex)
    ok = [p for p in c.paths if p["path"] == "往返" and p["status"] == "ok"]
    assert ok and "retLoaded=false" in ok[-1]["detail"], ok
