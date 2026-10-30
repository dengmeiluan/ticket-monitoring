# -*- coding: utf-8 -*-
"""r674：App 渠道的「全渠道统一」契约 + 去哪儿多日期/多航线稳定性。

统一的三件事必须由基类提供，而不是各渠道各写一份：
  1. 城市名映射（`_city_name`）——曾只有智行有，去哪儿另抄 12 条别名表；
  2. 航线判定（`_route_unchanged` + `read_route` 钩子）——曾只有智行有；
  3. 逐日期记账（`note_date`）——两个渠道各写一遍，empty 判据还不一致。

多日期稳定性靠两点保证：
  * 航线未变时不重复设城市（否则每个日期白花 ~20s）；
  * 选日失败**不搜索**（列表页无法校验属于哪天，搜下去会把上一个日期的
    价格记到目标日期名下——日期错位价，比缺数据更糟）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler
from crawlers.app_qunar import AppQunarCrawler
from crawlers.app_zhixing import AppZhixingCrawler


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _qunar():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.paths = []
    c.login_suspect = False
    c.logger = _Log()
    return c


def _zhixing():
    c = AppZhixingCrawler.__new__(AppZhixingCrawler)
    c.name = "app_zhixing"
    c.paths = []
    c.logger = _Log()
    return c


# ---------- 一、全渠道统一：能力都在基类 ----------
def test_route_memory_lives_in_base_for_all_app_channels():
    for cls in (AppQunarCrawler, AppZhixingCrawler):
        assert issubclass(cls, AppCrawler)
        # 两个渠道都从基类继承同一份判据，不再各自实现
        assert cls._route_unchanged is AppCrawler._route_unchanged, cls
        assert cls._city_name is AppCrawler._city_name, cls
        assert cls.note_date is AppCrawler.note_date, cls


def test_city_name_is_single_source():
    """三字码 → 中文城市名：两个渠道必须给同一个答案。"""
    for code, want in (("SHA", "上海"), ("PEK", "北京"), ("CAN", "广州"),
                       ("CTU", "成都")):
        assert AppQunarCrawler._city_name(code) == want, code
        assert AppZhixingCrawler._city_name(code) == want, code


def test_unknown_city_code_passes_through():
    """查不到就原样传下去——宁可显式失败，不要瞎猜一个城市。"""
    assert AppCrawler._city_name("ZZZ") == "ZZZ"
    assert AppCrawler._city_name("") == ""


def test_qunar_no_longer_has_private_alias_table():
    """去哪儿不得再维护第二套城市别名表。"""
    import crawlers.app_qunar as M
    assert not hasattr(M, "_CITY_ALIAS"), "去哪儿又抄了一份城市别名表"


# ---------- 二、逐日期记账单源 ----------
def test_note_date_semantics_are_one_source():
    c = _qunar()
    c.note_date("2026-11-01", [{"price": 1}], "ok")
    c.note_date("2026-11-02", [], "empty")             # 确认无航班
    c.note_date("2026-11-03", [], "no-list-page")      # 没采到
    c.note_date("2026-11-04", [], "pick-date-failed")
    got = [(p["date"], p["status"]) for p in c.paths]
    assert got == [("2026-11-01", "ok"), ("2026-11-02", "empty"),
                   ("2026-11-03", "timeout"), ("2026-11-04", "timeout")], got
    # 通路名与智行/浏览器一致
    assert {p["path"] for p in c.paths} == {"航班明细"}


def test_empty_still_requires_reason():
    """只有 reason=="empty" 才记 empty；其它原因一律 timeout。"""
    c = _qunar()
    for why in ("no-home", "set-city-dep", "no-search-button",
                "", "exception:TimeoutError"):
        c.note_date("2026-11-0" + str(len(c.paths) + 1), [], why)
    assert all(p["status"] == "timeout" for p in c.paths), c.paths


# ---------- 三、去哪儿多日期 ----------
def test_multi_date_records_one_row_per_date():
    """两个日期各记一条账，日期不串。"""
    c = _qunar()
    calls = []

    def fake_one(dev, fn, tn, target, fc="", tc=""):
        calls.append(target)
        rows = [{"flight_no": "CA100", "depart_time": "08:00",
                 "arrive_time": "10:00", "price": 300}]
        return c._to_prices(rows, target, "BJS", "SHA"), "ok"

    c._open_flight_home = lambda dev: True
    c._ensure_home = lambda dev: "<x/>"
    c._one_date = fake_one
    out = c._fetch_locked(_Dev(), "BJS", "SHA", ["2026-11-01", "2026-11-02"])
    assert calls == ["2026-11-01", "2026-11-02"], calls
    assert [o.depart_date for o in out] == ["2026-11-01", "2026-11-02"]
    assert [(p["date"], p["status"]) for p in c.paths] == [
        ("2026-11-01", "ok"), ("2026-11-02", "ok")]


def test_multi_date_failure_is_isolated():
    """一个日期失败，另一个照常产出；失败日不记 empty。"""
    c = _qunar()

    def fake_one(dev, fn, tn, target, fc="", tc=""):
        if target == "2026-11-02":
            return [], "pick-date-failed"
        rows = [{"flight_no": "CA100", "depart_time": "08:00",
                 "arrive_time": "10:00", "price": 300}]
        return c._to_prices(rows, target, "BJS", "SHA"), "ok"

    c._open_flight_home = lambda dev: True
    c._ensure_home = lambda dev: "<x/>"
    c._one_date = fake_one
    out = c._fetch_locked(_Dev(), "BJS", "SHA", ["2026-11-01", "2026-11-02"])
    assert [o.depart_date for o in out] == ["2026-11-01"]
    st = {p["date"]: p["status"] for p in c.paths}
    assert st == {"2026-11-01": "ok", "2026-11-02": "timeout"}, st


def test_route_unchanged_skips_setting_cities():
    """航线未变时不得重复设城市（多日期下每日期省 ~20s）。"""
    c = _qunar()
    set_calls = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")
    c._set_city = lambda dev, xml, city, side: set_calls.append(city) or True
    c._pick_date = lambda dev, xml, target: True
    c._search_and_parse = lambda dev, target, fc="", tc="": ([], "empty")

    c._one_date(_Dev(), "北京", "上海", "2026-11-01", "BJS", "SHA")
    assert set_calls == [], "航线已对却还在重设城市：%s" % set_calls


def test_route_changed_sets_both_cities():
    """航线变了要按顺序重设出发+到达。"""
    c = _qunar()
    set_calls = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")      # 屏幕上是旧航线
    c._set_city = lambda dev, xml, city, side, intl=False: set_calls.append((side, city)) or True
    c._pick_date = lambda dev, xml, target: True
    c._search_and_parse = lambda dev, target, fc="", tc="": ([], "empty")

    c._one_date(_Dev(), "北京", "广州", "2026-11-01", "BJS", "CAN")
    assert set_calls == [("dep", "北京"), ("arr", "广州")], set_calls


def test_pick_date_failure_does_not_search():
    """选日失败时绝不能搜——否则会把上一个日期的价记到目标日期名下。"""
    c = _qunar()
    searched = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")
    c._set_city = lambda dev, xml, city, side, intl=False: True
    c._pick_date = lambda dev, xml, target: False
    c._search_and_parse = lambda dev, target, fc="", tc="": (
        searched.append(target) or ([], "ok"))

    got, why = c._one_date(_Dev(), "北京", "上海", "2026-11-02", "BJS", "SHA")
    assert got == []
    assert why == "pick-date-failed", why
    assert searched == [], "选日失败却仍然搜了：%s" % searched


def test_read_route_reads_home_city_fields():
    """read_route 从首页城市控件取事实，不在首页返回 None。"""
    c = _qunar()

    class D:
        def __init__(self, xml):
            self._xml = xml

        def dump(self, retries=2):
            return self._xml

    home = ('<hierarchy><node resource-id="com.Qunar:id/atom_flight_search_panel_view"'
            ' bounds="[0,397][1600,826]" />'
            '<node text="北京" resource-id="com.Qunar:id/atom_flight_tv_dep_city"'
            ' bounds="[48,487][120,540]" />'
            '<node text="上海" resource-id="com.Qunar:id/atom_flight_tv_arr_city"'
            ' bounds="[1480,487][1552,540]" /></hierarchy>')
    assert c.read_route(D(home)) == ("北京", "上海")
    assert c.read_route(D("<hierarchy></hierarchy>")) is None


class _Dev:
    """最小设备替身：dump + swipe（滚动是链路的一部分，必须能记录）。"""

    def __init__(self):
        self.swipes = []

    def dump(self, retries=2):
        return '<hierarchy><node text="x" bounds="[0,0][1,1]" /></hierarchy>'

    def swipe(self, x1, y1, x2, y2, dur=400):
        self.swipes.append((x1, y1, x2, y2))
        return True

    def tap(self, x, y):
        return True


# ---------- 四、与 PC/H5 对齐：不支持的维度要显式落账 ----------
def test_round_trip_is_explicit_unsupported():
    """App 渠道不支持往返时必须显式记 unsupported 并返回空。

    静默忽略 ret_date 会把单程价当成往返总价，推送/走势据此报警——
    浏览器渠道（qunar TRIP）就是显式 unsupported 的口径，App 必须同款。
    """
    for cls in (AppQunarCrawler, AppZhixingCrawler):
        c = cls.__new__(cls)
        c.name = getattr(cls, "name", "app")
        c.paths = []
        c.logger = _Log()
        c.last_error = ""
        called = []
        c.fetch = lambda *a, **k: called.append(1) or []
        out = c.safe_fetch("SHA", "CAN", ["2026-11-01"], ret_date="2026-11-05")
        assert out == []
        assert called == [], "不支持往返却仍发起了单程查询：%s" % cls
        st = [(p["path"], p["status"]) for p in c.paths]
        assert ("TRIP", "unsupported") in st, st


def test_channel_declares_round_trip_support_flag():
    """能力是**声明式**的：基类默认 False，将来支持往返的渠道改一处即可。"""
    assert AppCrawler.supports_round_trip is False
    assert AppQunarCrawler.supports_round_trip is False
    assert AppZhixingCrawler.supports_round_trip is False


def test_supported_round_trip_channel_is_not_blocked():
    """声明支持的渠道不得被这道闸门拦下。"""
    c = _qunar()
    c.last_error = ""
    c.supports_round_trip = True
    hit = []
    c.fetch = lambda *a, **k: hit.append(k.get("ret_date")) or []
    c.safe_fetch("SHA", "CAN", ["2026-11-01"], ret_date="2026-11-05")
    assert hit == ["2026-11-05"], hit
