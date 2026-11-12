# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r805ci_app_foreground.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys


# ---- merged from tests/test_r805ci_app_foreground.py ----

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
