# -*- coding: utf-8 -*-
"""AdbDevice：命令正确、失败兜底、越界不调外部进程。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.device import AdbDevice

ADB = r"D:\fake\adb.exe"
SERIAL = "127.0.0.1:16384"


def _dev():
    return AdbDevice(ADB, SERIAL, timeout=10)


class R:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def test_dump_returns_xml(monkeypatch):
    xml = b'<?xml version="1.0"?><hierarchy rotation="0"></hierarchy>'
    calls = []

    def fake(cmd, **k):
        calls.append(cmd)
        if "cat" in cmd:
            return R(out=xml)
        return R(out=b"UI hierchary dumped to: /sdcard/ui.xml")

    monkeypatch.setattr(subprocess, "run", fake)
    out = _dev().dump()
    assert "<hierarchy" in out
    assert any("cat" in c for c in calls)


def test_dump_returns_empty_when_offline(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(err=b"adb: device offline", rc=1))
    assert _dev().dump() == ""


def test_screencap_returns_png_bytes(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=b"\x89PNG\r\n\x1a\n" + b"0" * 32))
    data = _dev().screencap()
    assert data.startswith(b"\x89PNG")


def test_screencap_empty_on_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=b"", err=b"error", rc=1))
    assert _dev().screencap() == b""


def test_tap_rejects_negative_coordinates(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: calls.append(a) or R())
    assert _dev().tap(-1, 10) is False
    assert calls == []


def test_tap_builds_input_command(monkeypatch):
    seen = {}

    class Ok:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake(cmd, **k):
        seen["cmd"] = cmd
        return Ok()

    monkeypatch.setattr(subprocess, "run", fake)
    assert _dev().tap(100, 200) is True
    assert "input" in seen["cmd"]
    assert "tap" in seen["cmd"]
    assert "100" in seen["cmd"] and "200" in seen["cmd"]


def test_online_true_when_devices_lists_serial(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: R(out=f"List of devices attached\n{SERIAL}\tdevice\n".encode()))
    assert _dev().online() is True


def test_online_false_when_absent(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=b"List of devices attached\n"))
    assert _dev().online() is False


def test_prop_returns_stripped_value(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=b"arm64-v8a\n"))
    assert _dev().prop("ro.product.cpu.abi") == "arm64-v8a"


def test_app_start_uses_monkey(monkeypatch):
    seen = {}

    class Ok:
        returncode = 0
        stdout = b"Events injected: 1"
        stderr = b""

    def fake(cmd, **k):
        seen["cmd"] = cmd
        return Ok()

    monkeypatch.setattr(subprocess, "run", fake)
    assert _dev().app_start("cn.suanya.zhixing") is True
    assert "monkey" in seen["cmd"]


# ---- r630：dump 必须拿「这一屏」，不能拿旧文件冒充 ----
def test_dump_writes_to_shell_writable_path(monkeypatch):
    """/sdcard 是 media_rw 挂载，shell 删不掉旧文件；必须写 /data/local/tmp。"""
    seen = []
    xml = b'<?xml version="1.0"?><hierarchy rotation="0"></hierarchy>'

    def fake(cmd, **k):
        seen.append(list(cmd))
        if "cat" in cmd:
            return R(out=xml)
        return R(out=b"UI hierchary dumped to: /data/local/tmp/tm_ui.xml")

    monkeypatch.setattr(subprocess, "run", fake)
    assert "<hierarchy" in _dev().dump()
    dumped = [c for c in seen if "uiautomator" in c]
    assert dumped, "没有调用 uiautomator dump"
    assert any("/data/local/tmp/" in a for a in dumped[0]), \
        "dump 仍写 /sdcard（旧文件删不掉，会读到上一屏）"


def test_dump_clears_previous_file_first(monkeypatch):
    """必须先删旧文件，否则读到的是上次的内容。"""
    seen = []

    def fake(cmd, **k):
        seen.append(list(cmd))
        if "cat" in cmd:
            return R(out=b"<hierarchy></hierarchy>")
        return R(out=b"UI hierchary dumped to: x")

    monkeypatch.setattr(subprocess, "run", fake)
    _dev().dump()
    first_cmds = [c for c in seen[:3]]
    assert any("rm" in c for c in first_cmds), \
        "dump 前没有 rm 旧文件：%s" % first_cmds


def test_dump_returns_empty_when_file_is_stale(monkeypatch):
    """uiautomator 谎报成功但文件是 0 字节/不存在时，必须返回空而不是旧页面。"""
    def fake(cmd, **k):
        if "cat" in cmd:
            return R(out=b"", err=b"No such file or directory", rc=1)
        return R(out=b"UI hierchary dumped to: x")

    monkeypatch.setattr(subprocess, "run", fake)
    assert _dev().dump(retries=1) == ""


def test_dump_kills_stuck_uiautomator(monkeypatch):
    """卡死的 uiautomator 要 pkill 掉再重试，否则整条采集线永久空转。"""
    seen = []

    def fake(cmd, **k):
        seen.append(list(cmd))
        if "cat" in cmd:
            return R(out=b"")
        if "pkill" in cmd:
            return R()
        return R(out=b"UI hierchary dumped to: x")

    monkeypatch.setattr(subprocess, "run", fake)
    _dev().dump(retries=1)
    assert any("pkill" in c for c in seen), "没有尝试重启卡死的 uiautomator"
