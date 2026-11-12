# -*- coding: utf-8 -*-
"""r805bd：App 采集必须先锁竖屏——自动旋转一开，整轮就点不动。

现场实证（`debug/scene/qunar_app_20261101_183042_setcity-timeout-dep.txt`）：
首页控件全在（`atom_flight_tv_dep_city` 北京、搜索按钮都在），但那一帧 dump
是 **1600×900 横屏**（物理 900×1600、`accelerometer_rotation=1`）。脚本里的
滑动 `swipe(800, 1200, …, 600)` 的 y 已超出 900 屏高，城市页 30 秒内一次
都没打开，账本只记 `set-city-dep`——人眼看是「这条通路时好时坏」，其实是
设备被转屏了。

判据：设备层真的发出两条 settings 命令；统一前置里**先**锁竖屏再干别的。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_lock_portrait_issues_both_settings():
    from core.android.device import AdbDevice

    d = AdbDevice.__new__(AdbDevice)          # 不连 adb，只验命令拼装
    calls = []
    d._sh = lambda *a, **k: calls.append(tuple(a)) or ""
    assert d.lock_portrait() is True
    assert ("shell", "settings", "put", "system",
            "accelerometer_rotation", "0") in calls
    assert ("shell", "settings", "put", "system",
            "user_rotation", "0") in calls


def test_lock_portrait_reports_failure():
    from core.android.device import AdbDevice

    d = AdbDevice.__new__(AdbDevice)
    d._sh = lambda *a, **k: None        # 超时/失败
    assert d.lock_portrait() is False


def test_prepare_device_locks_portrait_first():
    """统一前置的第一步必须是锁竖屏：后面的点击全靠竖屏坐标。"""
    from crawlers.app_base import AppCrawler

    calls = []
    c = AppCrawler.__new__(AppCrawler)
    c.restore_login_snapshot = lambda dev: calls.append("restore")
    c._dismiss_system_prompts = lambda dev: calls.append("prompts")
    c.recover_anr = lambda dev, wait_s=30: calls.append("anr")

    class D:
        def lock_portrait(self):
            calls.append("portrait")
            return True

    c.prepare_device(D())
    assert calls == ["portrait", "restore", "prompts", "anr"], calls
