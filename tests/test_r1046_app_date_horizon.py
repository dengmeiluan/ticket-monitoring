# -*- coding: utf-8 -*-
"""App 渠道的**日期视野**守卫：超视野的日期不该再耗设备时间。

实测背景（2026-11-05）：生产对 `SHA→HAK 2027-01-29`（14 个月后）也派了
App 渠道，而各家的价格日历只覆盖 ~62 天。三个 App 渠道各白耗约 150 秒
设备时间（单设备，互相排队），单条航线就烧掉 7 分钟。

处置原则：这是**能力边界**，不是失败——必须记 `unsupported`，
不能记成 empty/timeout，否则会把"不支持"算成渠道质量问题，误伤爬取率统计。
"""
import datetime as dt
import logging

from crawlers.app_fliggy import AppFliggyCrawler


class _Dev:
    def current_activity(self):
        return ""


def _crawler():
    return AppFliggyCrawler({"user_data_dir": "user_data", "android": {}},
                            logging.getLogger("test"))


def _days_ahead(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_far_date_is_rejected():
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(400)]) is True
    note = c.paths[-1]
    assert note["status"] == "unsupported"
    assert "视野" in note["detail"]


def test_near_date_passes():
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(3)]) is False
    assert not c.paths


def test_horizon_boundary_is_inclusive():
    c = _crawler()
    horizon = c.date_horizon_days
    assert c.reject_far_dates([_days_ahead(horizon)]) is False
    assert c.reject_far_dates([_days_ahead(horizon + 1)]) is True


def test_mixed_dates_reject_whole_batch():
    """一批里有一条超视野，就整批交浏览器（App 侧无法只取其中一条）。"""
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(2), _days_ahead(400)]) is True


def test_bad_date_string_is_ignored_not_crashing():
    c = _crawler()
    assert c.reject_far_dates(["not-a-date"]) is False


def test_empty_dates_not_rejected():
    c = _crawler()
    assert c.reject_far_dates([]) is False
