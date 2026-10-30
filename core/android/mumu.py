# -*- coding: utf-8 -*-
"""MuMuManager.exe 封装：发现安装位置、查询状态、控制实例。

所有方法都以「失败返回 None/False」为契约，不向上抛异常——调用方
（采集链路 / 健康面板）需要的是可展示的状态，不是调用栈。

实测依据（2026-10-27）：`MuMuManager.exe info -v 0` 返回 JSON，
含 `is_android_started` / `adb_port` / `hyperv_enabled`；
`control -v N launch|shutdown` 返回 `{"errcode":0}`。
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, Optional

from .config import DEFAULT_INSTALL_DIRS

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(cmd, timeout):
    """执行命令并吞掉所有异常，返回 CompletedProcess 或 None。"""
    kwargs = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _decode(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


class MuMuManager:
    """MuMu 模拟器管理器。

    构造后 `manager_path` / `adb_path` 可能为空，用 `available()` 判定；
    测试可注入 `_exists` 覆盖真实文件探测。
    """

    def __init__(self, install_dir: str = "", vm_index: int = 0,
                 timeout: int = 60):
        self.install_dir = os.path.abspath(install_dir) if install_dir else ""
        self.vm_index = int(vm_index or 0)
        self.timeout = int(timeout or 60)
        self._exists: Optional[bool] = None
        self.last_error = ""
        self.manager_path = ""
        self.adb_path = ""
        self._resolve_paths()

    # ---------- 路径 ----------
    def _resolve_paths(self):
        base = self.install_dir
        if not base:
            for cand in DEFAULT_INSTALL_DIRS:
                if os.path.isdir(cand):
                    base = cand
                    break
        self.install_dir = base or ""
        if not base:
            return
        shell = os.path.join(base, "nx_main")
        for name, attr in (("MuMuManager.exe", "manager_path"),
                           ("adb.exe", "adb_path")):
            path = os.path.join(shell, name)
            if os.path.exists(path):
                setattr(self, attr, path)

    def available(self) -> bool:
        """可用性判定：不存在的路径不触发任何外部进程。"""
        if self._exists is not None:
            return bool(self._exists and self.manager_path)
        return bool(self.manager_path and os.path.exists(self.manager_path))

    # ---------- 内部执行 ----------
    def _call(self, args, timeout=None) -> Optional[str]:
        if not self.available():
            self.last_error = "manager unavailable"
            return None
        proc = _run([self.manager_path, *args],
                    timeout or self.timeout)
        if proc is None:
            self.last_error = "timeout or spawn failure"
            return None
        out = _decode(proc.stdout)
        err = _decode(proc.stderr)
        if proc.returncode != 0 and not out.strip():
            self.last_error = (err or f"rc={proc.returncode}").strip()[:200]
            return None
        return out

    def _call_json(self, args, timeout=None) -> Optional[dict]:
        out = self._call(args, timeout=timeout)
        if not out:
            return None
        text = out.strip()
        start = text.find("{")
        if start < 0:
            self.last_error = "non-json output"
            return None
        try:
            data = json.loads(text[start:])
        except (ValueError, TypeError):
            self.last_error = "json parse failed"
            return None
        return data if isinstance(data, dict) else None

    # ---------- 查询 ----------
    def info(self, vm: Optional[int] = None) -> Optional[dict]:
        """实例信息；键含 is_android_started / adb_port / player_state。"""
        out = self._call_json(["info", "-v", str(self._vm(vm))])
        return out

    def list_info(self) -> Dict[str, Any]:
        out = self._call_json(["info", "-v", "all"])
        return out or {}

    def engine_state(self) -> Dict[str, Any]:
        """各 Android 引擎安装状态：{"12": {...}, "15": {...}}。"""
        out = self._call_json(["main", "engine", "state"])
        if not out:
            return {}
        ret = out.get("return")
        return ret if isinstance(ret, dict) else {}

    def setting(self, key: str, value: Any = None,
                vm: Optional[int] = None) -> Optional[str]:
        args = ["setting", "-v", str(self._vm(vm)), "-k", str(key)]
        if value is not None:
            args += ["-val", str(value).lower() if isinstance(value, bool)
                     else str(value)]
        return self._call(args)

    # ---------- 控制 ----------
    def launch(self, vm: Optional[int] = None) -> bool:
        out = self._call_json(["control", "-v", str(self._vm(vm)), "launch"],
                              timeout=max(self.timeout, 120))
        return bool(out and out.get("errcode") == 0)

    def shutdown(self, vm: Optional[int] = None) -> bool:
        out = self._call_json(["control", "-v", str(self._vm(vm)), "shutdown"],
                              timeout=max(self.timeout, 120))
        return bool(out and out.get("errcode") == 0)

    def restart(self, vm: Optional[int] = None) -> bool:
        out = self._call_json(["control", "-v", str(self._vm(vm)), "restart"],
                              timeout=max(self.timeout, 180))
        return bool(out and out.get("errcode") == 0)

    def app_install(self, apk: str, vm: Optional[int] = None) -> bool:
        out = self._call_json(
            ["control", "-v", str(self._vm(vm)), "app", "install",
             "-apk", apk], timeout=max(self.timeout, 600))
        return bool(out and out.get("errcode") == 0)

    def adb_serial(self, vm: Optional[int] = None) -> str:
        """从 info 里取 adb 地址；取不到时回退到约定端口。"""
        info = self.info(vm) or {}
        host = str(info.get("adb_host_ip") or "127.0.0.1")
        port = info.get("adb_port")
        if port:
            return f"{host}:{port}"
        idx = self._vm(vm)
        return f"127.0.0.1:{16384 + 32 * idx}"

    def _vm(self, vm: Optional[int]) -> int:
        return self.vm_index if vm is None else int(vm)
