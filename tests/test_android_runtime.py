# -*- coding: utf-8 -*-
"""AndroidRuntime：关闭时空转、启动超时、设备锁串行。"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import runtime as rt_mod
from core.android.runtime import AndroidRuntime


class FakeMuMu:
    def __init__(self, started=False, available=True, launch_ok=True,
                 boot_after=0):
        self.started = started
        self._available = available
        self.launch_ok = launch_ok
        self.boot_after = boot_after
        self.launch_calls = 0
        self.info_calls = 0

    def available(self):
        return self._available

    def info(self, vm=None):
        self.info_calls += 1
        if self.boot_after and self.info_calls >= self.boot_after:
            self.started = True
        return {"is_android_started": self.started, "adb_port": 16384}

    def launch(self, vm=None):
        self.launch_calls += 1
        if self.launch_ok:
            self.started = True
        return self.launch_ok

    def shutdown(self, vm=None):
        self.started = False
        return True

    def adb_serial(self, vm=None):
        return "127.0.0.1:16384"


class FakeDevice:
    def __init__(self, online=True, recoverable=False):
        self._online = online
        self.connect_calls = 0
        self.reconnect_calls = 0
        # recoverable=True 模拟"只是 adb 端点坏了，逐级重连能救回来"
        # （2026-11-04 实测：`adb kill-server` 之后 TCP 端点 offline，
        #  而同一实例的 emulator-5554 还是 device 态——重连 9 秒就好，
        #  根本不需要重启整个实例）。
        self._recoverable = recoverable

    def connect(self):
        self.connect_calls += 1
        return self._online

    def online(self):
        return self._online

    def state(self):
        return "device" if self._online else "offline"

    def reconnect(self, logger=None, settle_s=0.0):
        """与 `AdbDevice.reconnect` 同契约：返回最终状态字符串。"""
        self.reconnect_calls += 1
        if self._online:
            return "device"
        if self._recoverable:
            self._online = True
            return "recovered:server"
        return "offline"

    def prop(self, key):
        return "arm64-v8a"

    def app_installed(self, pkg):
        return True


def _make(cfg=None, mumu=None, device=None):
    rt = AndroidRuntime(cfg or {"enabled": True}, logger=None)
    rt._mumu = mumu or FakeMuMu(started=True)
    rt._device = device or FakeDevice(online=True)
    rt._poll_interval = 0.01
    return rt


def test_disabled_touches_nothing(monkeypatch):
    """关闭时必须零外部调用。"""
    rt = AndroidRuntime({"enabled": False}, logger=None)
    ok, why = rt.ensure_ready()
    assert (ok, why) == (False, "disabled")
    assert rt._mumu is None
    assert rt._device is None


def test_not_installed_reported():
    rt = _make(mumu=FakeMuMu(available=False))
    ok, why = rt.ensure_ready()
    assert (ok, why) == (False, "not_installed")
    assert rt.status()["state"] == "not_installed"


def test_ready_when_started_and_online():
    rt = _make()
    ok, why = rt.ensure_ready()
    assert (ok, why) == (True, "ready")
    assert rt.status()["state"] == "ready"
    assert rt.status()["adb_ok"] is True


def test_launches_when_stopped():
    mumu = FakeMuMu(started=False, boot_after=2)
    rt = _make(mumu=mumu)
    ok, why = rt.ensure_ready()
    assert ok is True
    assert mumu.launch_calls == 1


def test_boot_timeout_reported():
    mumu = FakeMuMu(started=False, launch_ok=False)
    rt = _make(mumu=mumu, cfg={"enabled": True, "boot_timeout_s": 10})
    ok, why = rt.ensure_ready()
    assert ok is False
    assert why in ("timeout", "not_started")
    assert rt.status()["state"] in ("starting", "stopped")


def test_endpoint_recoverable_is_not_treated_as_dead():
    """**端点坏 ≠ 设备坏**（2026-11-04 误诊两次之后钉住的契约）。

    真实场景：db kill-server 或 db root 重启 adbd 之后，
    TCP 端点显示 offline，而同一实例的 emulator-5554 还是 device 态。
    当时我判定"设备离线"→ 去 MuMuManager control restart，
    白丢一轮采集 + 全部内存态；实际 kill-server+connect 9 秒就好。

    所以：能靠逐级重连救回来的，**必须**返回 ready，不许报 adb 失败。
    """
    rt = _make(device=FakeDevice(online=False, recoverable=True))
    ok, why = rt.ensure_ready()
    assert ok is True, (ok, why, rt.last_error)
    assert rt.status()["state"] == "ready", rt.status()


def test_adb_offline_reported():
    rt = _make(device=FakeDevice(online=False))
    ok, why = rt.ensure_ready()
    assert ok is False
    assert why == "adb"


def test_device_lock_is_serial():
    rt = _make()
    order = []
    entered = threading.Event()

    def slow():
        with rt.device_lock():
            entered.set()
            order.append("a-in")
            time.sleep(0.15)
            order.append("a-out")

    t = threading.Thread(target=slow)
    t.start()
    entered.wait(1)
    with rt.device_lock():
        order.append("b-in")
    t.join(2)
    # b 必须在 a 之后进入：a-out 先于 b-in
    assert order.index("a-out") < order.index("b-in"), order
