# -*- coding: utf-8 -*-
"""首启弹窗自愈：系统权限框之后还有**启动页协议**，两者都要能点掉。

2026-11-06 实测（`pm clear ctrip.android.view` 之后）：

    #1 .permission.ui.GrantPermissionsActivity  「要允许…发送通知吗？」
    #2 ctrip.business.splash.CtripSplashActivity 「同意并继续」（用户协议）
    #3 ...home...HomeActivity

原实现只在 activity 含 `permission` 时介入 → 卡在第 2 步，账本记
「40s 内未到机票表单页」，看着像渠道坏了，其实只差点一下「同意并继续」。
"""
import logging

from crawlers.app_fliggy import AppFliggyCrawler


class FakeDev:
    """按脚本依次返回 activity 与页面。"""

    def __init__(self, script):
        self._script = list(script)
        self.taps = []

    def current_activity(self):
        return self._script[0][0]

    def dump(self):
        act, xml = self._script[0]
        self._next = True
        return xml

    def tap(self, x, y):
        self.taps.append((x, y))
        if len(self._script) > 1:
            self._script.pop(0)
        return True


def _node(text, x=600, y=1400):
    return ('<node text="%s" bounds="[%d,%d][%d,%d]"/>'
            % (text, x - 30, y - 20, x + 30, y + 20))


def _crawler():
    return AppFliggyCrawler({"user_data_dir": "user_data", "android": {}},
                            logging.getLogger("t"))


def test_splash_agreement_is_clicked():
    """启动页的「同意并继续」必须被点掉（原实现只认 permission）。"""
    script = [
        ("com.ctrip/splash.CtripSplashActivity",
         "<hierarchy>" + _node("同意并继续") + "</hierarchy>"),
        ("com.ctrip/home.HomeActivity", "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    n = c._dismiss_system_prompts(d)
    assert n >= 1, "启动页协议没被点"
    assert d.taps, "没有发生点击"


def test_permission_dialog_still_handled():
    script = [
        ("com.android.permissioncontroller/.GrantPermissionsActivity",
         "<hierarchy>" + _node("允许") + "</hierarchy>"),
        ("com.ctrip/home.HomeActivity", "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) >= 1


def test_normal_page_is_not_touched():
    """普通页面（非 permission/splash）一律不读不点，避免吃掉广告页序列。"""
    script = [("com.ctrip/home.HomeActivity",
               "<hierarchy>" + _node("同意") + "</hierarchy>")]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) == 0
    assert d.taps == []


def test_loading_activity_agreement_is_clicked():
    """同程首启页是 `.LoadingActivity`（文案「温馨提示 / 同意并继续」）。

    只认 `splash` 会漏掉它 —— 2026-11-06 实测：清数据后渠道卡在首启页，
    账本记「20s 内未到同程机票表单」。修好后同一条路能出 5 条明细。
    """
    script = [
        ("com.tongcheng.android/.LoadingActivity",
         "<hierarchy>" + _node("温馨提示", 600, 900)
         + _node("同意并继续", 600, 1400)
         + _node("不同意且进入游客模式", 600, 1550) + "</hierarchy>"),
        ("com.tongcheng.android/.TongchengMainActivity",
         "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) >= 1, "LoadingActivity 的协议没被点"


def test_unknown_activity_is_untouched():
    """未列入首启名单的 activity 不介入（避免误点业务页上的「同意」）。"""
    script = [("com.foo/.SettingsActivity",
               "<hierarchy>" + _node("同意") + "</hierarchy>")]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) == 0
    assert d.taps == []
