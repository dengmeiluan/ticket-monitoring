# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r805bd_app_portrait.py
- tests/test_r944_app_portrait_persist.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys

from core.android import emulator_tuning as tune


# ---- merged from tests/test_r805bd_app_portrait.py ----

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


# ---- merged from tests/test_r944_app_portrait_persist.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class FakeDev:
    """只记录 shell 调用；`settings get` 回读本次 put 进去的值。"""

    def __init__(self):
        self.calls = []
        self.kv = {}

    def sh(self, *a, **_k):
        self.calls.append(tuple(a))
        if len(a) >= 5 and a[1] == "settings":
            if a[2] == "put":
                self.kv[(a[3], a[4])] = a[5]
            elif a[2] == "get":
                return self.kv.get((a[3], a[4]), "")
        if len(a) >= 3 and a[1] == "cat":
            return "boot-xyz"
        return ""

    _sh = sh


# ---------------------------------------------------------------------------
# 1. 调优层真的会写竖屏锁，并把它纳入验收
# ---------------------------------------------------------------------------
def test_tuning_puts_portrait_lock():
    dev = FakeDev()
    rep = tune.apply(dev, {"android": {"tuning": {"enabled": True}}}, force=True)
    puts = [c for c in dev.calls if len(c) >= 6 and c[1] == "settings"
            and c[2] == "put"]
    assert ("shell", "settings", "put", "system",
            "accelerometer_rotation", "0") in dev.calls, puts
    assert ("shell", "settings", "put", "system",
            "user_rotation", "0") in dev.calls, puts
    assert rep["ok"] is True


def test_portrait_lock_is_part_of_verification():
    """把竖屏锁写进 _EXPECT，`ok` 才是"竖屏已锁"的诚实结论。

    只写不验，等于重复 r915 那个「setprop 返回 0 但值不变」的老坑：
    报告全绿、设备还是横的。
    """
    assert tune._EXPECT.get("accelerometer_rotation") == "0"
    assert tune._EXPECT.get("user_rotation") == "0"
    keys = {k for _s, k, _v in tune._SETTINGS}
    assert "accelerometer_rotation" in keys and "user_rotation" in keys


def test_portrait_verify_fails_when_device_still_rotates():
    """设备没吃下设置时必须报 False，不能因为"命令发出去了"就报成功。"""

    class Stubborn(FakeDev):
        def sh(self, *a, **_k):
            self.calls.append(tuple(a))
            if len(a) >= 5 and a[1] == "settings" and a[2] == "get":
                if a[4] == "accelerometer_rotation":
                    return "1"          # 设备仍然开着自动旋转
            if len(a) >= 3 and a[1] == "cat":
                return "boot-xyz"
            return ""

        _sh = sh

    rep = tune.verify(Stubborn())
    assert rep["ok"] is False
    assert rep["values"]["accelerometer_rotation"] == "1"


# ---------------------------------------------------------------------------
# 2. 宿主机侧：window_auto_rotate 必须在官方可写白名单里
# ---------------------------------------------------------------------------
def test_vendor_allows_window_auto_rotate():
    from core.android import vendor
    assert "window_auto_rotate" in vendor._WRITABLE


def test_vendor_rejects_performance_keys():
    """白名单不能被顺手放宽：性能/网络类键写错会让采集变慢或断网。"""
    from core.android import vendor
    for bad in ("performance_cpu.custom", "max_frame_rate",
                "net_bridge.enabled", "prefetch.config"):
        assert bad not in vendor._WRITABLE


# ---------------------------------------------------------------------------
# 3. 设备侧强制竖屏清单：MuMu 原生按包名扳正
# ---------------------------------------------------------------------------
def test_force_orientation_lists_all_app_channels():
    """五个 App 渠道包名都要在 portrait 清单里。

    这是第二层：App 自己声明横屏（Flutter/游戏化首页常见）时，
    只靠 `accelerometer_rotation=0` 扳不回来，必须由 MuMu 原生层强制。
    """
    from core.android.stealth import KNOWN_APPS

    path = os.path.join(ROOT, "_scratch", "force-orientation-apps.json")
    if not os.path.isfile(path):
        pytest_skip = __import__("pytest").skip
        pytest_skip("设备侧清单样本未入库：%s" % path)
    import json
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    portrait = set(data.get("portrait") or [])
    missing = [p for p in KNOWN_APPS.values() if p not in portrait]
    assert not missing, "未进 portrait 清单: %s" % missing


# ---------------------------------------------------------------------------
# 4. 开查前重清厂商 props：nemuinit 会周期性写回，按 boot 一次不够
# ---------------------------------------------------------------------------
def test_prepare_device_refreshes_vendor_props_last():
    """统一前置的最后一刀必须是 props 重清（App 启动后才读 Build）。

    顺序钉死：竖屏 → 登录态 → 权限框 → ANR → props。
    竖屏必须最先（后面所有点击都靠竖屏坐标），props 必须最后
    （清完再启 App，否则又给了 nemuinit 一次写回窗口）。
    """
    from crawlers.app_base import AppCrawler

    calls = []
    c = AppCrawler.__new__(AppCrawler)
    c.restore_login_snapshot = lambda dev: calls.append("restore")
    c._dismiss_system_prompts = lambda dev: calls.append("prompts")
    c.recover_anr = lambda dev, wait_s=30: calls.append("anr")
    c._refresh_vendor_props = lambda dev: calls.append("props")

    class D:
        def lock_portrait(self):
            calls.append("portrait")
            return True

    c.prepare_device(D())
    assert calls == ["portrait", "restore", "prompts", "anr", "props"], calls


def test_refresh_vendor_props_is_fail_soft():
    """设备读不到 / 没 resetprop 时不许抛，也不许阻断采集。"""
    from crawlers.app_base import AppCrawler

    c = AppCrawler.__new__(AppCrawler)
    c.name = "app_ctrip"
    c.config = {}
    c.logger = _Quiet()

    class Dead:
        def sh(self, *a, **k):
            raise RuntimeError("device offline")

        _sh = sh

    c._refresh_vendor_props(Dead())      # 不抛就算过


def test_refresh_vendor_props_logs_when_it_deletes():
    from crawlers.app_base import AppCrawler

    seen = []
    c = AppCrawler.__new__(AppCrawler)
    c.name = "app_ctrip"
    c.config = {}
    c.logger = _Quiet(seen)
    c._stealth_refresh = lambda dev: {"deleted": ["nemud.x", "abcdefnemu"]}

    c._refresh_vendor_props(object())
    assert seen and "2" in seen[-1], seen


class _Quiet:
    def __init__(self, seen=None):
        self.seen = seen if seen is not None else []

    def info(self, fmt, *a):
        self.seen.append((fmt % a) if a else fmt)

    def warning(self, fmt, *a):
        self.seen.append((fmt % a) if a else fmt)
