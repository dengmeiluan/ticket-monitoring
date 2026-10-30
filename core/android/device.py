# -*- coding: utf-8 -*-
"""ADB 设备原语：截图、点击、输入、UI 树、启停 App。

所有方法失败返回空值（b"" / "" / False），不抛异常——设备掉线是常态，
采集层需要把它变成一条 `path_note`，而不是一个调用栈。

实测基准（2026-10-27，MuMu 实例 0）：
  exec-out screencap -p  ≈ 63–91ms
  uiautomator dump + cat ≈ 75–77ms
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_OFFLINE_MARKS = ("device offline", "device not found", "no devices",
                  "device '", "unauthorized")

# UI dump 落到设备内的固定路径，避免每次随机名堆积
# UI dump 落点：/sdcard 是 media_rw 挂载，shell 删不掉旧文件（实测 rm 返回空
# 但 ls 文件仍在），只能换成 shell 自己的可写目录才能保证「读到的是这一屏」。
_DUMP_TMP_PATH = "/data/local/tmp/tm_ui.xml"


def _run(cmd, timeout, binary=False):
    kwargs = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _text(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


class AdbDevice:
    """一台已连接设备（真机 / 模拟器同接口）。"""

    def __init__(self, adb_path: str, serial: str, timeout: int = 60):
        self.adb_path = adb_path
        self.serial = serial
        self.timeout = int(timeout or 60)
        self.last_error = ""

    # ---------- 基础 ----------
    def _base(self):
        return [self.adb_path, "-s", self.serial]

    def _sh(self, *args, timeout=None):
        proc = _run(self._base() + list(args), timeout or self.timeout)
        if proc is None:
            self.last_error = "timeout or spawn failure"
            return None
        out = _text(proc.stdout)
        err = _text(proc.stderr)
        if proc.returncode != 0:
            low = (out + err).lower()
            self.last_error = next(
                (m for m in _OFFLINE_MARKS if m in low),
                (err or out).strip()[:200] or f"rc={proc.returncode}")
        return out

    def connect(self) -> bool:
        proc = _run([self.adb_path, "connect", self.serial], self.timeout)
        if proc is None:
            self.last_error = "connect spawn failure"
            return False
        return "connected" in _text(proc.stdout).lower()

    def online(self) -> bool:
        """`adb devices` 里该 serial 处于 device 态。"""
        out = _text((_run([self.adb_path, "devices"], self.timeout)
                     or type("X", (), {"stdout": b""})()).stdout)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self.serial:
                return parts[1] == "device"
        return False

    def prop(self, key: str) -> str:
        return (_self_out(self._sh("shell", "getprop", str(key))) or "").strip()

    # ---------- 观测 ----------
    def dump(self, retries: int = 2) -> str:
        """UI 层级 XML；拿不到返回空串（不缓存上一轮结果）。

        必须校验**新鲜度与归属**。实测（MuMu Android 12）两种失效：
          ① `/sdcard/tm_ui.xml` 属 media_rw，shell 删不掉，旧文件一直在；
          ② uiautomator 服务卡死时照样打印 "dumped to"，但文件是 0 字节
             或未被改写。
        两种情况下读到的都是**上一屏**——按它点击等于在旧界面上盲操作，
        比拿不到更危险。所以这里写到 shell 自己可写的 /data/local/tmp，
        并且要求「文件存在 + 大小 > 0 + 内容带 <hierarchy>」，连续失败
        就重启 uiautomator 再试一次。
        """
        for attempt in range(retries + 1):
            self._sh("shell", "rm", "-f", _DUMP_TMP_PATH)
            out = self._sh("shell", "uiautomator", "dump", _DUMP_TMP_PATH,
                           timeout=max(self.timeout, 60)) or ""
            if "dumped to" in out:
                xml = self._sh("shell", "cat", _DUMP_TMP_PATH) or ""
                if "<hierarchy" in xml:
                    return xml
            # 卡死自愈：pkill 掉僵住的 uiautomator，下一轮重新拉服务
            if attempt < retries:
                self._sh("shell", "pkill", "-f", "uiautomator")
                time.sleep(1.0)
        if not self.last_error:
            self.last_error = "dump failed"
        return ""

    def screencap(self) -> bytes:
        """PNG 字节流；失败返回 b""。"""
        if not self.adb_path:
            return b""
        proc = _run([self.adb_path, "-s", self.serial,
                     "exec-out", "screencap", "-p"],
                    max(self.timeout, 30))
        if proc is None or proc.returncode != 0:
            self.last_error = "screencap failed"
            return b""
        data = proc.stdout or b""
        if not data.startswith(b"\x89PNG"):
            self.last_error = "screencap returned non-png"
            return b""
        return data

    def current_activity(self) -> str:
        out = self._sh("shell", "dumpsys", "activity", "activities",
                       timeout=max(self.timeout, 30)) or ""
        m = re.search(r"topResumedActivity=ActivityRecord\{\S+ \S+ (\S+?)\s",
                      out)
        if m:
            return m.group(1)
        m = re.search(r"mResumedActivity.*? (\S+/\S+)", out)
        return m.group(1) if m else ""

    # ---------- 交互 ----------
    def tap(self, x: int, y: int) -> bool:
        if not self._coord_ok(x) or not self._coord_ok(y):
            return False
        out = self._sh("shell", "input", "tap", str(int(x)), str(int(y)))
        return out is not None

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> bool:
        if not all(self._coord_ok(v) for v in (x1, y1, x2, y2)):
            return False
        out = self._sh("shell", "input", "swipe",
                       str(int(x1)), str(int(y1)),
                       str(int(x2)), str(int(y2)), str(int(duration_ms)))
        return out is not None

    def input_text(self, text: str) -> bool:
        """输入文本。空格转 %s（input text 的约定），并做 shell 转义。"""
        if text is None:
            return False
        payload = str(text).replace(" ", "%s")
        out = self._sh("shell", "input", "text",
                       shlex.quote(payload))
        return out is not None

    def keyevent(self, key: str) -> bool:
        out = self._sh("shell", "input", "keyevent", str(key))
        return out is not None

    # ---------- App ----------
    def app_start(self, pkg: str) -> bool:
        out = self._sh("shell", "monkey", "-p", pkg,
                       "-c", "android.intent.category.LAUNCHER", "1",
                       timeout=max(self.timeout, 60))
        if out is None:
            return False
        return "Events injected" in out or "No activities found" not in out

    def app_stop(self, pkg: str) -> bool:
        out = self._sh("shell", "am", "force-stop", pkg)
        return out is not None

    def deep_link(self, uri: str) -> bool:
        """用 scheme 深链启动 App 的目标页。

        有些 App 的首屏是强制登录页，但深链能直达功能页（去哪儿实测：
        首屏 UCLoginByPhoneActivity，qunarphone://flight 直接进机票首页）。
        失败返回 False，调用方回落到 app_start。
        """
        out = self._sh("shell", "am", "start", "-a",
                       "android.intent.action.VIEW", "-d", uri,
                       timeout=max(self.timeout, 60))
        if out is None:
            return False
        low = out.lower()
        return "error" not in low and "unable to resolve" not in low

    def app_installed(self, pkg: str) -> bool:
        out = self._sh("shell", "pm", "list", "packages") or ""
        return any(line.strip() == f"package:{pkg}"
                   for line in out.splitlines())

    def window_size(self) -> tuple:
        """(w, h)；解析失败返回 (0, 0)。"""
        out = self._sh("shell", "wm", "size") or ""
        m = re.search(r"(\d+)\s*x\s*(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def root(self) -> bool:
        """切 adbd 为 root（MuMu 支持；失败也不致命）。"""
        self._sh("root", timeout=max(self.timeout, 30))
        time.sleep(1.5)
        out = self._sh("shell", "id") or ""
        return "uid=0" in out

    # ---------- 内部 ----------
    @staticmethod
    def _coord_ok(v) -> bool:
        try:
            return int(v) >= 0
        except (TypeError, ValueError):
            return False


def _self_out(value):
    return value if value is not None else ""
