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
