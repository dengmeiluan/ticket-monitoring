# -*- coding: utf-8 -*-
"""App 渠道的网页内嵌登录会话。

设计要点（spec §4.2）：
  * 一个 slot 一个会话，持有 runtime/device 引用与状态机；
  * 帧获取带内容哈希——同一画面不重复传 200KB PNG；
  * 点击坐标按**原始分辨率**回传，会话负责按当前屏幕换算；
  * 完成时导出登录态快照（P3 后半），失败有明确文案与重试入口。

本模块只做会话逻辑，不碰 HTTP：端点层薄薄一层贴在 webui.py，
这样状态机可以脱离服务器单测。
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional

# 会话状态
ST_PENDING = "pending"        # 已起 App，等用户操作
ST_SAVING = "saving"          # 正在导出快照
ST_DONE = "done"              # 完成
ST_ERROR = "error"            # 失败
ST_EXPIRED = "expired"        # 超时/被回收


class AppLoginSession:
    """一次 App 登录的上下文。线程安全（帧与点击可能并发）。"""

    def __init__(self, plat: str, runtime, package: str,
                 timeout_s: int = 900, logger=None):
        self.plat = plat
        self.package = package
        self.runtime = runtime
        self.logger = logger
        self.created_at = time.time()
        self.timeout_s = int(timeout_s or 900)
        self.status = ST_PENDING
        self.detail = ""
        self._lock = threading.Lock()
        self._last_hash = ""
        self._last_png = b""
        self.frames = 0        # 统计：供健康/调试观察
        self.taps = 0

    # ---------- 生命周期 ----------
    def expired(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self.created_at) > self.timeout_s

    def alive(self) -> bool:
        return self.status in (ST_PENDING, ST_SAVING) and not self.expired()

    def finish(self, ok: bool, detail: str = ""):
        with self._lock:
            self.status = ST_DONE if ok else ST_ERROR
            self.detail = str(detail or "")[:200]

    # ---------- 帧 ----------
    def frame(self):
        """返回 (png_bytes, changed)。画面没变时不重发全图。

        返回 (b"", False) 表示"画面未变，用你手上那帧就行"。
        """
        with self._lock:
            if self.status not in (ST_PENDING, ST_SAVING):
                return b"", False
            dev = self.runtime.device() if self.runtime else None
            if dev is None:
                return b"", False
            png = dev.screencap()
            if not png:
                return b"", False
            h = hashlib.sha1(png).hexdigest()
            self.frames += 1
            if h == self._last_hash:
                return b"", False
            self._last_hash = h
            self._last_png = png
            return png, True

    def last_frame(self) -> bytes:
        with self._lock:
            return self._last_png

    # ---------- 交互 ----------
    def tap(self, x: int, y: int) -> bool:
        """按原始画面坐标点击；越界直接拒绝（不盲目点空）。"""
        with self._lock:
            if self.status != ST_PENDING:
                return False
            try:
                px, py = int(x), int(y)
            except (TypeError, ValueError):
                return False
            if px < 0 or py < 0:
                return False
            dev = self.runtime.device() if self.runtime else None
            if dev is None:
                return False
            w, h = dev.window_size()
            if w and h and (px >= w or py >= h):
                self.detail = f"点击超出屏幕 {w}x{h}"
                return False
            ok = dev.tap(px, py)
            if ok:
                self.taps += 1
            return bool(ok)

    def input_text(self, text: str) -> bool:
        with self._lock:
            if self.status != ST_PENDING:
                return False
            dev = self.runtime.device() if self.runtime else None
            if dev is None:
                return False
            return bool(dev.input_text(text))

    def keyevent(self, key: str) -> bool:
        with self._lock:
            if self.status != ST_PENDING:
                return False
            dev = self.runtime.device() if self.runtime else None
            return bool(dev and dev.keyevent(key))

    # ---------- 视图 ----------
    def view(self) -> dict:
        return {
            "plat": self.plat,
            "status": self.status,
            "detail": self.detail,
            "frames": self.frames,
            "taps": self.taps,
            "age_s": int(time.time() - self.created_at),
            "can_interact": self.status == ST_PENDING and not self.expired(),
        }


class AppLoginRegistry:
    """按 plat 管理登录会话；同时只允许一个（同一台设备是串行资源）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def get(self, plat: str) -> Optional[AppLoginSession]:
        with self._lock:
            s = self._sessions.get(plat)
            if s is not None and not s.alive():
                # 过期会话保留最后一次状态供前端展示，但不允许再交互
                if s.status == ST_PENDING:
                    s.status = ST_EXPIRED
                    s.detail = "登录超时，请重新发起"
            return s

    def put(self, session: AppLoginSession) -> AppLoginSession:
        with self._lock:
            old = self._sessions.get(session.plat)
            if old is not None and old.alive():
                raise ValueError(f"{session.plat} 已有进行中的登录会话")
            self._sessions[session.plat] = session
            return session

    def drop(self, plat: str):
        with self._lock:
            self._sessions.pop(plat, None)

    def plats(self):
        with self._lock:
            return sorted(self._sessions)
