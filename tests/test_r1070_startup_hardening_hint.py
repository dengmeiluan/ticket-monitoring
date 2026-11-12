# -*- coding: utf-8 -*-
"""补测试：设备起来了但伪装没就位时，启动日志必须带修复命令。

这是"零配置"的最后一环：用户看到「实例已就绪」但采集一直失败，
是最难自查的状态。日志里必须直接给出 `python scripts/setup_device.py ...`。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.android import bootstrap as bs  # noqa: E402


class _Mgr:
    adb_path = "adb"

    def __init__(self, *a, **k):
        pass

    def adb_serial(self):
        # 真实 MuMuManager 里这是**方法**，写成属性会让 AdbDevice 构造抛
        # TypeError 并被吞成"设备句柄不可用"（假绿/假红的典型来源）。
        return "127.0.0.1:16384"

    def available(self):
        return True

    def info(self):
        return {"is_android_started": True, "adb_port": 16384,
                "adb_host_ip": "127.0.0.1"}


class _Dev:
    """假设备：App 都没装（让 status 走到"就绪但缺 App"分支）。"""

    def __init__(self, *a, **k):
        pass

    def app_installed(self, pkg):
        return False


def _patch(monkeypatch, hardening):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _Mgr)
    from core.android import device as _dev_mod
    monkeypatch.setattr(_dev_mod, "AdbDevice", _Dev)
    monkeypatch.setattr(bs, "probe_hardening", lambda dev: hardening)


def test_ready_with_missing_hardening_says_what_to_run(monkeypatch):
    _patch(monkeypatch, {"ok": False, "checks": [],
                         "missing": ["SELinux 视图=Permissive"],
                         "next": "设备伪装未就位：SELinux 视图=Permissive；"
                                 "执行 python scripts/setup_device.py --apply --reboot"})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "setup_device.py" in msg and "--apply" in msg, msg


def test_ready_with_good_hardening_stays_concise(monkeypatch):
    _patch(monkeypatch, {"ok": True, "checks": [("x", True, "y")],
                         "missing": [], "next": ""})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "就绪" in msg
    assert "setup_device.py" not in msg


def test_ready_with_unknown_hardening_does_not_cry_wolf(monkeypatch):
    """读不到伪装时不能吓人（ok=None 不算失败）。"""
    _patch(monkeypatch, {"ok": None, "checks": [], "missing": [],
                         "next": "读不到设备状态"})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "setup_device.py" not in msg, msg


def test_no_app_channel_returns_empty(monkeypatch):
    _patch(monkeypatch, {"ok": False, "checks": [], "missing": [],
                         "next": "x"})
    assert bs.ensure_android_runtime(["qunar"], {"android": {"enabled": True}}) == ""
