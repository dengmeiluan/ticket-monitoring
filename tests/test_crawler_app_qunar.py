# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r695_app_qunar_low_fare_radar.py
- tests/test_r805aa_app_qunar_intl_boundary.py
- tests/test_r822_app_qunar_calendar_dir.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import core.special_radar as sr
import io
import os
import sys

from crawlers.app_qunar import _calendar_scroll_dir
from ledger_fixture import groups as _ledger_groups


# ---- merged from tests/test_r695_app_qunar_low_fare_radar.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _query(channels=("app_qunar",)):
    import datetime as dt
    today = dt.date.today()
    return sr.RadarQuery(
        user="t", from_code="BJS", from_name="北京", to_code="SHA",
        to_name="上海", start=today,
        end=today + dt.timedelta(days=13), channels=list(channels))


def test_app_qunar_is_a_radar_channel():
    assert "app_qunar" in sr._CHANNELS, sr._CHANNELS


def test_deals_mark_basis_unknown_when_page_says_nothing(monkeypatch):
    """页面没写口径时必须标「未标注」，不能假设含税。"""
    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "14 天最低价"}]

        def low_fare(self, fc, tc, days=14):
            import datetime as dt
            d = dt.date.today()
            return [{"date": d.isoformat(), "weekday": "今天", "price": 358},
                    {"date": (d + dt.timedelta(days=1)).isoformat(),
                     "weekday": "明天", "price": 420}]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert st["status"] == "ok" and st["rows"] == 2, st
    assert [r.src_price for r in rows] == [358.0, 420.0]
    for r in rows:
        # 页面没写口径 → 只能是 unknown（标含税会让人误当到手价）
        assert r.tax_included is None
        assert r.price_basis == "unknown"
        assert r.price_basis_label == "口径未标注"
        assert r.src == "app_qunar"


def test_blocked_source_is_error_not_empty(monkeypatch):
    """被登录/风控挡住时账本要写 error，不能记 empty（那是「没低价」）。"""
    class Fake:
        paths = [{"path": "low-fare", "status": "login",
                  "detail": "查询后要求登录"}]

        def low_fare(self, fc, tc, days=14):
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert rows == []
    assert st["status"] == "error", st
    assert "登录" in st["reason"]


def test_truly_no_low_fare_is_empty(monkeypatch):
    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "0 天最低价"}]

        def low_fare(self, fc, tc, days=14):
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert rows == [] and st["status"] == "empty", st


def test_future_range_requests_strip_from_today(monkeypatch):
    """日期带从今天起算：未来 11-10..11-12 必须请求 11 天，不能只请求 3 天。

    负控：改回 `(end-start).days+1` 时 fake 只拿到 3 天，返回 11-02..11-04，
    过滤后为空——这正是 r815 线上 176s/empty 的形态。
    """
    import datetime as dt
    today = dt.date.today()
    seen = {}

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            seen["days"] = days
            return [{"date": (today + dt.timedelta(days=i)).isoformat(),
                     "price": 300 + i} for i in range(days)]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=8),
                      today + dt.timedelta(days=10), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert seen["days"] == 11, seen
    assert len(rows) == 3 and st["status"] == "ok", st
    assert {r.date for r in rows} == {
        (today + dt.timedelta(days=i)).isoformat() for i in (8, 9, 10)}


def test_range_beyond_strip_has_reason_not_bare_empty(monkeypatch):
    """超出 14 天日期带要明确说原因，不能只回一个无理由的 empty。"""
    import datetime as dt
    today = dt.date.today()
    called = {"n": 0}

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            called["n"] += 1
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=20),
                      today + dt.timedelta(days=22), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert rows == [] and st["status"] == "empty", st
    assert "14 天" in st["reason"], st
    assert called["n"] == 0, "已知超出日期带仍去开真机（会白等）"


def test_returned_strip_missing_request_range_has_reason(monkeypatch):
    """App 只回今天附近而请求在更远日期：必须报「未覆盖」，不能裸 empty。"""
    import datetime as dt
    today = dt.date.today()

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            return [{"date": (today + dt.timedelta(days=i)).isoformat(),
                     "price": 300} for i in range(3)]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=8),
                      today + dt.timedelta(days=10), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert rows == [] and st["status"] == "empty", st
    assert "未覆盖" in st["reason"], st


def test_build_radar_routes_app_qunar(monkeypatch):
    """分发必须真的走到 _app_qunar_deals，不能落到 not_connected。"""
    called = {}

    def fake_deals(q, logger):
        called["yes"] = True
        return [], sr._status("ok", "", 0)

    monkeypatch.setattr(sr, "_app_qunar_deals", fake_deals)
    import datetime as dt
    today = dt.date.today()
    out = sr.build_radar({"user": "t", "from": "BJS", "to": "SHA",
                          "start": today.isoformat(),
                          "end": (today + dt.timedelta(days=5)).isoformat(),
                          "channels": ["app_qunar"]}, None)
    assert called.get("yes"), "build_radar 没分发到 app_qunar"
    assert "app_qunar" in out["channels"]


# ---- merged from tests/test_r805aa_app_qunar_intl_boundary.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _ledger():
    """App 渠道按状态的聚合成交证据（本机生产库优先，快照回放）。"""
    rows = []
    for plat, _path, st, runs, rws in _ledger_groups(recent=True):
        if not str(plat).startswith("app"):
            continue
        rows.append((plat, st, runs, rws))
    return rows


def test_app_qunar_intl_not_downgraded_from_ledger_failure():
    """国际声明不许因为「账本没出数」被降级——那不是能力缺失。

    判据用**行为对照**：若 app_qunar 的国内航线在同一账本里也被大面积
    判 timeout，那这条通路的问题是整体的（设备/时序），不能归因到 intl。
    """
    rows = _ledger()
    assert rows, "App 账本证据为空：快照与生产库都不可读"
    from core.channels import CHANNEL_DIMENSIONS
    by = {}
    for plat, st, n, rws in rows:
        by.setdefault(plat, {}).setdefault(st, 0)
        by[plat][st] += n
    aq = by.get("app_qunar") or {}
    to = aq.get("timeout", 0)
    ok = aq.get("ok", 0)
    # 只有「国际失败但国内健康」时才允许把问题归因到 intl 维度
    if to > ok * 2:
        assert CHANNEL_DIMENSIONS["app_qunar"]["intl"] != "n", (
            "app_qunar 整条通路 timeout %d / ok %d（国内国际一起失败），"
            "这是设备时序问题，不是 intl 维度缺失——不许据此降级声明"
            % (to, ok))


def test_home_mark_does_not_match_calendar_page():
    """日历页不含 _HOME_MARK——用真机 dump（若在）固化为回归样本。

    没有样本文件时跳过（本判据的价值在于防止有人把 `_HOME_MARK`
    改成日历页也含的 id，从而让 `_ensure_home` 静默返回日历页）。
    """
    from crawlers.app_qunar import _HOME_MARK
    sample = os.path.join(ROOT, "tests", "fixtures", "qunar_calendar_home.xml")
    assert os.path.isfile(sample), "真机 dump 样本缺失：%s" % sample
    xml = io.open(sample, encoding="utf-8", errors="replace").read()
    assert "atom_flight_hs_calendar" in xml, "样本不是日历页，判据失去靶子"
    assert _HOME_MARK not in xml, (
        "_HOME_MARK=%r 出现在日历页 dump 里：_ensure_home 会误判"
        "「已在首页」而直接返回日历页，后续设城市必然失败" % _HOME_MARK)


# ---- merged from tests/test_r822_app_qunar_calendar_dir.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
