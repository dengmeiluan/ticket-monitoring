# -*- coding: utf-8 -*-
"""r689：登录页是启动首屏，不等于会话失效。

真机现场（2026-10-30，去哪儿）：App 被 force-stop 后重新启动，前台落在
`UCLoginByPhoneActivity`。此时：

  * 直接按 login 放弃 → 账本记「需要手机号登录」；
  * 但发一次 `qunarphone://flight` 就进到机票首页，**而且是登录态**
    （首页正常、下单不跳登录）。

于是每次 force-stop 后都会误报一轮「登录失效」，用户看到的是「明明
刚登录，怎么又要登」。判据应该是「深链能不能进首页」，不是「第一屏
长什么样」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import AppQunarCrawler

LOGIN = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
         '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
HOME = ('<hierarchy><node text="atom_flight_search_panel" bounds="[0,0][900,100]" />'
        + "".join('<node text="x%d" bounds="[0,%d][100,%d]" />' % (i, 200 + i * 10, 208 + i * 10)
                  for i in range(8))
        + '</hierarchy>')


class Dev:
    """第一屏登录页；深链后变首页。"""

    def __init__(self, reachable=True):
        self.reachable = reachable
        self.on_home = False
        self.calls = []

    def dump(self):
        self.calls.append(("dump",))
        return HOME if self.on_home else LOGIN

    def deep_link(self, uri):
        self.calls.append(("deep", uri))
        if self.reachable:
            self.on_home = True
        return self.reachable

    def keyevent(self, key):
        self.calls.append(("key", key))
        return True

    def current_activity(self):
        return "com.Qunar/.home.HomeActivity" if self.on_home else "com.Qunar/.uc.UCLoginByPhoneActivity"

    def app_stop(self, pkg):
        return True

    def app_start(self, pkg):
        return True


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.home_uri = "qunarphone://flight"
    c._snapshot_restored = True
    import logging
    c.logger = logging.getLogger("t")
    return c


def test_uses_deep_link_when_first_screen_is_login(monkeypatch):
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _crawler()
    dev = Dev(reachable=True)
    xml = c._ensure_home(dev)
    assert "atom_flight_search_panel" in xml, \
        "首屏是登录页就直接放弃了，明明深链能进首页"
    assert ("deep", "qunarphone://flight") in dev.calls


def test_still_reports_login_when_deep_link_also_blocked(monkeypatch):
    """深链也进不去 → 返回登录页那帧，由调用方按 login 入账。"""
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _crawler()
    xml = c._ensure_home(Dev(reachable=False))
    assert "请输入手机号" in xml, "深链失败时应把登录页原样交回"


def test_base_restore_treats_login_first_screen_as_logged_in(monkeypatch):
    """基类的「设备已登录就跳过恢复」不能把登录首屏当未登录。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    c._snapshot_restored = False
    c.user_data_root = os.path.abspath("user_data")
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
    ok = c.restore_login_snapshot(Dev(reachable=True))
    assert ok is False
    assert "restore" not in calls, "登录首屏被当成未登录，又用旧快照覆盖了设备"
