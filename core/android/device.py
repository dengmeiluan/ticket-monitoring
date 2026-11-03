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
        # CLI dump 撞上 u2 已注册的 UiAutomation 后，本进程改用 u2
        self._prefer_u2 = False
        # 设计坐标系（默认 None = 不做任何换算，行为与改造前逐字一致）。
        # 只有在 ``display.spoof()`` 真改了 wm size 之后才该设置它：那时脚本
        # 里写死的常量属于「设计坐标」，而 UI 树 bounds 属于「设备坐标」。
        self.design = None
        self._size_cache = None

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
            # u2 的 UiAutomation 服务已注册时，CLI 每次都会以
            # 「already registered」崩掉；继续跑 CLI 只会在 logcat 里刷
            # FATAL，还可能把 u2 服务一起 pkill 掉。一旦确认这种状态，
            # 本进程后续直接走 u2。
            if self._prefer_u2:
                xml = self.dump_u2()
                if xml:
                    return xml
                self._prefer_u2 = False
            self._sh("shell", "rm", "-f", _DUMP_TMP_PATH)
            out = self._sh("shell", "uiautomator", "dump", _DUMP_TMP_PATH,
                           timeout=max(self.timeout, 60)) or ""
            if "dumped to" in out:
                xml = self._sh("shell", "cat", _DUMP_TMP_PATH) or ""
                if "<hierarchy" in xml:
                    return xml
            # 动画页（WebView）的 CLI dump 会直接报 idle 状态拿不到；立刻走
            # u2 回退，别再重试/pkill（实测重试+等待要 37s，u2 只要 0.3s）。
            low = ((out or "") + " " + (self.last_error or "")).lower()
            if "idle state" in low or "already registered" in low:
                xml = self.dump_u2()
                if xml:
                    if "already registered" in low:
                        self._prefer_u2 = True
                    return xml
                if "already registered" in low:
                    # 注册者可能就是 u2 自己的服务：pkill 会把回退也杀掉
                    break
            # 卡死自愈：pkill 掉僵住的 uiautomator，下一轮重新拉服务
            if attempt < retries:
                self._sh("shell", "pkill", "-f", "uiautomator")
                time.sleep(1.0)
        # CLI dump 在「持续动画的 WebView」上会报 could not get idle state；
        # uiautomator2 的 dump 不等 idle，能读到同程结果页的完整文本。
        # 它是**可选回退**：未安装时静默返回空，不改变既有依赖。
        xml = self.dump_u2()
        if xml:
            return xml
        if not self.last_error:
            self.last_error = "dump failed"
        return ""

    def dump_u2(self) -> str:
        """可选：用 uiautomator2 取层级（WebView 动画页的 CLI dump 会卡 idle）。"""
        try:
            import uiautomator2 as u2  # type: ignore
        except Exception:
            return ""
        try:
            dev = u2.connect(self.serial)
            xml = dev.dump_hierarchy() or ""
        except Exception as e:
            self.last_error = "u2 dump: %s" % str(e)[:120]
            return ""
        if "<hierarchy" not in xml:
            self.last_error = "u2 dump: no hierarchy"
            return ""
        return xml

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
    def set_design(self, width, height) -> tuple:
        """开启「设计坐标系 → 设备坐标系」换算；``(0,0)/None`` = 关闭。

        什么时候需要：``display.spoof()`` 改过 ``wm size`` 之后。这时脚本里
        **写死的常量**是设计坐标（按 900×1600 写的），而点击要的是设备坐标。
        不改屏幕就别开这个——开了会给每条坐标多乘一个比例。
        """
        try:
            w, h = int(width or 0), int(height or 0)
        except (TypeError, ValueError):
            w = h = 0
        self.design = (w, h) if (w > 0 and h > 0) else None
        self._size_cache = None
        return self.design

    def _scale(self) -> tuple:
        """(sx, sy)：设备像素 / 设计像素。读不到真实尺寸时退回 1.0。"""
        if not self.design:
            return (1.0, 1.0)
        if self._size_cache is None:
            try:
                self._size_cache = self.window_size() or (0, 0)
            except Exception:
                self._size_cache = (0, 0)
        w, h = self._size_cache
        dw, dh = self.design
        if min(int(w), int(h), int(dw), int(dh)) <= 0:
            return (1.0, 1.0)
        return (w / float(dw), h / float(dh))

    def to_device(self, x, y) -> tuple:
        """设计坐标 → 设备坐标（未开启换算时原样返回）。"""
        sx, sy = self._scale()
        return int(round(float(x) * sx)), int(round(float(y) * sy))

    def to_design(self, x, y) -> tuple:
        """设备坐标 → 设计坐标：UI 树 ``bounds`` 读出来的点要走这一层，
        再与写死的设计坐标比较/运算，否则会算错两倍。"""
        sx, sy = self._scale()
        return (int(round(float(x) / sx)),
                int(round(float(y) / sy)))

    def tap(self, x: int, y: int) -> bool:
        if not self._coord_ok(x) or not self._coord_ok(y):
            return False
        dx, dy = self.to_device(x, y)
        out = self._sh("shell", "input", "tap", str(dx), str(dy))
        return out is not None

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> bool:
        if not all(self._coord_ok(v) for v in (x1, y1, x2, y2)):
            return False
        ax, ay = self.to_device(x1, y1)
        bx, by = self.to_device(x2, y2)
        out = self._sh("shell", "input", "swipe",
                       str(ax), str(ay), str(bx), str(by),
                       str(int(duration_ms)))
        return out is not None

    def input_text(self, text: str) -> bool:
        """输入文本。空格转 %s（input text 的约定），并做 shell 转义。

        **必须校验文本真的进了界面**（r805ab 真机实测）：`adb shell input
        text` 在没有聚焦输入框时**同样是返回成功**——命令发出去了，字却
        掉在地上。内嵌画面此前只判「命令没报错」，于是用户点「输入文字」
        后接口回 ok、画面一动不动（真机：城市页输入 "bei"，前后两帧 sha1
        完全相同、视图树文本零变化）。

        这里输入后读一次视图树，确认目标文本真的出现；读不到（或无焦点
        导致没进去）就如实返回 False——调用方据此提示「请先点一下输入框」，
        而不是让用户对着一个撒谎的 ok 发呆。
        """
        if text is None:
            return False
        s = str(text)
        payload = s.replace(" ", "%s")
        out = self._sh("shell", "input", "text",
                       shlex.quote(payload))
        if out is None:
            return False
        # 校验：视图树里要出现该文本（去空格后比对，容忍输入法与转义差异）
        want = s.replace(" ", "").strip()
        if not want:
            return True
        try:
            page = self.dump() or ""
        except Exception:
            return True      # 读不到页面时不否决（dump 自身可能超时）
        return want in page.replace(" ", "")

    def keyevent(self, key: str) -> bool:
        out = self._sh("shell", "input", "keyevent", str(key))
        return out is not None

    # ---------- App ----------
    def lock_portrait(self) -> bool:
        """锁定竖屏（关自动旋转 + user_rotation=0）。

        采集脚本的元素坐标与滑动距离都按 900×1600 竖屏写。现场实证
        （2026-11-01 18:30）：模拟器 `accelerometer_rotation=1`，某一轮 App
        转成 **1600×900 横屏**——首页控件都在，但硬编码的
        `swipe(800,1200,…,600)` 的 y 已超出 900 屏高，整轮点不动，账本只记
        `set-city-dep`，人眼看是「这条通路时好时坏」。
        失败不影响采集（下一轮会再锁）。
        """
        ok = True
        for cmd in (("shell", "settings", "put", "system",
                     "accelerometer_rotation", "0"),
                    ("shell", "settings", "put", "system",
                     "user_rotation", "0")):
            if self._sh(*cmd) is None:
                ok = False
        return ok

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

    def start_component(self, component: str) -> bool:
        """用显式 `pkg/activity` 启动页面（App 没有可用深链时的入口）。

        携程 App 实测：`ctrip.business.planthome.CtripPlantHomeActivity`
        可以显式拉起机票查询页；没有可解析的 scheme 深链。
        """
        if not component or "/" not in component:
            return False
        out = self._sh("shell", "am", "start", "-n", component,
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
        """当前**生效的**屏幕 (w, h)；解析失败返回 (0, 0)。

        ⚠ 必须优先取 ``Override size``：``wm size`` 的输出有两行
        （``Physical size: 900x1600`` + ``Override size: 1080x1920``），
        取第一个匹配会永远拿到**物理**尺寸——屏幕被 ``wm size`` 改过之后，
        坐标换算比例就恒等于 1.0，写死的坐标会按比例全偏，而账本上只表现成
        「设城市失败 / 页面认不出」，极难追（2026-11-03 实机验证时踩到）。
        """
        out = self._sh("shell", "wm", "size") or ""
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out)
        if not m:
            m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        if not m:
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
