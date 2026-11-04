# -*- coding: utf-8 -*-
"""Android 运行时：单例缓存、启动编排、设备独占锁。

职责边界：这是**唯一**决定「模拟器该不该起、adb 通不通」的地方。
上层（crawler / webui）只问 `ensure_ready()` 与 `status()`，不碰
MuMuManager 或 adb 细节。

为什么设备锁是模块级 threading.Lock 而不是 BoundedSemaphore(2)：
adb 设备是单实例串行资源，两个采集同时操作会互相打断（点击落在
对方的界面上）。浏览器渠道的 CHANNEL_GATE=2 针对多实例，语义不同。
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional, Tuple

from .config import AndroidConfig, normalize, resolve_install_dir
from .device import AdbDevice
from .mumu import MuMuManager

_DEVICE_LOCK = threading.Lock()
# 设备锁持有者观测（2026-11-04）：谁持着锁、从什么时候开始。
# 事故背景见 ``device_lock()`` 的 docstring——没有它，卡死 10 小时也查不出是谁。
_LOCK_STATE = {"owner": "", "since": 0.0}
_RUNTIME_CACHE = {}
_CACHE_LOCK = threading.Lock()


def reset_runtime_cache():
    """仅测试使用：清掉单例缓存。"""
    with _CACHE_LOCK:
        _RUNTIME_CACHE.clear()


class AndroidRuntime:
    """一台模拟器实例的生命周期与健康。"""

    def __init__(self, cfg: Optional[dict], logger: Optional[logging.Logger] = None,
                 full: Optional[dict] = None):
        self.cfg: AndroidConfig = normalize(cfg)
        # 原始配置留两份：``raw`` 是 android: 段（身份/隐藏层读它的子段），
        # ``full`` 是整份配置（要 user_data_dir 这种顶层键）。刻意不改
        # AndroidConfig 数据类——test_android_config 把字段集钉住了。
        self.raw: dict = dict(cfg) if isinstance(cfg, dict) else {}
        self.full: dict = dict(full) if isinstance(full, dict) else {}
        self.logger = logger
        self.last_error = ""
        self.identity_report: dict = {}
        self.stealth_report: dict = {}
        self.tuning_report: dict = {}
        self.display_report: dict = {}
        self.abi_report: dict = {}
        self.harden_report: dict = {}
        self._mumu: Optional[MuMuManager] = None
        self._device: Optional[AdbDevice] = None
        self._state = "disabled" if not self.cfg.enabled else "unknown"
        self._poll_interval = 2.0
        self._boot_waited = 0

    # ---------- 惰性构造（关闭时零副作用）----------
    def mumu(self) -> Optional[MuMuManager]:
        if not self.cfg.enabled:
            return None
        if self._mumu is None:
            install = resolve_install_dir(self.cfg)
            self._mumu = MuMuManager(
                install_dir=install,
                vm_index=self.cfg.vm_index,
                timeout=self.cfg.action_timeout_s,
            )
        return self._mumu

    def device(self) -> Optional[AdbDevice]:
        if not self.cfg.enabled:
            return None
        mgr = self.mumu()
        if mgr is None or not mgr.available():
            return None
        if self._device is None:
            serial = mgr.adb_serial()
            self._device = AdbDevice(mgr.adb_path, serial,
                                     timeout=self.cfg.action_timeout_s)
        return self._device

    # ---------- 状态 ----------
    def status(self) -> dict:
        return {
            "state": self._state,
            "detail": self.last_error,
            "adb_ok": self._state == "ready",
            "device": self._device if self._state == "ready" else None,
            "enabled": self.cfg.enabled,
            "vm_index": self.cfg.vm_index,
            # 身份/隐藏/调优/显示/ABI 的最近一次报告（UI 与风险评分都读它；
            # 空 = 还没跑过）
            "identity": self.identity_report,
            "stealth": self.stealth_report,
            "tuning": self.tuning_report,
            "display": self.display_report,
            "abi": self.abi_report,
        }

    # ---------- 编排 ----------
    def ensure_ready(self) -> Tuple[bool, str]:
        """确保「实例在跑 + adb 已连」。返回 (ok, reason)。"""
        if not self.cfg.enabled:
            self._state = "disabled"
            return False, "disabled"

        mgr = self.mumu()
        if mgr is None or not mgr.available():
            self._state = "not_installed"
            self.last_error = "MuMu 未安装或路径不可用"
            return False, "not_installed"

        info = mgr.info() or {}
        started = bool(info.get("is_android_started"))
        if not started:
            self._state = "starting"
            if not mgr.launch():
                self._state = "stopped"
                self.last_error = "启动指令失败"
                return False, "not_started"
            started = self._wait_boot(mgr)
            if not started:
                self._state = "starting"
                self.last_error = (
                    f"启动超时（{self.cfg.boot_timeout_s}s 内未就绪）")
                return False, "timeout"

        dev = self.device()
        if dev is None:
            self._state = "error"
            self.last_error = "adb 不可用"
            return False, "adb"

        if not dev.online():
            # 再连一次；MuMu 偶尔在首次查询时会话未建立
            dev.connect()
            if not dev.online():
                self._state = "error"
                self.last_error = "adb 未连接（设备离线）"
                return False, "adb"

        self._state = "ready"
        self.last_error = ""
        self._harden(dev)
        return True, "ready"

    # ---------- 设备硬化（身份 + root/模拟器隐藏）----------
    def _user_data_dir(self) -> str:
        raw = self.full.get("user_data_dir") if self.full else ""
        return str(raw or "user_data")

    def _layer_cfg(self) -> dict:
        """给身份/隐藏层的配置视图：``{"android": <android 段>}``。

        这两层都用 ``config["android"][...]`` 取自己的子段（与
        ``crawler.*`` 的读法一致），而 AndroidRuntime 手里只有 android 段，
        所以在这里补一层壳——不复制、不猜默认值。
        """
        out = dict(self.full)
        out["android"] = dict(self.raw)
        return out

    def _harden(self, dev) -> dict:
        """在 adb 连通之后、任何 App 启动之前，把设备硬化跑完。

        为什么挂在这里而不挂在各 App 渠道：``android.os.Build`` 的字段在
        zygote 里定型，**必须**在 App 进程起来之前改完（见
        ``fingerprint`` 模块头）。``ensure_ready()`` 是全项目唯一决定
        「模拟器起没起、adb 通不通」的地方，也是唯一能保证这个顺序的地方。

        具体五步（身份 → 显示对齐 → 隐藏 → 调优 → ABI 闸门）的**顺序**由
        ``hardening.harden`` 统一编排，这里只负责调用与曝光报告——两边都写
        顺序的话，迟早会有一边写错。

        失败一律不阻塞采集：拿不到 root、设备掉线、没装 Magisk，都只让
        报告变短（``identity`` / ``stealth`` 里能看到原因）。
        """
        rep = {}
        try:
            from . import hardening
        except Exception as e:            # 模块被裁掉也不能拖垮启动
            self.log("warning", "硬化层不可用：%s", e)
            return rep
        if not self.cfg.enabled:
            return rep

        try:
            rep = hardening.harden(
                dev, self._layer_cfg(), self.logger,
                vm=self.cfg.vm_index,
                user_data_dir=self._user_data_dir(), profile="device")
        except Exception as e:
            rep = {"ok": False, "error": str(e)[:160]}
        self.identity_report = rep.get("identity") or {}
        self.stealth_report = rep.get("stealth") or {}
        self.tuning_report = rep.get("tuning") or {}
        self.display_report = rep.get("display") or {}
        self.abi_report = rep.get("abi") or {}
        self.harden_report = rep
        return rep

    def _wait_boot(self, mgr: MuMuManager) -> bool:
        deadline = time.time() + self.cfg.boot_timeout_s
        while time.time() < deadline:
            time.sleep(self._poll_interval)
            self._boot_waited += self._poll_interval
            info = mgr.info() or {}
            if info.get("is_android_started"):
                return True
        return False

    # ---------- 设备独占 ----------
    @contextmanager
    def device_lock(self, timeout: float = 600.0, owner: str = ""):
        """独占 adb 设备；拿不到锁抛 TimeoutError（调用方转成 busy 状态）。

        ``owner`` 是"谁在用它"的标签（渠道名），用于**持有者观测**：
        2026-11-04 事故——某轮 `app_qunar` 的 worker 在路由级超时后仍在跑，
        永久占着这把锁；后面每轮每个 App 渠道都要白等 600s 才发现拿不到锁，
        单轮耗时远超 30 分钟间隔，apscheduler 于是**连续 10 小时全部 skipped**，
        而日志里只有「路由级超时」和「skipped」，看不出是谁占着锁。

        现在把「谁持锁、持了多久」记进模块级状态，超时/释放时都留痕，
        下次同类事故能一眼定位。
        """
        import time as _t
        t0 = _t.time()
        acquired = _DEVICE_LOCK.acquire(timeout=timeout)
        if not acquired:
            holder = dict(_LOCK_STATE)
            self.log("warning",
                     "设备锁等待 %ds 超时；当前持有者=%s（已持有 %.0fs）",
                     int(timeout), holder.get("owner") or "?",
                     _t.time() - float(holder.get("since") or _t.time()))
            raise TimeoutError("android device busy")
        waited = _t.time() - t0
        if waited >= 5:
            self.log("info", "设备锁等待 %.0fs 后取得（上一持有者=%s）",
                     waited, _LOCK_STATE.get("owner") or "?")
        _LOCK_STATE.update({"owner": str(owner or "?"), "since": _t.time()})
        # 拿锁成功后的任何异常都不能把模块锁留在持有态（r667 用 __new__ 造桩
        # 时就没有 _device 属性）；预算 arm 与 yield 一起放进 try/finally。
        budget = 0.0
        dev = None
        try:
            # **arm 协作式截止时间**：拿到锁就同时给设备一个预算，超时后
            # worker 会在下一个 adb 调用处主动放弃 → 真正释放锁。
            # 这是"路由级超时"治不了的那个洞的正解（详见 device.set_deadline）。
            budget = self._fetch_budget_s()
            dev = getattr(self, "_device", None)
            if dev is not None and budget > 0:
                try:
                    dev.set_deadline(budget)
                except Exception:
                    pass
            yield
        finally:
            if dev is not None:
                try:
                    hits = int(getattr(dev, "deadline_hits", 0) or 0)
                    dev.set_deadline(0)          # 解除，别影响后续操作
                except Exception:
                    hits = 0
            else:
                hits = 0
            held = _t.time() - float(_LOCK_STATE.get("since") or _t.time())
            if hits:
                # 明确留痕：这一轮是**因为预算耗尽被主动掐断**，不是设备掉线
                self.log("warning",
                         "%s 采集超出预算 %.0fs，已主动放弃（%d 次 adb 被拦），"
                         "锁已释放", _LOCK_STATE.get("owner") or "?", budget, hits)
            elif held >= 120:
                # 单次持有超过 2 分钟就留痕：正常一轮 App 采集通常在 60s 内
                self.log("warning", "设备锁被 %s 持有 %.0fs（偏长，留意是否卡住）",
                         _LOCK_STATE.get("owner") or "?", held)
            _LOCK_STATE.update({"owner": "", "since": 0.0})
            _DEVICE_LOCK.release()

    def _fetch_budget_s(self) -> float:
        """单次 App 采集的预算秒数（``android.fetch_budget_s``）。

        默认 **540s**——刻意低于路由级超时（900s）：必须先让 worker 自己
        退出并释放锁，路由那边才不会因为"等不到人"而把整轮拖住。
        0 = 不限制（回到旧行为，出问题时可以一键关掉）。
        """
        try:
            # getattr 兜底：单测里常用 `__new__` 造桩对象，没有走 __init__
            # 就没有 raw 属性——辅助方法不能因此抛异常（fail-soft 惯例）。
            raw = getattr(self, "raw", None) or {}
            v = raw.get("fetch_budget_s", 540) if isinstance(raw, dict) else 540
            n = float(v)
        except (TypeError, ValueError):
            return 540.0
        return max(0.0, min(3600.0, n))

    def lock_state(self) -> dict:
        """当前设备锁持有者（给健康面板/排障用）。"""
        st = dict(_LOCK_STATE)
        try:
            st["budget_left"] = (self._device.deadline_left()
                                 if self._device is not None else 0.0)
            st["deadline_hits"] = int(getattr(self._device, "deadline_hits", 0)
                                      or 0)
        except Exception:
            pass
        return st

    def log(self, level: str, msg: str, *args):
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        try:
            getattr(logger, level)("[android] " + str(msg), *args)
        except Exception:
            pass


def get_runtime(cfg: Optional[dict],
                logger: Optional[logging.Logger] = None) -> AndroidRuntime:
    """按配置指纹缓存运行时实例（进程内单例）。"""
    android_cfg = (cfg or {}).get("android") if isinstance(cfg, dict) else None
    norm = normalize(android_cfg)
    key = (norm.enabled, norm.install_dir, norm.vm_index,
           norm.boot_timeout_s, norm.action_timeout_s)
    with _CACHE_LOCK:
        rt = _RUNTIME_CACHE.get(key)
        if rt is None:
            rt = AndroidRuntime(android_cfg, logger, full=cfg)
            _RUNTIME_CACHE[key] = rt
        elif logger is not None and rt.logger is None:
            rt.logger = logger
        return rt
