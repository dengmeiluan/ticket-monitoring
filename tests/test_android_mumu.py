# -*- coding: utf-8 -*-
"""MuMuManager 封装：命令拼装正确、失败不抛异常。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.mumu import MuMuManager

FAKE_DIR = r"D:\fake\MuMu"
MANAGER = os.path.join(FAKE_DIR, "nx_main", "MuMuManager.exe")
ADB = os.path.join(FAKE_DIR, "nx_main", "adb.exe")


def _mgr(**kw):
    m = MuMuManager(install_dir=FAKE_DIR)
    m.manager_path = MANAGER
    m.adb_path = ADB
    m._exists = kw.get("exists", True)
    return m


def test_available_false_when_manager_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(
                            AssertionError("must not spawn")))
    m = _mgr(exists=False)
    assert m.available() is False
    assert calls == []


def test_info_parses_json(monkeypatch):
    payload = {"is_android_started": True, "adb_port": 16384}

    class R:
        returncode = 0
        stdout = json.dumps(payload).encode()
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    info = _mgr().info(0)
    assert info["is_android_started"] is True
    assert info["adb_port"] == 16384


def test_info_returns_none_on_garbage(monkeypatch):
    class R:
        returncode = 0
        stdout = b"not json at all"
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert _mgr().info(0) is None


def test_launch_timeout_returns_false(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="MuMuManager", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    assert _mgr().launch(0) is False


def test_launch_builds_expected_args(monkeypatch):
    seen = {}

    class R:
        returncode = 0
        stdout = b'{"errcode": 0}'
        stderr = b""

    def fake(cmd, **k):
        seen["cmd"] = cmd
        return R()

    monkeypatch.setattr(subprocess, "run", fake)
    assert _mgr().launch(3) is True
    assert "control" in seen["cmd"]
    assert "-v" in seen["cmd"] and "3" in seen["cmd"]
    assert "launch" in seen["cmd"]


def test_engine_state_returns_dict(monkeypatch):
    class R:
        returncode = 0
        stdout = json.dumps({"return": {"15": {"installed": True}}}).encode()
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    st = _mgr().engine_state()
    assert st["15"]["installed"] is True
