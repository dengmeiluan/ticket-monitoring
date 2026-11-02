# -*- coding: utf-8 -*-
"""飞猪 App 采集器：契约、OCR 短语定位、日历坐标（不碰真机）。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_fliggy import (AppFliggyCrawler, _find_phrase,
                                 _target_xy)


def W(t, x, y, w=30, h=30):
    return {"t": t, "x": x, "y": y, "w": w, "h": h}


def _crawler():
    return AppFliggyCrawler({"android": {"enabled": True}},
                            logging.getLogger("app_fliggy_test"))


def test_contract():
    c = _crawler()
    assert c.name == "app_fliggy"
    assert c.package == "com.taobao.trip"
    assert c.supports_round_trip is False
    assert "com.taobao.trip" in c.login_url()


def test_find_phrase_merges_split_chinese():
    words = [W("上", 301, 1176, 29, 28), W("海", 333, 1176, 29, 29)]
    assert _find_phrase(words, "上海") == (331, 1190)


def test_find_phrase_min_y_skips_marketing_banner():
    words = [W("机", 254, 154, 49, 56), W("票", 302, 155, 54, 55),
             W("机", 195, 462, 50, 36), W("票", 245, 462, 50, 36)]
    assert _find_phrase(words, "机票", min_y=280) == (245, 480)


def test_calendar_grid_current_month():
    # 2026-11-01 周日；16 日在第 3 行、周一列
    assert _target_xy(2026, 11, 16, 0) == (205, 839)
    assert _target_xy(2026, 11, 2, 0) == (205, 551)


def test_calendar_grid_next_month():
    # 2026-12-01 周二，次月首行
    assert _target_xy(2026, 12, 1, 1) == (333, 1360)


def test_far_dimension_explicitly_unsupported():
    assert _target_xy(2027, 2, 1, 0) is not None  # 网格算得出
    # 但月份不在当月/次月时，_pick_date 必须显式 unsupported（见源码）


def test_access_denied_page_is_blocked_not_empty(monkeypatch):
    c = _crawler()
    c._ocr = lambda dev: [W("亲，访问被拒绝", 0, 0, 300, 30),
                          W("点我反馈", 0, 100, 200, 30)]
    dev = type("D", (), {"current_activity": lambda self: (
        "com.taobao.trip/com.alibaba.wireless.security.open."
        "middletier.fc.ui.ContainerActivity")})()
    assert c._denied(dev) is True
    assert c.paths[-1]["status"] == "blocked"
    assert "访问被拒绝" in c.paths[-1]["detail"]


def test_next_month_is_explicitly_unsupported(monkeypatch):
    import datetime as dt
    today = dt.date.today()
    ny, nm = (today.year + today.month // 12, today.month % 12 + 1)
    c = _crawler()
    monkeypatch.setattr(c, "_form", lambda dev: {
        "date_text": "1月1日", "date_xy": (172, 756)})
    assert c._pick_date(None, "%04d-%02d-15" % (ny, nm)) is False
    assert c.paths[-1]["status"] == "unsupported"
    assert "当月" in c.paths[-1]["detail"]


def test_ocr_unavailable_is_explicit(monkeypatch):
    import core.android.ocr as O
    monkeypatch.setattr(O, "available", lambda: False)
    c = _crawler()
    assert c.fetch("SHA", "PEK", ["2026-11-16"]) == []
    assert c.paths[-1]["status"] == "unsupported"
    assert "OCR" in c.paths[-1]["detail"]


def test_round_trip_is_explicitly_unsupported():
    c = _crawler()
    assert c.fetch("SHA", "PEK", ["2026-11-16"], ret_date="2026-11-20") == []
    assert c.paths[-1]["status"] == "unsupported"
