# -*- coding: utf-8 -*-
"""r688：设备上登录着，就绝不能用旧快照覆盖它。

真机现场（2026-10-30，去哪儿）：刚登录完导出快照 → 立刻恢复 → **App 回到
登录墙**；不恢复、直接重启 → 登录态正常。快照是某一时刻的副本，去哪儿的
会话凭据还带服务端刷新，用旧副本盖掉设备上更新的会话，等于每次采集都把
用户踢下线。

原来的 `restore_login_snapshot` 无条件恢复，于是「登录一次永久复用」在
去哪儿上变成了「每轮采集都要重登」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import AppQunarCrawler

import itertools

import pytest


@pytest.fixture(autouse=True)
def _fast_clock(monkeypatch):
    """恢复前置探测是「等到 deadline」的循环：sleep 被置空后若 time 不前进，
    整条用例会空转满 30 秒（实测一条 12s 还在转）。这里让时间每次调用 +10s。"""
    import crawlers.app_base as base
    tick = itertools.count(1)
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    monkeypatch.setattr(base.time, "time", lambda: float(next(tick)) * 10.0)

HOME = ('<hierarchy>' + "".join(
    '<node text="x%d" bounds="[0,%d][100,%d]" />' % (i, i * 10, i * 10 + 8)
    for i in range(10)) + '</hierarchy>')
LOGIN = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
         '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
BLANK = '<hierarchy><node text="x" bounds="[0,0][10,10]" /></hierarchy>'


class Dev:
    def __init__(self, screen=HOME):
        self.screen = screen
        self.calls = []

    def app_stop(self, pkg):
        self.calls.append(("stop", pkg))
        return True

    def app_start(self, pkg):
        self.calls.append(("start", pkg))
        return True

    def deep_link(self, uri):
        self.calls.append(("deep", uri))
        return True

    def dump(self):
        self.calls.append(("dump",))
        return self.screen

    def root(self):
        self.calls.append(("root",))
        return True

    def current_activity(self):
        return "com.Qunar/.X"


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.home_uri = "qunarphone://flight"
    c._snapshot_restored = False
    import logging
    c.logger = logging.getLogger("t")
    c.user_data_root = os.path.abspath("user_data")
    return c


def test_skips_restore_when_device_already_logged_in(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                calls.append("exists")
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    ok = c.restore_login_snapshot(Dev(HOME))
    assert ok is False
    assert "restore" not in calls, "设备已登录仍覆盖了快照：%s" % calls


def test_restores_when_device_shows_login_wall(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    ok = c.restore_login_snapshot(Dev(LOGIN))
    assert ok is True
    assert calls == ["restore"], calls


def test_restores_when_page_is_blank(monkeypatch):
    """白屏不算「已登录」——否则整轮会跑在空页面上。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    c.restore_login_snapshot(Dev(BLANK))
    assert calls == ["restore"], "白屏被当成已登录：%s" % calls

def test_restore_failure_cold_starts_so_round_can_continue(monkeypatch):
    """快照恢复因「拿不到 root」失败时，冷启一次，别把 App 留在半死状态。

    现场（2026-11-01 19:20）：`snap-restore error 无法获取 root` 紧接着
    `app-dump timeout 没能打开机票首页`——恢复失败后没有任何兜底。
    """
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    # 时间必须往前走：恢复前置探测是「等到 deadline」的循环，冻结就出不来
    import itertools
    _tick = itertools.count(1)
    monkeypatch.setattr(base.time, "time", lambda: float(next(_tick)) * 10)
    c = _crawler()

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            return False, "无法获取 root"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    called = []
    monkeypatch.setattr(c, "_cold_start_and_probe",
                        lambda dev, wait_s=30: called.append("cold") or HOME)
    dev = Dev(BLANK)
    assert c.restore_login_snapshot(dev) is False
    assert called == ["cold"], "恢复失败后没有冷启兜底"


def test_cold_start_and_probe_returns_first_usable_page(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    dev = Dev(HOME)
    assert c._cold_start_and_probe(dev) == HOME
    assert ("stop", "com.Qunar") in dev.calls
    assert any(k[0] == "deep" for k in dev.calls), "冷启应走深链回机票页"

def test_ensure_app_fresh_cold_starts_once_per_round(monkeypatch):
    """每条航线开始前冷启一次；快照恢复已冷启过则不重复。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []
    monkeypatch.setattr(c, "_cold_start_and_probe",
                        lambda dev, wait_s=30: calls.append("cold") or HOME)
    c._app_fresh = False
    assert c._ensure_app_fresh(Dev(HOME)) is True
    assert calls == ["cold"], calls
    # 恢复阶段刚冷启过 → 本轮不再启
    c._app_fresh = True
    assert c._ensure_app_fresh(Dev(HOME)) is True
    assert calls == ["cold"], "恢复已冷启过，采集前又启了一次"
