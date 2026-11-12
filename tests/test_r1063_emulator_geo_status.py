# -*- coding: utf-8 -*-
"""r1063 T64：模拟器自启/自重启 + 定位状态如实报告。

用户要求原话：「继续做到极致，模拟器重启你自己重启啊」。所以这两件事必须**程序能做**，
而且状态要说实话——`last location=null` 是"还没有应用请求过定位"，不是"没设上"。
"""
import io
import os

import pytest

from core.android import emulator as em
from core.android import geo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeMgr:
    def __init__(self, *, running=True, available=True, launch_ok=True):
        self.running = running
        self._available = available
        self.launch_ok = launch_ok
        self.calls = []
        self.adb_path = "adb-fake"
        self.manager_path = "fake.exe"

    def available(self):
        return self._available

    def info(self, vm=None):
        return {"is_android_started": self.running,
                "is_process_started": self.running,
                "player_state": "start_finished" if self.running else "closed",
                "adb_host_ip": "127.0.0.1", "adb_port": 16384,
                "android_version": "15.0", "pid": 1}

    def adb_serial(self, vm=None):
        return "127.0.0.1:16384"

    def launch(self, vm=None):
        self.calls.append("launch")
        self.running = self.launch_ok
        return self.launch_ok

    def shutdown(self, vm=None):
        self.calls.append("shutdown")
        return True

    def restart(self, vm=None):
        self.calls.append("restart")
        return True


@pytest.fixture()
def fake(monkeypatch):
    mgr = _FakeMgr(running=True)
    monkeypatch.setattr(em, "_mgr", lambda cfg=None, **kw: mgr)
    monkeypatch.setattr(em, "_adb_visible", lambda *a, **kw: True)
    return mgr


def test_status_reads_the_real_fields(fake):
    st = em.status({"android": {}})
    assert st["available"] and st["running"] and st["state"] == "start_finished"
    assert st["adb"] == "127.0.0.1:16384" and st["adb_path"] == "adb-fake"


def test_ensure_running_is_a_noop_when_already_up(fake):
    rep = em.ensure_running({"android": {}}, wait_s=1)
    assert rep["ok"] and rep["launched"] is False
    assert "launch" not in fake.calls, "已经在跑就不许再发启动指令"


def test_ensure_running_launches_when_down(monkeypatch, fake):
    fake.running = False
    rep = em.ensure_running({"android": {}}, wait_s=5, poll_s=0.01)
    assert rep["ok"] and rep["launched"] is True, rep
    assert "launch" in fake.calls


def test_restart_calls_restart_and_waits(fake):
    rep = em.restart({"android": {}}, wait_s=5)
    assert rep["ok"] and rep.get("restarted") is True
    assert "restart" in fake.calls


def test_unavailable_manager_is_reported_not_swallowed(monkeypatch):
    mgr = _FakeMgr(available=False)
    monkeypatch.setattr(em, "_mgr", lambda cfg=None, **kw: mgr)
    st = em.status({"android": {}})
    assert st["available"] is False
    assert "MuMuManager" in str(st.get("why") or "")
    rep = em.ensure_running({"android": {}}, wait_s=1)
    assert rep["ok"] is False and rep["why"]


def test_setup_check_actions_are_safe_listed():
    from core import setup_check as sc
    for act in ("launch_emulator", "restart_emulator"):
        assert act in sc.SAFE_ACTIONS, act


class _GeoDev:
    def __init__(self, mode="3", prov="+gps,+network", last="last location=null"):
        self.mode, self.prov, self.last = mode, prov, last
        self.calls = []

    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        if "location_mode" in cmd:
            return self.mode
        if "providers_allowed" in cmd:
            return self.prov
        if "dumpsys location" in cmd:
            return self.last
        return "OK"


def test_geo_status_distinguishes_never_requested_from_not_set():
    st = geo.status(_GeoDev(), {"android": {"geo": {"enabled": True}}})
    assert st["mode"] == "3" and "gps" in st["providers"]
    assert st["verdict"] == "未请求过（正常）"
    assert st["ok"] is True, "没有应用请求过定位 == 正常，不是失败"


def test_geo_status_flags_a_really_off_provider():
    st = geo.status(_GeoDev(mode="0", prov=""), {"android": {}})
    assert st["verdict"] == "无法确认"
    assert st["ok"] is False


def test_geo_status_sees_a_real_fix():
    st = geo.status(_GeoDev(last="last location=Location[gps 31.187400,121.492100]"),
                    {"android": {}})
    assert st["verdict"] == "已设置" and st["ok"] is True
