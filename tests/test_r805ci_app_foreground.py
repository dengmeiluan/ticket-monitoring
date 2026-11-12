# -*- coding: utf-8 -*-
"""r805ci：App 采集前，前台必须是自家包。

实测（2026-11-02）：模拟器先采集去哪儿、再采集智行，智行那一轮 dump 出来
全是 `com.Qunar:id/...`——去哪儿还停在前台。原 `prepare_device` 只做
竖屏/快照/权限框/ANR，**从不校验前台是哪个 App**，于是智行照着去哪儿首页
解析，账本记成「页面选择不覆盖」，人看是「这条通路没数据」。

四个判据：
  1) 前台是别的包 → 真的调 app_start(自家包)，并且切成功后返回 True；
  2) 前台已经是自家包 → 一次 app_start 都不发（不无故重启 App）；
  3) activity 读不到 → 判不了就不动手（adb 慢不该触发重启）；
  4) 启动后前台仍是别人 → 如实返回 False 并留告警，不假装切好了。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _crawler(package="cn.suanya.zhixing"):
    import logging
    from crawlers.app_base import AppCrawler

    c = AppCrawler.__new__(AppCrawler)
    c.name = "app_zhixing"
    c.package = package
    c.logger = logging.getLogger("test-foreground")
    return c


class _Dev:
    def __init__(self, acts, start_moves=True):
        self.acts = list(acts)
        self.start_moves = start_moves
        self.started = []

    def current_activity(self):
        if len(self.acts) > 1:
            return self.acts.pop(0)
        return self.acts[0]

    def app_start(self, pkg):
        self.started.append(pkg)
        if self.start_moves:
            self.acts = [pkg + "/com.app.main.entrance.MainActivity"]
        return True


def test_switches_back_when_other_app_is_foreground(monkeypatch):
    import crawlers.app_base as ab
    monkeypatch.setattr(ab.time, "sleep", lambda s: None)
    c = _crawler()
    d = _Dev(["com.Qunar/com.mqunar.atom.flight.modules.home.TabHomeActivity"])
    assert c._ensure_own_app(d) is True
    assert d.started == ["cn.suanya.zhixing"], d.started


def test_does_not_restart_own_app(monkeypatch):
    import crawlers.app_base as ab
    monkeypatch.setattr(ab.time, "sleep", lambda s: None)
    c = _crawler()
    d = _Dev(["cn.suanya.zhixing/com.app.main.entrance.MainActivity"])
    assert c._ensure_own_app(d) is False
    assert d.started == [], "前台已是自家包还重启了 App"


def test_unreadable_activity_takes_no_action(monkeypatch):
    import crawlers.app_base as ab
    monkeypatch.setattr(ab.time, "sleep", lambda s: None)
    c = _crawler()
    d = _Dev([""])
    assert c._ensure_own_app(d) is False
    assert d.started == [], "读不到 activity 就重启 App 属于瞎猜"


def test_reports_failure_when_foreground_does_not_move(monkeypatch):
    import crawlers.app_base as ab
    monkeypatch.setattr(ab.time, "sleep", lambda s: None)
    c = _crawler()
    d = _Dev(["com.android.launcher3/.Launcher"], start_moves=False)
    assert c._ensure_own_app(d) is False
    assert d.started == ["cn.suanya.zhixing"]


def test_no_package_is_a_noop(monkeypatch):
    import crawlers.app_base as ab
    monkeypatch.setattr(ab.time, "sleep", lambda s: None)
    c = _crawler(package="")
    d = _Dev(["com.Qunar/x"])
    assert c._ensure_own_app(d) is False
    assert d.started == []


def test_prepare_device_checks_foreground_before_anr():
    """前台校验必须在 ANR 探测之前：ANR 判据是按 activity 粗筛的，
    别人家的启动页会被误读成「自己卡住了」。"""
    c = _crawler()
    calls = []
    c.restore_login_snapshot = lambda dev: calls.append("restore")
    c._dismiss_system_prompts = lambda dev: calls.append("prompts")
    c._ensure_own_app = lambda dev: calls.append("own-app")
    c.recover_anr = lambda dev, wait_s=30: calls.append("anr")

    class D:
        def lock_portrait(self):
            calls.append("portrait")
            return True

    c.prepare_device(D())
    assert calls == ["portrait", "restore", "prompts", "own-app", "anr"], calls
