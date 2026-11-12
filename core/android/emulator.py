"""模拟器生命周期（r1063 T63）：**自己把模拟器拉起来**，不再让用户手动点。

为什么需要
----------
App 渠道（`app_fliggy` / `app_zhixing` / `app_qunar` …）全部依赖那台模拟器。
它没起来时，界面上只会显示"已启用但没连到设备"——用户得自己开 MuMu、等开机、
再点一次自检。这条把这件事变成程序能做的：

* `status()` 读实例状态（是否在跑 / 安卓是否起来 / adb 地址）；
* `ensure_running()` 没起来就 `launch()` 并**等到安卓真的起来 + adb 可见**；
* `restart()` 卡死/异常时一键重启（用户明确要求："模拟器重启你自己重启啊"）。

纪律
----
* **只读优先**：`status()` 不触发任何启动动作；
* **有上限**：等待有超时（默认 180s），超时如实返回失败原因，不假装成功；
* **失败进账本**：拉不起来要记进 `core.degraded`（"能力悄悄没起来"比"报错"更难查）；
* 不碰账号、不碰配置——只负责"把机器开着"。
"""
from __future__ import annotations

import logging
import time

_LOG = logging.getLogger(__name__)


def _mgr(cfg: dict = None, *, vm_index=None):
    """拿到 MuMuManager（配置缺省时用默认安装目录）。"""
    from .config import normalize, resolve_install_dir
    from .mumu import MuMuManager

    sec = {}
    if isinstance(cfg, dict):
        sec = cfg.get("android") if isinstance(cfg.get("android"), dict) else {}
    norm = normalize(sec)
    idx = int(vm_index if vm_index is not None else getattr(norm, "vm_index", 0)
              or 0)
    return MuMuManager(
        install_dir=str(sec.get("install_dir") or resolve_install_dir(norm)),
        vm_index=idx)


def status(cfg: dict = None, **kw) -> dict:
    """实例状态（只读）。`running` 指"安卓已起来"，不是"进程存在"。"""
    try:
        mgr = _mgr(cfg, **kw)
    except Exception as e:
        return {"available": False, "running": False, "why": str(e)[:80]}
    if not mgr.available():
        return {"available": False, "running": False,
                "why": "找不到 MuMuManager（检查 android.install_dir）"}
    info = {}
    try:
        info = mgr.info() or {}
    except Exception as e:
        return {"available": True, "running": False,
                "why": "info 读不到：%s" % str(e)[:60]}
    return {
        "available": True,
        "running": bool(info.get("is_android_started")),
        "process": bool(info.get("is_process_started")),
        "state": str(info.get("player_state") or ""),
        "pid": info.get("pid"),
        "adb": str(info.get("adb_host_ip") or "127.0.0.1") + ":"
               + str(info.get("adb_port") or ""),
        "adb_path": str(getattr(mgr, "adb_path", "") or ""),
        "android": str(info.get("android_version") or ""),
        "why": "",
    }


def device(cfg: dict = None, **kw):
    """按配置造一个 `AdbDevice`（**带 adb 可执行路径**，与 runtime 同构）。

    踩过三次的坑：`AdbDevice("", serial)` 的 `_base()` 会是
    `["", "-s", serial]` → 任何 adb 调用都失败，还静默返回"设备不存在"。
    """
    mgr = _mgr(cfg, **kw)
    from .device import AdbDevice
    return AdbDevice(mgr.adb_path, mgr.adb_serial(),
                     timeout=30, )


def _adb_visible(serial: str, adb_path: str = "") -> bool:
    """adb 里能看到这台且状态是 device。`adb_path` 空则退回 PATH 里的 adb。"""
    try:
        from .device import AdbDevice
        dev = AdbDevice(adb_path or "adb", serial)
        return str(dev.state() or "") == "device"
    except Exception:
        return False


def ensure_running(cfg: dict = None, *, wait_s: float = 180.0,
                   logger=None, poll_s: float = 3.0) -> dict:
    """确保模拟器**安卓已起来且 adb 可见**；没起来就自己拉起并等待。

    返回 `{"ok", "launched", "waited_s", "status", "why"}`。超时就是失败——
    不把"进程在跑"当成"能用"。
    """
    log = logger or _LOG
    st = status(cfg)
    if not st.get("available"):
        _note(cfg, st.get("why") or "模拟器不可用")
        return {"ok": False, "launched": False, "waited_s": 0.0,
                "status": st, "why": st.get("why") or "不可用"}
    serial = st.get("adb") or ""
    _ap = str((st.get("adb_path") or ""))
    if st.get("running") and serial and _adb_visible(serial, _ap):
        return {"ok": True, "launched": False, "waited_s": 0.0, "status": st,
                "why": "已在运行"}
    launched = False
    if not st.get("running"):
        try:
            mgr = _mgr(cfg)
            launched = bool(mgr.launch())
            log.info("[模拟器] 已发送启动指令：%s", launched)
        except Exception as e:
            log.warning("[模拟器] 启动指令失败：%s", str(e)[:80])
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(poll_s)
        st = status(cfg)
        serial = st.get("adb") or ""
        if st.get("running") and serial and _adb_visible(
                serial, str(st.get("adb_path") or "")):
            took = round(time.time() - t0, 1)
            log.info("[模拟器] 已就绪（等了 %.1fs，adb=%s）", took, serial)
            return {"ok": True, "launched": launched, "waited_s": took,
                    "status": st, "why": "启动后可见"}
    took = round(time.time() - t0, 1)
    why = ("等了 %.0fs 仍未就绪（state=%s, process=%s）"
           % (wait_s, st.get("state") or "?", st.get("process")))
    _note(cfg, why)
    log.warning("[模拟器] %s", why)
    return {"ok": False, "launched": launched, "waited_s": took, "status": st,
            "why": why}


def restart(cfg: dict = None, *, wait_s: float = 240.0, logger=None) -> dict:
    """重启实例（卡死/装不上/开机卡住时用），然后等它就绪。"""
    log = logger or _LOG
    try:
        mgr = _mgr(cfg)
        if not mgr.available():
            return {"ok": False, "why": "找不到 MuMuManager"}
        log.info("[模拟器] 执行重启…")
        mgr.restart()
    except Exception as e:
        _note(cfg, "重启失败：%s" % str(e)[:60])
        return {"ok": False, "why": "重启失败：%s" % str(e)[:80]}
    # 重启后**不要**再 launch，只等
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(3.0)
        st = status(cfg)
        serial = st.get("adb") or ""
        if st.get("running") and serial and _adb_visible(
                serial, str(st.get("adb_path") or "")):
            took = round(time.time() - t0, 1)
            log.info("[模拟器] 重启完成（%.1fs）", took)
            return {"ok": True, "restarted": True, "waited_s": took,
                    "status": st, "why": "重启后可见"}
    why = "重启后 %.0fs 仍不可见" % wait_s
    _note(cfg, why)
    return {"ok": False, "restarted": True, "waited_s": round(time.time() - t0, 1),
            "status": status(cfg), "why": why}


def _note(cfg, detail: str) -> None:
    """失败进降级账本（"能力悄悄没起来"比报错更难查）。"""
    try:
        from core import degraded as _dg
        _dg.note("emulator", "", detail)
    except Exception:
        pass
