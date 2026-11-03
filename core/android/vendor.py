# -*- coding: utf-8 -*-
"""MuMu 宿主机侧官方接口：机型 / 屏幕 / 系统盘只读 / root。

为什么这层比改 props 更该优先用
------------------------------
2026-11-03 用 ``MuMuManager.exe setting -v 0 --all`` 枚举出这些**官方键**：

    phone_brand    Samsung
    phone_model    Galaxy A52 5G
    phone_miit     SM-A5260        ← 对应 ro.product.model
    phone_imei     865247046277134
    resolution_width/height  1600 / 900
    resolution_dpi           240
    root_permission          true
    system_disk_readonly     true   ← ABI 改不动的真正根因

和「改 props」这条路相比，官方键有三个压倒性优势：

1. **不需要 root、不需要 Magisk**——MuMu 自己在虚拟机启动时注入；
2. **可持久化**——写进实例配置，重启、快照、迁移都跟着走；
3. **不会静默失败**——写失败会回 ``errcode``，可用 ``setting -k`` 读回校验。

所以本项目的分层原则是：**能让 MuMu 官方做的，就别去改 props**；
props 那条路（``fingerprint``）只用来补官方不提供的那部分（序列号、
android_id、gsm 之类）。

``system_disk_readonly`` 特别说明
--------------------------------
它是最深的那层闸：设 ``true`` 时系统盘以只读方式挂给虚拟机，于是
``setprop ro.*``、``blockdev --setrw``、``remount rw`` 全部**静默无效**
（都是返回 0 但不变）。改成 ``false`` 并**重启实例**后才能 remount，
ABI 改写那条路才打开。本模块只负责"改设置 + 告诉你要重启"，不替你重启。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .fingerprint import _call, _text

# 允许写入的键白名单：只碰与「设备外观」和「系统盘可写」有关的，
# 绝不碰性能/网络/帧率——那些改错了会让采集变慢或断网。
_WRITABLE = (
    "phone_brand", "phone_model", "phone_miit", "phone_imei",
    "phone_number",
    "resolution_width", "resolution_height", "resolution_dpi",
    "resolution_mode",
    "system_disk_readonly",
)


def _manager(install_dir: str = "", vm_index: int = 0):
    from .config import normalize, resolve_install_dir
    from .mumu import MuMuManager
    cfg = normalize(None)
    return MuMuManager(install_dir=install_dir or resolve_install_dir(cfg),
                       vm_index=int(vm_index or 0))


def read(manager=None, *, install_dir: str = "", vm_index: int = 0) -> Dict[str, Any]:
    """读实例当前设置（``setting --all``）。失败返回空 dict。"""
    mgr = manager or _manager(install_dir, vm_index)
    if not mgr.available():
        return {}
    out = mgr._call_json(["setting", "-v", str(mgr._vm(None)), "--all"])
    return out if isinstance(out, dict) else {}


def get(key: str, manager=None, **kw) -> str:
    mgr = manager or _manager(kw.get("install_dir", ""), kw.get("vm_index", 0))
    if not mgr.available():
        return ""
    return str(mgr.setting(key) or "").strip()


def apply(manager=None, *, install_dir: str = "", vm_index: int = 0,
          logger=None, **values) -> dict:
    """写若干个官方键并**读回校验**。

    只接受 ``_WRITABLE`` 里的键（其余键忽略并记入 ``rejected``），
    因为性能/网络类键改错会直接让采集变慢或断网。

    返回 ``{"ok", "applied", "verify", "rejected", "restart_required"}``。
    ``restart_required=True`` 表示有键（如 ``system_disk_readonly``）必须
    重启实例才生效——本模块不替你重启，把决定权留给调用方。
    """
    mgr = manager or _manager(install_dir, vm_index)
    rep = {"ok": False, "applied": {}, "verify": {}, "rejected": [],
           "restart_required": False, "error": ""}
    if not mgr.available():
        rep["error"] = "MuMuManager 不可用"
        return rep
    vm = mgr._vm(None)
    for k, v in values.items():
        if k not in _WRITABLE:
            rep["rejected"].append(k)
            continue
        if mgr.setting(k, v) is None:
            rep["verify"][k] = {"want": str(v), "got": None, "ok": False}
            continue
        got = str(mgr.setting(k) or "").strip()
        want = str(v).strip()
        # 数值型键读回带 6 位小数（1600.000000），按数值比
        same = got == want
        if not same:
            try:
                same = abs(float(got) - float(want)) < 0.5
            except (TypeError, ValueError):
                same = False
        rep["verify"][k] = {"want": want, "got": got, "ok": same}
        if same:
            rep["applied"][k] = got
        if k in ("system_disk_readonly", "resolution_mode"):
            rep["restart_required"] = True
    rep["ok"] = bool(rep["applied"]) and all(
        x.get("ok") for x in rep["verify"].values())
    if logger and rep["applied"]:
        logger.info("[android] MuMu 官方设置已写入 %d 项%s",
                    len(rep["applied"]),
                    "（需重启实例生效）" if rep["restart_required"] else "")
    return rep


def spoof_device(manager=None, *, brand: str = "", model: str = "",
                 miit: str = "", imei: str = "", **kw) -> dict:
    """按「品牌 + 机型 + 入网型号」一起改（三件必须自洽）。

    为什么要一起给：``phone_brand`` 是 Xiaomi、``phone_model`` 是 Galaxy A52
    这种组合比不改更可疑——风控读 ``ro.product.brand`` 与 ``ro.product.model``
    就能看出矛盾。
    """
    vals = {}
    if brand:
        vals["phone_brand"] = brand
    if model:
        vals["phone_model"] = model
    if miit:
        vals["phone_miit"] = miit
    if imei:
        vals["phone_imei"] = imei
    return apply(manager, **kw, **vals)


def spoof_screen(manager=None, *, width: int = 0, height: int = 0,
                 dpi: int = 0, **kw) -> dict:
    """改分辨率/DPI（官方键）。**改分辨率必须同时开坐标换算**。

    App 渠道的坐标是按 900×1600 竖屏写死的，改屏幕后必须
    ``AdbDevice.set_design(900, 1600)``，否则点击会按比例偏——
    这条边界写在 ``core/android/display.py`` 里。
    """
    vals = {}
    if width:
        vals["resolution_width"] = width
    if height:
        vals["resolution_height"] = height
    if dpi:
        vals["resolution_dpi"] = dpi
    return apply(manager, **kw, **vals)


def unlock_system_disk(manager=None, *, restart: bool = False,
                       logger=None, **kw) -> dict:
    """把 ``system_disk_readonly`` 设成 ``false``（ABI 那条路的前置）。

    ``restart=True`` 时顺便重启实例（会中断正在进行的采集，**默认不重启**）。
    """
    rep = apply(manager, logger=logger, **kw, system_disk_readonly="false")
    rep["restarted"] = False
    if restart and rep.get("ok"):
        try:
            mgr = manager or _manager(kw.get("install_dir", ""),
                                      kw.get("vm_index", 0))
            rep["restarted"] = bool(mgr.restart())
        except Exception as e:
            rep["restart_error"] = str(e)[:120]
    return rep


# ---------------------------------------------------------------------------
# 按 App 伪装 ABI（MuMu 官方 abi-select 表）——2026-11-03 实测可用
# ---------------------------------------------------------------------------
# MuMu 用 `/system/etc/mumu-configs/abi-select-android12.config` 这张
# 「包名正则 → ABI」表决定**每个 App 用哪套 ABI 启动**。实测：

#   * 往表里加 ``ctrip\.android\.view   arm64-v8a`` 后重启 →
#     `dumpsys package ctrip.android.view` 的 primaryCpuAbi **真的变成
#     arm64-v8a**，nativeLibraryDir 指向 arm64 目录；
#   * 而**全局** ``ro.product.cpu.abi`` 仍是 ``x86_64`` ——
#     App 视角是 arm64，系统仍跑 x86，稳定性不受影响；
#   * 携程正常启动（CtripHomeActivity 在前台），logcat 无
#     UnsatisfiedLinkError / FATAL / SIGSEGV。
#
# 这比「全局改 ro.product.cpu.abi」好得多，也比改 /system/build.prop 可靠
# （build.prop 在只读基础镜像上改了也会被启动流程覆盖）。而且**只影响我们
# 关心的几个包**，不碰系统。
ABI_SELECT = "/system/etc/mumu-configs/abi-select-android12.config"

# 票务 App 包名 → 统一正则（表里用的是"包名正则 + 目标 ABI + 注释"）
TICKET_APPS = {
    "ctrip.android.view": r"ctrip\.android\.view",
    "com.taobao.trip": r"com\.taobao\.trip",
    "com.Qunar": r"com\.Qunar",
    "com.tongcheng.android": r"com\.tongcheng\.android",
    "cn.suanya.zhixing": r"cn\.suanya\.zhixing",
}

_ABI_BLOCK_MARK = "# 票务 App：按 arm64-v8a 启动"


def read_abi_select(dev, apps=None) -> dict:
    """读 abi-select 表：``{"path", "exists", "lines", "apps": {pkg: abi}}``。

    表里一行形如 ``ctrip\\.android\\.view   arm64-v8a   # 携程``——
    **第一列本身就是一条正则**（带反斜杠转义），不是裸包名。所以这里把
    每一行的第一列当"原文"取出，再用它去比对 ``TICKET_APPS`` 里的包名：
    把两边都去掉转义后比较，避免"用包名去匹配转义文本"这种必失败的写法。
    ``apps`` 可传自定义映射（包名→正则），否则只认票务包。
    """
    out = {"path": ABI_SELECT, "exists": False, "lines": [], "apps": {}}
    raw = _text(_call(dev, "shell", "cat", ABI_SELECT))
    if not raw.strip():
        return out
    out["exists"] = True
    out["lines"] = raw.splitlines()

    def _unesc(s: str) -> str:
        return str(s or "").replace("\\", "").strip()

    want = {_unesc(p): p for p in (apps or TICKET_APPS)}
    for ln in out["lines"]:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        cols = s.split()
        if len(cols) < 2:
            continue
        pat, abi = cols[0], cols[1]
        if abi not in ("arm64-v8a", "armeabi-v7a", "arm", "x86", "x86_64"):
            continue
        key = _unesc(pat)
        if key in want:
            out["apps"][want[key]] = abi
    return out


def set_app_abi(dev, apps=None, abi: str = "arm64-v8a", *,
                logger=None) -> dict:
    """把票务 App 写进 abi-select 表（幂等：已有则跳过）。

    需要 ``/system`` 可写（见 ``unlock_system_disk``），并且**重启实例**才生效。
    写前先把原表备份到 ``/data/local/tmp/abi-select.orig``。
    """
    apps = dict(apps or TICKET_APPS)
    rep = {"ok": False, "path": ABI_SELECT, "added": [], "present": [],
           "abi": abi, "backup": "", "restart_required": True, "error": ""}
    cur = read_abi_select(dev, apps=apps)
    if not cur["exists"]:
        rep["error"] = "找不到 abi-select 表（这台实例可能不是 MuMu？）"
        return rep

    todo = [p for p in apps if p not in cur["apps"]]
    rep["present"] = [p for p in apps if p in cur["apps"]]
    if not todo:
        rep["ok"] = True
        rep["restart_required"] = False
        return rep

    # 备份
    bak = "/data/local/tmp/abi-select.orig"
    if not _text(_call(dev, "shell", "ls", bak)).strip():
        _call(dev, "shell", "cp", "-f", ABI_SELECT, bak)
    rep["backup"] = bak

    _call(dev, "shell", "mount", "-o", "rw,remount", "/")
    block = ["", "############################################",
             _ABI_BLOCK_MARK]
    for pkg in todo:
        block.append("%-48s %-18s # %s"
                     % (apps[pkg], abi, pkg.split(".")[-1]))
    payload = "\n".join(block) + "\n"
    # 用 printf 追加（避免 heredoc 在不同 shell 上的差异）
    out = _text(_call(dev, "shell", "sh", "-c",
                      "printf %s >> %s && echo TM_OK"
                      % (_shq(payload), ABI_SELECT)))
    if "TM_OK" not in out:
        rep["error"] = "追加失败：%s" % (out.strip()[:120] or "无输出")
        return rep

    after = read_abi_select(dev, apps=apps)
    rep["added"] = [p for p in todo if p in after["apps"]]
    rep["ok"] = bool(rep["added"])
    if logger and rep["ok"]:
        logger.info("[android] 已写入 %d 个 App 的 ABI=%s（重启实例生效）",
                    len(rep["added"]), abi)
    return rep


def revert_app_abi(dev, *, logger=None) -> dict:
    """从备份还原 abi-select 表（回滚用）。"""
    bak = "/data/local/tmp/abi-select.orig"
    rep = {"ok": False, "path": ABI_SELECT, "backup": bak}
    if not _text(_call(dev, "shell", "ls", bak)).strip():
        rep["error"] = "没有备份可还原"
        return rep
    _call(dev, "shell", "mount", "-o", "rw,remount", "/")
    out = _text(_call(dev, "shell", "sh", "-c",
                      "cp -f %s %s && echo TM_OK" % (bak, ABI_SELECT)))
    rep["ok"] = "TM_OK" in out
    if logger and rep["ok"]:
        logger.info("[android] abi-select 已还原（重启实例生效）")
    return rep


def _shq(s: str) -> str:
    """单引号包裹给设备端 sh（内部单引号转义）。"""
    return "'" + str(s).replace("'", "'\\''") + "'"
