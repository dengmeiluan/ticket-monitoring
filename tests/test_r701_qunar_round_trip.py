# -*- coding: utf-8 -*-
"""r701：去哪儿 App 往返是真能力——双列 + 页脚「往返价格」。

真机 dump（2026-10-31，北京⇄上海 11-05 → 11-27，1600×900）。页面带
结构化 content-desc，不用按几何猜：

    FlightsRound_go_selected / _unselected    去程卡
    go_depPrice                               去程段价（726 / 730 / 746）
    FlightsRound_back_selected / _unselected  返程卡
    back_supplyPrice                          **返程加价**（0 / 16 / 39）
    页脚 ¥726 + 往返价格                      当前选中对的总价

三条必须守住的判据：
  * `back_supplyPrice` 是加价不是票价，当票价就是 0 元假数据；
  * 卡按 y 分段配对（卡高 165–179px，首尾相接），不能用文档顺序；
  * 页脚总价只在**当前选中组合**下有效，缺 `往返价格` 时返回 None，
    不能拿列表里的某个 ¥ 顶替。

另有一条航司代码坑：`川航3U4553` 这类以数字开头的代码，旧正则
`[A-Z]{2}\\d{3,4}` 匹配不到 → 航班号空。四个解析器（去哪儿单程/往返、
智行单程/往返）统一改成 `[A-Z0-9]{2}\\d{3,4}`。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar_roundtrip import (is_round_trip_page, parse_back_rows,
                                          parse_footer_total, parse_go_rows)

_P = "flight_module_search|"


def _n(desc, text, x1, y1, x2, y2):
    return ('<node text="%s" content-desc="%s" resource-id="" '
            'class="android.widget.TextView" bounds="[%d,%d][%d,%d]" />'
            % (text, desc, x1, y1, x2, y2))


def _go_card(y1, y2, fno, price, dep, arr, selected):
    state = "selected" if selected else "unselected"
    return (_n(_P + "QunarFlightList|FlightsRound_go_" + state, "", 0, y1, 796, y2)
            + _n(_P + "QunarFlightList|FlightsRound_" + fno, "", 0, y1, 796, y2)
            + _n(_P + "round_way_flights|go_depTime", dep, 15, y1 + 37, 78, y1 + 67)
            + _n(_P + "round_way_flights|go_arrTime", arr, 144, y1 + 37, 207, y1 + 67)
            + _n(_P + "round_way_flights|go_aircraftType", "x" + fno,
                 15, y1 + 107, 704, y1 + 128)
            + _n(_P + "round_way_flights|go_depPrice", price,
                 719, y1 + 98, 761, y1 + 131))


def _back_card(y1, y2, fno, supply, dep, arr, selected):
    state = "selected" if selected else "unselected"
    return (_n(_P + "QunarFlightList|FlightsRound_back_" + state, "", 805, y1, 1600, y2)
            + _n(_P + "QunarFlightList|FlightsRound_" + fno, "", 805, y1, 1600, y2)
            + _n(_P + "round_way_flights|back_depTime", dep, 820, y1 + 37, 883, y1 + 67)
            + _n(_P + "round_way_flights|back_arrTime", arr, 949, y1 + 37, 1012, y1 + 67)
            + _n(_P + "round_way_flights|back_aircraftType", "x" + fno,
                 820, y1 + 113, 1452, y1 + 134)
            + _n(_P + "round_way_flights|back_supplyPrice", supply,
                 1565, y1 + 106, 1579, y1 + 139))


def _page(total=None):
    xml = ('<hierarchy>'
           + _n(_P + "QunarFlightList|ScrollView_go", "", 0, 348, 796, 827)
           + _go_card(348, 527, "HO1258", "726", "11:55", "14:10", True)
           + _go_card(527, 692, "CZ8882", "730", "14:00", "16:30", False)
           + _go_card(693, 827, "HO1254", "746", "21:20", "23:30", False)
           + _n(_P + "QunarFlightList|ScrollView_back", "", 805, 348, 1600, 827)
           + _back_card(348, 533, "HO1251", "0", "10:25", "12:40", True)
           + _back_card(533, 704, "HO1257", "16", "08:25", "10:50", False)
           # 真机第三张卡被屏幕底部裁到 827，航司行只剩一半——仍要整卡
           # 归属正确（这里给足高度，模拟滚动后完整可见的形态）
           + _back_card(705, 859, "3U4553", "39", "08:25", "10:50", False))
    if total is not None:
        xml += (_n("", "¥" + total, 27, 834, 98, 879)
                + _n("", "往返价格", 27, 876, 1369, 894))
    return xml + '</hierarchy>'


def test_page_marker():
    assert is_round_trip_page(_page())
    assert not is_round_trip_page("<hierarchy></hierarchy>")


def test_go_rows_pair_price_with_own_card():
    rows = parse_go_rows(_page())
    assert [r["flight_no"] for r in rows] == ["HO1258", "CZ8882", "HO1254"]
    assert [r["price"] for r in rows] == [726, 730, 746]
    assert rows[0]["depart_time"] == "11:55"
    assert rows[1]["arrive_time"] == "16:30"


def test_back_supply_price_is_not_a_fare():
    rows = parse_back_rows(_page())
    # 0 是「补 0 元」的真实读数（不是缺失）；不能因为 falsy 被丢掉
    assert [r["supply_price"] for r in rows] == [0, 16, 39]
    assert [r["flight_no"] for r in rows] == ["HO1251", "HO1257", "3U4553"]


def test_numeric_prefix_airline_code_survives():
    # 3U4553（川航）在旧正则 `[A-Z]{2}\\d{3,4}` 下会被解析成空字符串
    rows = parse_back_rows(_page())
    assert rows[2]["flight_no"] == "3U4553"


def test_footer_total_only_when_label_present():
    assert parse_footer_total(_page("726")) == 726
    # 没有「往返价格」页脚（未选中组合）时绝不拿列表里的 ¥ 顶替
    assert parse_footer_total(_page(None)) is None


def test_footer_prefers_total_over_card_price():
    """页脚 ¥726 与首卡 go_depPrice 726 同值时也不能混淆来源。

    改成页脚 941（=947 去程 + -6 补价，真机实测过这组）后仍要读 941，
    证明取的是页脚而不是卡内价。
    """
    xml = _page("941")
    assert parse_footer_total(xml) == 941


def test_empty_page_yields_nothing():
    assert parse_go_rows("<hierarchy></hierarchy>") == []
    assert parse_back_rows("<hierarchy></hierarchy>") == []
    assert parse_footer_total("<hierarchy></hierarchy>") is None


def test_intl_round_trip_is_recorded_as_unsupported_not_timeout(monkeypatch):
    """国际档不给往返结果页：账本要写 unsupported，不能只写 no-list-page。

    现场（2026-11-01 SHA→LHR）：表单确实是「往返 + 去程 11-23 + 返程 11-30」，
    搜索后却是 25 张 `QunarFlightInterList` 单程卡（无 ScrollView_go/back、
    无「往返价格」页脚）。那 60 秒等待只是在等一个不会出现的页面；结果如果
    只记 no-list-page，读起来像「页面没打开」。
    """
    import crawlers.app_qunar as M

    ticks = {"t": 0.0}

    class FakeTime:
        @staticmethod
        def time():
            ticks["t"] += 1.0
            return ticks["t"]

        @staticmethod
        def sleep(_s):
            pass

        strftime = staticmethod(lambda fmt: "20261101_000000")

        def __getattr__(self, k):
            return getattr(__import__("time"), k)

    monkeypatch.setattr(M, "time", FakeTime)
    monkeypatch.setattr(M, "_sleep", lambda s: None)

    page = ('<hierarchy><node text="搜索" bounds="[48,769][1552,826]" />'
            '<node text="02:25" bounds="[39,384][116,426]" />'
            '<node text="07:10" bounds="[283,384][357,426]" />'
            '</hierarchy>')

    class D:
        def dump(self, retries=2):
            return page

        def tap(self, x, y):
            return True

    c = M.AppQunarCrawler.__new__(M.AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.paths = []
    c.login_suspect = False
    c._set_round_trip_form = lambda *a, **k: (True, "")
    c._scroll_home = lambda dev, want="search": page
    notes, dates = [], []
    c.path_note = lambda *a, **k: notes.append((a, k))
    c.note_date = lambda *a, **k: dates.append((a, k))

    prices = c._fetch_round_trip_locked(D(), "SHA", "LHR",
                                        ["2026-11-23"], "2026-11-30")
    assert prices == []
    trips = [n for n in notes if n[0] and n[0][0] == "TRIP"]
    assert trips, "国际往返没有记 TRIP 路径"
    assert trips[0][0][1] == "unsupported", (
        "国际档无往返结果页应记 unsupported，实际 %r" % (trips[0],))
    assert "国际" in str(trips[0][1].get("detail", "")), (
        "说明里要写清是国际档：%r" % (trips[0],))
    assert any(d[0][2] == "no-list-page" for d in dates if len(d[0]) > 2), (
        "日期级仍要如实记 no-list-page：%r" % (dates,))
