# -*- coding: utf-8 -*-
"""r1574：开查前若前台是**别的 App 渠道**，要先停掉它（否则任务栈反复抢前台）。

现场（2026-11-11 同程 App 连续 0 条）：上一家渠道留下的
`ctrip.android.view` 任务栈压在栈顶，`_ensure_own_app` 只 app_start 自己，
切回同程首页后它又抢回前台——每轮都打一次「前台是 ctrip.android.view」，
表单刚打开就被顶掉，`app-city` 永远超时。

顺带纠正一个我自己的误判：这不是"同程的机票入口走携程模块"，
同程自己有 Flutter 表单（TCELFlutterBoostActivity）与自己的 H5 结果页
（WebViewActivity），实测四个入口点完都仍在 com.tongcheng.android。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)


class _Dev:
    def __init__(self, act, after=None):
        self.act = act
        self.after = after or act
        self.stops = []
        self.starts = []

    def current_activity(self):
        return self.act

    def app_stop(self, pkg):
        self.stops.append(pkg)
        self.act = self.after

    def app_start(self, pkg):
        self.starts.append(pkg)
        self.act = pkg + "/Main"


def _mk(pkg="com.tongcheng.android"):
    c = AppCrawler({}, _Log())
    c.name = "app_tongcheng"
    c.package = pkg
    c.logger = _Log()
    return c


def test_foreign_app_channel_is_stopped_not_just_switched():
    c = _mk()
    dev = _Dev("ctrip.android.view/ctrip.android.flight.FlightMainActivity",
               after="com.tongcheng.android/Home")
    c._ensure_own_app(dev)
    assert "ctrip.android.view" in dev.stops, (
        "前台残留的是别的 App 渠道，必须 force-stop 它，否则任务栈会反复抢前台：%s"
        % dev.stops)
    assert c.package in dev.starts, dev.starts


def test_unknown_package_is_not_killed():
    c = _mk()
    dev = _Dev("com.android.settings/.Settings", after="com.tongcheng.android/H")
    c._ensure_own_app(dev)
    assert dev.stops == [], "不是自家渠道的包不许乱停：%s" % dev.stops
    assert c.package in dev.starts, dev.starts


def test_already_own_app_does_nothing():
    c = _mk()
    dev = _Dev("com.tongcheng.android/.MainActivity")
    assert c._ensure_own_app(dev) is False
    assert dev.stops == [] and dev.starts == []
