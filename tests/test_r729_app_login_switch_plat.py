# -*- coding: utf-8 -*-
"""r729 内嵌登录切换 App 渠道时，画面仍是上一个 App 的画面。

用户报：「内嵌画面切换 app 的时候没有正确切换」——截图里弹窗标题写
「智行 App 登录」，画面却是去哪儿 App 的航班列表。

根因（`core/android/login_api.py: handle_create`）：
  * 同一台设备是**串行资源**，只能有一个 App 在前台；
  * 但 `AppLoginRegistry` 按 plat 各存一份，多个 plat 的会话可同时 alive；
  * 切到另一个 plat 时，`existing = registry.get(plat)` 查的是**新 plat**
    （没有会话）→ 继续走 `dev.app_start(pkg)`，看起来没问题；
  * 真正出问题的是**反向顺序**：若新 plat 之前已经有过一次会话且仍 alive，
    `existing.alive()` 为真 → 直接 `return {"ok": True, "already": True}`
    **不执行 app_start**；而屏幕上停留的是**另一个 App**，
    于是新会话持续采集到旧 App 的画面。

判据：切 plat 后必须确保「目标包名真的在前台」，否则要么拉起它，
要么把其它 plat 的会话作废——绝不能沿用「已有会话」直接复用画面。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import login_api  # noqa: E402
from core.android.login_session import (  # noqa: E402
    AppLoginRegistry, AppLoginSession, ST_PENDING,
)


class FakeDev:
    def __init__(self):
        self.started = []
        self.foreground = ""

    def app_start(self, pkg):
        self.started.append(pkg)
        self.foreground = pkg
        return True

    def current_activity(self):
        return ("cn.suanya.zhixing/com.app.main.entrance.MainActivity"
                if "zhixing" in self.foreground else
                "com.Qunar/com.mqunar.react.base.stack.container"
                ".QReactNativeActivity1")


class FakeRuntime:
    def __init__(self, dev):
        self._dev = dev

    def ensure_ready(self):
        return True, "已就绪"

    def device(self):
        return self._dev


PACKAGES = {"app_zhixing": "cn.suanya.zhixing",
            "app_qunar": "com.Qunar"}


def _create(registry, plat, rt):
    return login_api.handle_create(registry, plat, PACKAGES, lambda: rt)


def test_switching_plat_restarts_the_target_app():
    """A 会话在，切到 B：必须把 B 拉到前台，不能直接复用 A 的画面。"""
    dev = FakeDev()
    rt = FakeRuntime(dev)
    reg = AppLoginRegistry()

    out_a, code = _create(reg, "app_zhixing", rt)
    assert code == 200 and out_a.get("ok"), out_a
    assert dev.foreground == "cn.suanya.zhixing"

    out_b, code = _create(reg, "app_qunar", rt)
    assert code == 200 and out_b.get("ok"), out_b
    # 关键断言：B 必须真的被拉起
    assert "com.Qunar" in dev.started, (
        "切到去哪儿时没有 app_start，画面会继续是上一个 App")
    assert out_b.get("already") is not True, (
        "把「另一个 plat 的会话在」当成了「本 plat 已在登录」，直接复用画面")


def test_switching_back_reuses_only_after_reasserting_foreground():
    """A→B→A：回到 A 时也要确认 A 在前台（不能只信「A 有会话」）。"""
    dev = FakeDev()
    rt = FakeRuntime(dev)
    reg = AppLoginRegistry()
    _create(reg, "app_zhixing", rt)
    _create(reg, "app_qunar", rt)
    started_before = len(dev.started)
    out_a2, code = _create(reg, "app_zhixing", rt)
    assert code == 200 and out_a2.get("ok"), out_a2
    assert dev.foreground == "cn.suanya.zhixing", (
        "回到智行后前台的还是上一个 App")


def test_same_plat_twice_is_still_idempotent():
    """负控：同一渠道重复打开不应反复重启（幂等仍要成立）。"""
    dev = FakeDev()
    rt = FakeRuntime(dev)
    reg = AppLoginRegistry()
    _create(reg, "app_zhixing", rt)
    n = len(dev.started)
    out2, code = _create(reg, "app_zhixing", rt)
    assert code == 200 and out2.get("ok"), out2
    assert len(dev.started) == n, "同一渠道重复打开又重启了一次 App"


def test_frame_from_stale_session_is_not_served_as_target():
    """会话已被顶掉后，旧 plat 的帧接口不能再返回画面。

    否则前端轮询拿到的仍是旧 App 的截图，「切了没切」看不出来。
    """
    dev = FakeDev()
    rt = FakeRuntime(dev)
    reg = AppLoginRegistry()
    _create(reg, "app_zhixing", rt)
    _create(reg, "app_qunar", rt)
    sess_a = reg.get("app_zhixing")
    assert sess_a is None or not sess_a.alive(), (
        "被顶掉的会话还 alive：切走后仍会继续拍到旧 App 的画面")
