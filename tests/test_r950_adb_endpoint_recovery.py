# -*- coding: utf-8 -*-
"""r950：把「adb 端点 offline」误诊成「Android 被我改挂了」，白重启了实例。

2026-11-04 实测到的真实序列：

```
$ adb devices -l
127.0.0.1:16384   offline            ← TCP 端点
emulator-5554     device product:V2405A model:V2405A   ← 同一实例的另一个端点！
```

同一台实例，一个端点 offline、另一个 `device` —— 这就排除了"系统挂了"，
只能是**本地 adb 侧的握手状态坏了**。而 `offline` 的常见成因全是我自己
正常操作带来的：`adb root`（重启 adbd）、`adb kill-server`、MuMu 的双端点。

当时的处置错了：`runtime.ensure_ready()` 里只做一次 `dev.connect()`，
而本地 server 握手坏掉时 `connect` 会返回 `already connected` **却仍 offline**；
于是我判定"设备离线"→ 去 `MuMuManager control restart` →
**白丢一轮采集 + 所有内存态**。实际只要
`kill-server` + `start-server` + `connect`，**9 秒**就恢复。

修法：`AdbDevice.reconnect()` 逐级恢复

```
1. connect                      （会话未建立）
2. disconnect + connect         （僵尸挂接）
3. kill-server + start-server   （本地 server 缓存的坏握手）← 这次需要的
```

并加 `state()` 明确区分 `device / offline / unauthorized / absent`，
让"端点问题"和"设备故障"在代码里就是**两种不同的处置路径**。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r950_adb_endpoint_recovery.py -q
"""
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android.device import AdbDevice  # noqa: E402

ADB = r"D:\fake\adb.exe"
SERIAL = "127.0.0.1:16384"


class R:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def _dev():
    # settle_s 压到 0：测试不真的睡
    return AdbDevice(ADB, SERIAL, timeout=5)


# ---------------------------------------------------------------------------
# 1. state()：必须能区分端点状态（这是"先分辨再处置"的前提）
# ---------------------------------------------------------------------------
def test_state_reads_serial_state(monkeypatch):
    def fake(cmd, **k):
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\toffline\n"
                     + b"emulator-5554\tdevice\n")
        return R()
    monkeypatch.setattr(subprocess, "run", fake)
    assert _dev().state() == "offline"


def test_state_absent_when_not_listed(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **k: R(out=b"List of devices attached\n"))
    assert _dev().state() == "absent"


# ---------------------------------------------------------------------------
# 2. reconnect 逐级升级：第 1 级就好就不要动 server
# ---------------------------------------------------------------------------
def test_reconnect_stops_at_first_success(monkeypatch):
    calls = []

    def fake(cmd, **k):
        calls.append(" ".join(str(x) for x in cmd))
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\tdevice\n")
        return R(out=b"connected")
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res == "device", res
    assert not any("kill-server" in c for c in calls), \
        "一开始就 device 态还去重启 server（会打断别的 adb 使用者）"


# ---------------------------------------------------------------------------
# 3. 核心：connect 修不好时必须升级到 kill-server + start-server
# ---------------------------------------------------------------------------
def test_reconnect_escalates_to_server_restart(monkeypatch):
    """复刻 2026-11-04 的真实故障：connect 说成功，状态仍 offline。"""
    calls = []
    state = {"now": "offline"}

    def fake(cmd, **k):
        c = " ".join(str(x) for x in cmd)
        calls.append(c)
        if "devices" in cmd:
            body = "List of devices attached\n%s\t%s\n" % (SERIAL, state["now"])
            return R(out=body.encode())
        if "kill-server" in c:
            state["now"] = "device"          # 重启 server 之后才好
            return R()
        return R(out=b"already connected")   # ← connect 骗人
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res.startswith("recovered"), res
    assert any("kill-server" in c for c in calls), "没升级到重启 server"
    assert any("start-server" in c for c in calls), "重启后没起 server"


def test_reconnect_reports_final_state_when_unrecoverable(monkeypatch):
    def fake(cmd, **k):
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\toffline\n")
        return R(out=b"unable to connect")
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res == "offline", res        # 如实返回，不许谎报恢复


# ---------------------------------------------------------------------------
# 4. runtime 必须用 reconnect，而不是裸 connect
# ---------------------------------------------------------------------------
def test_runtime_uses_reconnect():
    src = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
                  encoding="utf-8").read()
    assert "dev.reconnect(" in src, "runtime 没走逐级恢复"
    # 不许残留"只 connect 一次就判离线"
    assert "dev.connect()\n            if not dev.online()" not in src, \
        "还在只 connect 一次就判定设备离线"


def test_device_has_recovery_primitives():
    for m in ("state", "disconnect", "restart_server", "reconnect"):
        assert hasattr(AdbDevice, m), m


def test_error_message_names_the_endpoint_distinction():
    """`last_error` 要说清"试过哪些手段 + 当前端点状态"，
    否则下一次还是会被误诊成设备故障。"""
    src = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
                  encoding="utf-8").read()
    assert "端点状态" in src, "错误信息里没区分端点/设备"
