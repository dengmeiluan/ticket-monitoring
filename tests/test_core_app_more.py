# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1374_app_device_state.py
- tests/test_r729_app_login_switch_plat.py
- tests/test_r805ab_app_input_honesty.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import sys

from core.android import login_api, login_api as api
from core.android.login_session import AppLoginRegistry, AppLoginSession, ST_PENDING


# ---- merged from tests/test_r1374_app_device_state.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Reg:
    def get(self, plat):
        return None          # 没有进行中的登录会话


def test_state_reports_device_evidence():
    out, code = api.handle_state(
        _Reg(), "app_fliggy",
        snapshot_info=lambda p: {"exists": False},
        needs_login=lambda p: False,
        device_state=lambda p: {"state": "logged_in", "at": "2026-11-10 21:41:53",
                                "why": "最近一轮出过数"})
    assert code == 200, out
    assert out["device_state"] == "logged_in", out
    assert out["device_at"] == "2026-11-10 21:41:53", out
    assert out["device_why"], out
    # 快照仍然没有 —— 两件事分开表达，不许互相冒充
    assert out["snapshot_saved"] is False, out
    assert out["evidence"] == "无", out


def test_state_reports_login_wall():
    out, _ = api.handle_state(
        _Reg(), "app_ctrip", None, None,
        device_state=lambda p: {"state": "login_wall", "at": "2026-11-10 22:57",
                                "why": "命中登录墙"})
    assert out["device_state"] == "login_wall", out


def test_broken_evidence_degrades_to_empty():
    """负控：证据回调抛异常时，接口必须照常返回（只是没有证据）。"""
    def _boom(plat):
        raise RuntimeError("db locked")

    out, code = api.handle_state(_Reg(), "app_qunar", None, None, device_state=_boom)
    assert code == 200, out
    assert out["device_state"] == "", out
    assert out["device_at"] == "", out


def test_frontend_maps_device_state_to_status():
    """前端必须把账本结论合成为 status，否则各卡片消费者读不到。"""
    src = webui_full_src()
    assert 'device_state:String((j&&j.device_state)||\'\')' in src, "前端没读 device_state"
    assert "'login_wall'?'login_required'" in src, "登录墙没映射成需登录"
    assert "'logged_in'?'live_unsaved'" in src, "已登录没映射成「设备已登录·未存快照」"
    assert "live_unsaved:'设备已登录 · 未存快照'" in src, "缺 live_unsaved 词面"
    # 卡片消费者统一走 slotStatusCn → 必须能翻译这个新状态
    assert "function slotStatusCn(st){return SLOT_STATUS_CN[st]" in src


# ---- merged from tests/test_r729_app_login_switch_plat.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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


# ---- merged from tests/test_r805ab_app_input_honesty.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_input_text_verifies_ui_not_just_command():
    body = _src("core/android/device.py")
    i = body.index("    def input_text(")
    j = body.index("\n    def ", i + 10)
    seg = body[i:j]
    assert "self.dump()" in seg, (
        "input_text 没有回读视图树：无焦点时 adb 照样回成功，"
        "函数会谎报「已输入」")
    assert "return want in page" in seg or "want in page" in seg, (
        "input_text 读了 dump 却没拿它做判定，等于没校验")


def test_input_text_returns_false_when_text_absent(monkeypatch=None):
    """行为层：文本没进界面时必须返回 False（用替身，不连设备）。"""
    from core.android.device import AdbDevice

    dev = AdbDevice.__new__(AdbDevice)          # 不跑 __init__（无设备）

    class _D:
        n = 0

        def __call__(self):
            _D.n += 1
            return '<node text="出发城市"/>'     # 页面里没有 zzQ9

    dev.dump = _D()
    dev._sh = lambda *a, **k: ""                # 「命令成功」
    got = dev.input_text("zzQ9")
    assert got is False, (
        "文本没出现在视图树里却返回 %r：用户会看到「已输入」而画面没变" % got)

    class _D2:
        def __call__(self):
            return '<node text="zzQ9"/>'

    dev.dump = _D2()
    got2 = dev.input_text("zzQ9")
    assert got2 is True, "文本确实进了界面却返回 %r（校验过头）" % got2


def test_frontend_input_failure_tells_next_step():
    src = webui_full_src()
    i = src.index("function appLoginText(")
    seg = src[i:src.index("\nfunction ", i)]
    assert "没输进去" in seg or "点一下输入框" in seg, (
        "输入失败只回「输入失败」，用户不知道下一步该做什么")
