# -*- coding: utf-8 -*-
"""r1063 T87：`/api/channel/reset-app`——清 App 数据成为可执行干预。

为什么是接口而不是新按钮：节流行的高度被 r420/r640/r993 几何门禁盯着，
再加一行按钮会把工具条撑高（实测历史里为此红过多次）。接口先落地，
按钮等有把握不影响 96px 时再排。

三道安全闸（顺序即优先级）：
1. 渠道存在性；
2. **只有 App 渠道**才有"App 数据"可清（浏览器渠道该走重登/清会话）；
3. 必须 `confirm: true`——这是破坏性操作，会清掉该 App 的登录态。

清完之后要**同时清掉登录墙记忆**，否则窗口期内我们不会再去试，
用户登好了也读不到数（这就是"清了没效果"的经典假象）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()

START = 'elif self.path == "/api/channel/reset-app":'


def _seg():
    i = SRC.index(START)
    j = SRC.index('elif self.path == "/api/push":', i)
    return SRC[i:j]


def test_route_exists_and_before_push():
    assert START in SRC
    assert SRC.index(START) < SRC.index('elif self.path == "/api/push":')


def test_three_guards_in_order():
    seg = _seg()
    i_unknown = seg.index('"未知渠道"')
    i_apponly = seg.index("_APP_CHANNELS")
    i_confirm = seg.index('need_confirm')
    assert i_unknown < i_apponly < i_confirm, "闸门顺序必须由粗到细"


def test_confirm_is_required_and_explained():
    seg = _seg()
    assert 'body.get("confirm")' in seg
    assert "破坏性操作" in seg and "登录态" in seg


def test_clears_login_wall_memo_after_success():
    """清完数据必须清登录墙记忆，否则窗口内不会重试，看起来像"清了没用"。

    r1063 T131 起统一走 `_clear_login_wall_memo()`（连 `app_gone` 熔断一起清），
    所以这里断言"调用该函数"而不是断言内联的 service_state 调用——
    实现细节变了，但**契约没变**（成功清数据后必须清墙）。
    """
    seg = _seg()
    assert "_clear_login_wall_memo" in seg, \
        "清完 App 数据后必须清登录墙记忆（T131 起统一走该函数）"


def test_only_app_channels_allowed():
    seg = _seg()
    assert 'plat not in _APP_CHANNELS' in seg
    assert "只有 App 渠道" in seg


def test_uses_pm_clear_with_package_from_registry():
    seg = _seg()
    assert '"pm", "clear"' in seg or '"pm",' in seg
    assert 'getattr(_REG.get(plat), "package"' in seg
