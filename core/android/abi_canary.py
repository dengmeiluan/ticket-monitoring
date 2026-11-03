# -*- coding: utf-8 -*-
"""ABI 伪装的可行性验证（canary）：先证明不炸，再决定要不要长期开。

为什么不能直接改
----------------
MuMu 的系统是 ``x86_64 + ARM 转译层``。把 ``ro.product.cpu.abi`` 改成
``arm64-v8a`` 之后，**PackageManager 会按 arm64 去选 native so**：

* 纯 Java 的 App：没事，反而更像真机；
* 带加固 so 的 App（携程、去哪儿都有）：可能走进转译层不支持的指令，
  仓库里已经吃过一次 —— 主线程 Blocked 在 ``Runtime.load0``，ANR 120s+，
  点「等待」186s 也不恢复（见 ``core/android/snapshot.py`` 的 SNAPSHOT_EXCLUDES
  注释：动态 so 与 ABI 绑定，写回不匹配的 so 会死锁）。

所以这条不能靠"看文档猜"，只能**在具体实例 + 具体包上实测**。本模块就是那台
实测装置：

```
snapshot  →  apply(arm64)  →  restart framework  →  probe(pkg)
          →  restore(x86_64) →  restart framework  →  落盘判定
```

三条安全性质（比"能不能改"更重要）
--------------------------------
1. **无论 probe 成功、失败还是抛异常，restore 一定执行**（``try/finally``）；
2. probe 判据不是"能启动"，而是**三件事同时成立**：前台回到目标包、
   UI 树非空白、logcat 无 ``UnsatisfiedLinkError``/``FATAL``/``SIGSEGV``/``ANR``；
3. 判定落盘 ``user_data/device/abi_canary.json``，**只有判定 ok 才允许
   ``identity`` 长期写 ABI**；判定有 7 天有效期，过期要重测（App 升级后
   会换 so，昨天的结论不作数）。

对外接口
--------
``run(dev, pkg, ...)``     执行一次实验，返回报告
``verdict(...)``           读已落盘判定
``spoof_allowed(...)``     给 ``fingerprint`` 用：能不能长期写 ABI
``ABI_ARM`` / ``ABI_X86``  两组目标值（``restore`` 用 x86 组）
"""
from __future__ import annotations

import json
import os
import time

from .fingerprint import _call, _text, as_root, boot_id, props_of

VERDICT_FILE = "abi_canary.json"
VERDICT_TTL_S = 7 * 86400
LOG_TMP = "/data/local/tmp/tm_abi_canary.log"

# arm64 一组（模拟真机）
ABI_ARM = {
    "ro.product.cpu.abi": "arm64-v8a",
    "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a,armeabi",
    "ro.product.cpu.abilist32": "armeabi-v7a,armeabi",
    "ro.product.cpu.abilist64": "arm64-v8a",
    "ro.dalvik.vm.isa.arm64": "arm64",
    "ro.dalvik.vm.isa.arm": "arm",
}

# x86 一组（恢复用；MuMu 的出厂值）
ABI_X86 = {
    "ro.product.cpu.abi": "x86_64",
    "ro.product.cpu.abilist": "x86_64,x86,arm64-v8a,armeabi-v7a,armeabi",
    "ro.product.cpu.abilist32": "x86,armeabi-v7a,armeabi",
    "ro.product.cpu.abilist64": "x86_64,arm64-v8a",
    "ro.dalvik.vm.isa.arm64": "arm64",
    "ro.dalvik.vm.isa.arm": "arm",
}

# probe 的崩溃特征（logcat）
CRASH_MARKS = (
    "UnsatisfiedLinkError",
    "dlopen failed",
    "FATAL EXCEPTION",
    "SIGSEGV",
    "SIGILL",
    "ANR in ",
    "force-finishing",
)


def _props(dev, keys) -> dict:
    out = {}
    for k in keys:
        out[k] = _text(_call(dev, "shell", "getprop", k)).strip()
    return out


def snapshot(dev) -> dict:
    """当前 ABI 相关 props（原值，用于恢复）。"""
    return _props(dev, list(ABI_X86.keys()))


def apply_props(dev, mapping: dict, *, use_root=True) -> dict:
    """写一组 props 并**读回校验**。返回逐键结果。

    为什么必须读回：``setprop`` 对只读的 ``ro.*`` **返回码是 0 但值不变**
    （2026-11-03 实测：这台 MuMu 没有 Magisk，``setprop ro.product.cpu.abi
    arm64-v8a`` 静默无效）。用返回码判成功会得出「写进去了」的假结论——而
    canary 的整个安全性都建立在「我改了什么、有没有恢复」上，误报一次就等于
    把结论和恢复都判错。所以这里写完后逐个 ``getprop`` 比对真实值。

    返回 ``{"applied": [...], "verified": [...], "failed": [...],
    "mismatch": {k: (want, got)}, "resetprop": path}``。
    applied=命令报成功；verified=读回真的是新值（**只有 verified 才可信**）。
    """
    from .fingerprint import _magisk, _q

    rp = _magisk(dev) if use_root else ""
    # **写前**先读一次原值：只有「原值≠目标 且 写后=目标」才算真的写成功。
    # 少了这一步会出一类致命假阳性：某些键（如 ro.dalvik.vm.isa.arm64）
    # 本来就已经是目标值，命令根本没生效、读回也对得上——于是被判成
    # "写入成功"（2026-11-03 在无 Magisk 的 MuMu 上就是这么被骗的）。
    before = _props(dev, list(mapping.keys()))

    lines = []
    for k, v in mapping.items():
        if rp:
            cmd = "%s -n %s %s" % (rp, _q(k), _q(v))
        else:
            cmd = "setprop %s %s" % (_q(k), _q(v))
        lines.append("%s >/dev/null 2>&1 && echo 'OK %s' || echo 'FAIL %s'"
                     % (cmd, k, k))
    out = _text(as_root(dev, "; ".join(lines) or "true"))
    rep = {"applied": [], "verified": [], "failed": [], "mismatch": {},
           "unchanged": [], "resetprop": rp}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("OK "):
            rep["applied"].append(s[3:].strip())
        elif s.startswith("FAIL "):
            rep["failed"].append(s[5:].strip())

    # 写后读回校验
    actual = props_of(dev)
    for k, v in mapping.items():
        want = str(v).strip()
        got = actual.get(k)
        if got is None:
            continue                     # 读不到就不下结论
        got = str(got).strip()
        if got != want:
            rep["mismatch"][k] = (want, got)
            if k in rep["applied"]:
                rep["applied"].remove(k)
            continue
        if str(before.get(k) or "").strip() == want:
            # 本来就是目标值：不算"写成功"，单独记（它不构成可行性证据）
            rep["unchanged"].append(k)
            if k in rep["applied"]:
                rep["applied"].remove(k)
            continue
        rep["verified"].append(k)        # 真的从原值变成了目标值
    return rep


def _logcat_tail(dev, n: int = 400) -> str:
    return _text(_call(dev, "shell", "logcat", "-d", "-t", str(int(n)),
                       timeout=30))


def probe(dev, pkg: str, wait_s: int = 30) -> dict:
    """判据：前台回到 ``pkg`` + UI 树非空 + logcat 无**属于该包**的崩溃。

    为什么崩溃要限定包名：``stop; start`` 重启框架时，系统服务被杀的
    SIGSEGV/SIGKILL 会留在 logcat 里。不限定包名会把「重启自己的噪声」判成
    「App 崩了」——2026-11-03 实测就踩了这条假阳性（probe 报 SIGSEGV，
    但设备上 ABI 根本没变、App 也没启动过）。
    """
    rep = {"ok": False, "activity": "", "nodes": 0, "errors": [],
           "foreign_crashes": 0}
    if not pkg:
        rep["errors"].append("no package")
        return rep
    _call(dev, "shell", "logcat", "-c")          # 清屏，只看本次启动
    _call(dev, "shell", "am", "force-stop", pkg)
    time.sleep(1.0)
    _call(dev, "shell", "monkey", "-p", pkg, "-c",
          "android.intent.category.LAUNCHER", "1", timeout=60)
    end = time.time() + max(10, int(wait_s))
    xml = ""
    while time.time() < end:
        time.sleep(2.0)
        try:
            act = str(dev.current_activity() or "")
        except Exception:
            act = ""
        rep["activity"] = act
        if act.split("/")[0].strip() == pkg:
            xml = dev.dump() or ""
            if xml.count("<node") >= 6:
                break
    rep["nodes"] = xml.count("<node")
    log = _logcat_tail(dev)
    # 只认**属于该包**的崩溃：行里要同时出现崩溃特征与包名（或进程名）。
    # 框架重启留下的是 system_server/zygote 的 SIGSEGV，与本包无关。
    mine, foreign = [], 0
    for line in log.splitlines():
        if not any(m in line for m in CRASH_MARKS):
            continue
        if pkg in line or ("Process: " in line and pkg in line):
            mine.append(next(m for m in CRASH_MARKS if m in line))
        else:
            foreign += 1
    rep["errors"] = sorted(set(mine))
    rep["foreign_crashes"] = foreign
    rep["ok"] = (rep["activity"].split("/")[0].strip() == pkg
                 and rep["nodes"] >= 6 and not rep["errors"])
    if not rep["ok"] and log:
        # 留证据：只截崩溃行附近 300 字符，别把整个 logcat 写进报告
        needle = rep["errors"][0] if rep["errors"] else pkg
        idx = max(0, log.find(needle))
        rep["log_excerpt"] = log[max(0, idx - 80):idx + 220].replace("\n", " | ")
    return rep


def _verdict_path(user_data_dir: str) -> str:
    return os.path.join(str(user_data_dir or "user_data"), "device",
                        VERDICT_FILE)


# ---------------------------------------------------------------------------
# 只读预检：不动设备就能判断「改了会不会炸」
# ---------------------------------------------------------------------------
# 关键事实（2026-11-03 实测 MuMu 实例 0，Android 15）：
#   ro.product.cpu.abi   = x86_64          ← 风控读 Build.CPU_ABI 看的就是它
#   ro.product.cpu.abilist64 = x86_64,arm64-v8a
#   ro.dalvik.vm.native.bridge = libnb.so  ← MuMu 自带 ARM 转译
#   而 5 个目标包 primaryCpuAbi **全部是 arm64-v8a**（它们本来就是 arm64 包）
#
# 这条实测决定了风险模型：**so 选择看的是 primaryCpuAbi（已定），不是
# ro.product.cpu.abi**。所以对"本来就是 arm64 包"的 app，改这个 prop 不会
# 让 PackageManager 改选 so —— 历史那次 ANR 的前提（x86 包 + 改成 arm64）
# 在当前配置下不成立。
#
# 反过来：如果某个包 primaryCpuAbi 还是 x86_64，改 prop 就真会让它去加载
# arm64 so，风险高——预检会直接判 high 并建议先重装成 arm64 包。
_PREFLIGHT_GOOD = "low"
_PREFLIGHT_MID = "medium"
_PREFLIGHT_BAD = "high"
_PREFLIGHT_STOP = "blocked"


def mumu_capabilities(manager=None) -> dict:
    """读 MuMu 宿主机侧的**官方能力**（不需要 root、不需要 Magisk）。

    2026-11-03 用 ``MuMuManager.exe setting -v 0 --all`` 枚举出来的关键项：

    ==========================  ================================================
    键                            含义 / 实测值
    ==========================  ================================================
    ``system_disk_readonly``    **系统盘只读开关**，实测 ``true``——这就是 ABI
                                改不动的根因；改成 ``false`` 后重启实例，
                                ``mount -o remount,rw /`` 才可能成功
    ``root_permission``         MuMu 自带 root（实测 ``true``，但只给 adb root，
                                不提供 ``resetprop``）
    ``phone_brand`` / ``phone_model`` / ``phone_miit`` / ``phone_imei``
                                **官方机型伪装**（实测 Samsung / Galaxy A52 5G /
                                SM-A5260，与 ``ro.product.model`` 一致）——
                                比改 props 更稳、可持久化、还不用 root
    ``resolution_width/height`` + ``resolution_dpi``
                                **官方分辨率/DPI**（实测 1600×900 / 240）
    ==========================  ================================================

    结论：**机型和分辨率这两件事根本不需要走 props 那条路**，MuMu 自己就提供
    了正式接口；只有 ABI 必须靠系统盘可写或 Magisk。
    """
    out = {"available": False, "raw": {}, "keys": {}}
    mgr = manager
    try:
        if mgr is None:
            from .config import resolve_install_dir, normalize
            from .mumu import MuMuManager
            cfg = normalize(None)
            mgr = MuMuManager(install_dir=resolve_install_dir(cfg) or "",
                              vm_index=0)
        if not mgr.available():
            out["note"] = "MuMuManager 不可用"
            return out
        info = mgr._call_json(["setting", "-v", str(mgr.vm_index), "--all"])
        if not isinstance(info, dict):
            out["note"] = "setting --all 无输出"
            return out
        out["available"] = True
        out["raw"] = info
        for k in ("system_disk_readonly", "root_permission",
                  "phone_brand", "phone_model", "phone_miit", "phone_imei",
                  "resolution_width", "resolution_height", "resolution_dpi",
                  "resolution_mode"):
            if k in info:
                out["keys"][k] = info[k]
        out["system_writable"] = str(
            info.get("system_disk_readonly", "true")).lower() == "false"
        return out
    except Exception as e:
        out["note"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        return out


def capabilities(dev) -> dict:
    """探测「这台实例到底能不能改 ro.*」——四条路各测一次，全部只读。

    2026-11-03 在 MuMu（Android 15，无 Magisk）实测：

    ==============  ==========================================  ================
    路径             探测方法                                    结果
    ==============  ==========================================  ================
    ``resetprop``   ``command -v resetprop``                    无（无 Magisk）
    ``setprop``     写 ro.* 后读回                               不变（**返回 0 静默无效**）
    ``remount rw``  ``mount -o remount,rw /`` + ``touch``      ``'…sda6' is read-only``
    ``blockdev``    ``blockdev --setrw`` + ``--getro``           仍为 1（**同样静默无效**）
    ==============  ==========================================  ================

    三层根因（一层比一层深）：

    1. **Android props 层**：``ro.*`` 只读，``setprop`` 返回 0 但不生效；
    2. **Android 块设备层**：``/dev/block/sda6`` 的 ro 标志清不掉；
    3. **VirtualBox 设备层**：实例配置 ``vms/<实例>/<实例>.nemu`` 里
       ``system.vdi`` 的 ``type="Readonly"`` —— 系统盘以**只读**方式挂给
       虚拟机，这是最底层根因。

    这些结论只说明一件事：**全局改 `ro.*` 这条路堵着**。但 ABI 伪装不需要
    走它——MuMu 有官方的 per-app ABI 表
    （``/system/etc/mumu-configs/abi-select-android12.config``），
    按包名决定用哪套 ABI 启动，已实测跑通，入口在
    ``core/android/vendor.py::set_app_abi``。

    所以本函数现在的定位是：**给"想全局改 ro.*"的人做能力探测**，
    免得每次重新试一遍、也免得把"命令返回 0"误当成"改成功了"。
    """
    from .fingerprint import _magisk

    rep = {"resetprop": "", "setprop_ro": False, "remount_rw": False,
           "can_write_ro": False, "note": ""}
    try:
        rep["resetprop"] = _magisk(dev) or ""
    except Exception:
        pass
    # remount 探测（可逆：改 rw 试 touch，无论结果都改回 ro）
    try:
        out = _text(_call(dev, "shell", "sh", "-c",
                          "mount -o remount,rw / 2>&1; touch /system/.tm_cap "
                          "2>&1 && { rm -f /system/.tm_cap; echo TM_RW_OK; } "
                          "|| echo TM_RW_FAIL; mount -o remount,ro / "
                          "2>/dev/null; true"))
        rep["remount_rw"] = "TM_RW_OK" in out
        if "read-only" in out.lower():
            rep["note"] = "块设备只读（remount 被拒）"
    except Exception:
        pass
    rep["can_write_ro"] = bool(rep["resetprop"]) or rep["remount_rw"]
    # blockdev 只读标志：能清掉的话 remount 才有戏（实测清不掉，返回 0 但 ro 仍 1）
    try:
        out = _text(_call(
            dev, "shell", "sh", "-c",
            "blockdev --getro /dev/block/sda6 2>/dev/null || echo NA; "
            "blockdev --setrw /dev/block/sda6 2>/dev/null; "
            "blockdev --getro /dev/block/sda6 2>/dev/null || echo NA"))
        vals = [x.strip() for x in out.splitlines() if x.strip()]
        rep["blockdev_ro_before"] = vals[0] if vals else ""
        rep["blockdev_ro_after"] = vals[-1] if len(vals) > 1 else ""
        if rep["blockdev_ro_after"] == "1" and not rep["remount_rw"]:
            rep["note"] = ("块设备只读标志清不掉（blockdev --setrw 返回 0 但 ro 仍 1）；"
                           "根因是系统盘以只读方式挂给虚拟机（system.vdi type=Readonly）")
    except Exception:
        pass
    if not rep["can_write_ro"] and not rep["note"]:
        rep["note"] = "无可用的 ro.* 写入通道（无 Magisk 且不能 remount）"
    return rep


def preflight(dev, packages=None) -> dict:
    """只读预检：判断「在这台实例上改 ABI」有多危险。**不动任何设置**。

    返回::

        {"ok": bool, "risk": "low|medium|high|blocked", "why": "...",
         "props": {...}, "packages": {pkg: {"primary":..., "secondary":...}}}

    判定规则（全部来自实测事实，不猜）：

    * ``abilist`` 里没有 ``arm64-v8a`` → ``blocked``（系统根本没有 arm 运行时，
      写进去必然崩）；
    * 所有目标包 ``primaryCpuAbi == arm64-v8a`` → ``low``（so 选择已定，
      改 prop 只影响风控读到的 ``Build.CPU_ABI``）；
    * 部分包是 arm64 → ``medium``；
    * 全部不是 arm64 → ``high``（改 prop 会真的改选 so）。
    """
    import re

    rep = {"ok": False, "risk": _PREFLIGHT_STOP, "why": "", "props": {},
           "packages": {}, "capabilities": {}}
    props = {
        "abi": _text(_call(dev, "shell", "getprop",
                           "ro.product.cpu.abi")).strip(),
        "abilist": _text(_call(dev, "shell", "getprop",
                               "ro.product.cpu.abilist")).strip(),
        "abilist64": _text(_call(dev, "shell", "getprop",
                                 "ro.product.cpu.abilist64")).strip(),
        "abilist32": _text(_call(dev, "shell", "getprop",
                                 "ro.product.cpu.abilist32")).strip(),
        "native_bridge": _text(_call(dev, "shell", "getprop",
                                     "ro.dalvik.vm.native.bridge")).strip(),
    }
    rep["props"] = props
    rep["capabilities"] = capabilities(dev)

    pkgs = [str(p) for p in (packages or []) if p]
    if not pkgs:
        from .stealth import KNOWN_APPS
        pkgs = list(KNOWN_APPS.values())

    for pkg in pkgs:
        d = _text(_call(dev, "shell", "dumpsys", "package", pkg))
        m = re.search(r"primaryCpuAbi=(\S+)", d)
        s = re.search(r"secondaryCpuAbi=(\S+)", d)
        rep["packages"][pkg] = {
            "installed": bool(d.strip()) and "Unable to find package" not in d,
            "primary": (m.group(1) if m else ""),
            "secondary": (s.group(1) if s else ""),
        }

    # 第一道闸：这台机器能不能**全局**改 ro.*（2026-11-03 的 MuMu 三条路全堵）
    # 放在包探测之后：报告要能一次把「机器什么样」+「包什么样」都摆出来，
    # 操作员才知道是「机器不支持」还是「包的 so 不匹配」。
    if not (rep.get("capabilities") or {}).get("can_write_ro"):
        rep["risk"] = _PREFLIGHT_STOP
        # 这里**只给静态提示**，不去 shell 调 MuMuManager：那是宿主机 GUI 进程，
        # 采集进行中会阻塞几十秒甚至更久（实测把一批单测拖到 42 分钟）。
        # 宿主能力由 CLI（scripts/abi_preflight.py）单独查、单独展示。
        rep["why"] = (
            "这台实例改不了**全局** ro.*：%s。\n"
            "但 ABI 伪装不必走这条路——用 MuMu 官方 per-app 表即可（已实测跑通）：\n"
            "  vendor.read_abi_select(dev) / vendor.set_app_abi(dev)  # 写 5 个票务包\n"
            "  前置：MuMuManager.exe setting -v <实例> -k system_disk_readonly -val false\n"
            "        MuMuManager.exe control -v <实例> restart\n"
            "（若确实要全局改 ro.*，则需装 Magisk 提供 resetprop。）"
            % (rep["capabilities"].get("note") or "无写入通道"))
        return rep

    blob = ",".join([props["abilist"], props["abilist64"],
                     props["abilist32"]])
    if "arm64-v8a" not in blob:
        rep["why"] = ("系统 abilist 里没有 arm64-v8a（native_bridge=%s）；"
                      "写 arm64 必然崩" % (props["native_bridge"] or "无"))
        return rep

    found = [r for r in rep["packages"].values() if r["installed"]]
    if not found:
        rep["why"] = "没有已安装的目标包可判（先装 App 再预检）"
        return rep

    arm = [r for r in found if r["primary"] == "arm64-v8a"]
    if len(arm) == len(found):
        rep["risk"] = _PREFLIGHT_GOOD
        rep["why"] = ("全部 %d 个目标包已是 arm64-v8a 主 ABI：so 选择已定，"
                      "改 ro.product.cpu.abi 只影响风控读到的 Build.CPU_ABI"
                      % len(found))
    elif arm:
        rep["risk"] = _PREFLIGHT_MID
        rep["why"] = ("%d/%d 个包是 arm64 主 ABI，其余仍按 x86 选 so——"
                      "只对 arm64 那些包可以改" % (len(arm), len(found)))
    else:
        rep["risk"] = _PREFLIGHT_BAD
        rep["why"] = ("目标包仍按 x86_64 选 so：此时改 ABI 会让 PM 改选 arm64，"
                      "可能崩（先重装成 arm64 包，或别改）")
    rep["ok"] = rep["risk"] in (_PREFLIGHT_GOOD, _PREFLIGHT_MID)
    return rep


def verdict(user_data_dir: str = "user_data") -> dict:
    """读已落盘判定：``{pkg: {ok, at, boot, errors, nodes}}``。"""
    try:
        with open(_verdict_path(user_data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def spoof_allowed(pkg: str, user_data_dir: str = "user_data",
                  now: float = None, ttl_s: int = VERDICT_TTL_S) -> bool:
    """这个包能不能长期用 arm64 伪装：**必须有过 ok 判定且没过期**。

    没有判定 = 不允许（保守）。过期 = 不允许（App 升级可能换 so）。
    """
    ts = float(now if now is not None else time.time())
    rec = (verdict(user_data_dir) or {}).get(str(pkg))
    if not isinstance(rec, dict) or not rec.get("ok"):
        return False
    at = float(rec.get("at") or 0)
    return bool(at) and (ts - at) <= int(ttl_s)


def run(dev, pkg: str, config: dict = None, logger=None, *,
        user_data_dir: str = "user_data", wait_s: int = 30,
        restart_wait_s: int = 90, dry_run: bool = False) -> dict:
    """跑一次 canary：改 arm64 → 重启框架 → 探活 → **必定恢复** → 落盘。

    ``dry_run=True`` 只做 snapshot + 判定读取，不动设备（给面板预览用）。
    ``restart_wait_s`` 是框架重启后等 `sys.boot_completed` 的上限——单测把它
    调小，否则一次实验要白等 3 分钟（两次重启 × 90s）。
    """
    rep = {"ok": False, "dry_run": bool(dry_run), "pkg": str(pkg),
           "before": {}, "after": {}, "probe": {}, "restored": False,
           "restore_verified": False, "error": "", "wrote": False}
    try:
        rep["before"] = snapshot(dev)
        # 只读预检先跑：risk=blocked/high 时**一个 prop 都不写**，
        # 直接把结论返回。这条让 canary 自己不会把设备改坏。
        rep["preflight"] = preflight(dev, [pkg] if pkg else None)
        if not rep["preflight"].get("ok") and not dry_run:
            rep["error"] = "预检未通过（%s）：%s" % (
                rep["preflight"].get("risk"), rep["preflight"].get("why"))
            return rep
        if dry_run:
            rep["ok"] = True
            rep["verdict"] = spoof_allowed(pkg, user_data_dir)
            return rep

        from .fingerprint import restart_framework

        ap = apply_props(dev, ABI_ARM)
        rep["apply"] = ap
        rep["wrote"] = bool(ap.get("verified"))
        # **必须是 verified**：``setprop`` 对只读 ro.* 返回 0 但值不变
        # （2026-11-03 实测：无 Magisk 的 MuMu 上"写成功"是假的）。没有一条
        # 读回校验通过就说明这台机器改不了 ABI，直接收工——绝不能拿"命令
        # 报成功"当结论往下跑，否则会得出错误的可行性判定。
        if not rep["wrote"]:
            rep["error"] = ("ABI 写不进去：%d 条命令报成功但 0 条读回生效"
                            "（这台实例缺 Magisk/resetprop，ro.* 只读）"
                            % len(ap.get("applied") or []))
            return rep
        boot = boot_id(dev)
        restart_framework(dev, "zygote", wait_s=restart_wait_s)

        rep["probe"] = probe(dev, pkg, wait_s=wait_s)
        rep["ok"] = bool(rep["probe"].get("ok"))
    except Exception as e:                      # 任何异常都不许跳过恢复
        rep["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        try:
            if not dry_run and rep.get("wrote"):
                # 恢复用**原值**（不硬编码 x86）：万一操作员本来就在 arm 上，
                # 硬写 x86 反而把设备改坏。
                back = {k: v for k, v in (rep.get("before") or {}).items() if v}
                restore = apply_props(dev, back or ABI_X86)
                rep["restore"] = restore
                try:
                    from .fingerprint import restart_framework
                    restart_framework(dev, "zygote", wait_s=restart_wait_s)
                except Exception:
                    pass
                rep["after"] = snapshot(dev)
                # 恢复是否真的成功：**比对读回值**，不看命令返回码
                diff = {k: (rep["before"].get(k), rep["after"].get(k))
                        for k in (rep.get("before") or {})
                        if str(rep["before"].get(k) or "")
                        != str(rep["after"].get(k) or "")}
                rep["restore_diff"] = diff
                rep["restored"] = not diff
                rep["restore_verified"] = bool(restore.get("verified"))
        except Exception as e:
            rep["restore_error"] = str(e)[:160]

    _persist(rep, user_data_dir)
    if logger:
        logger.info("[android] ABI canary %s：%s（restored=%s）", pkg,
                    "通过" if rep.get("ok") else "未通过/已回滚",
                    rep.get("restored"))
    return rep


def _persist(rep: dict, user_data_dir: str) -> None:
    pkg = str(rep.get("pkg") or "")
    if not pkg or rep.get("dry_run"):
        return
    path = _verdict_path(user_data_dir)
    data = verdict(user_data_dir)
    prev = data.get(pkg) if isinstance(data.get(pkg), dict) else {}
    rec = {
        "ok": bool(rep.get("ok")),
        "at": time.time(),
        "boot": "",
        "errors": list((rep.get("probe") or {}).get("errors") or []),
        "nodes": int((rep.get("probe") or {}).get("nodes") or 0),
        "activity": str((rep.get("probe") or {}).get("activity") or "")[:120],
        "restored": bool(rep.get("restored")),
        "tries": int(prev.get("tries") or 0) + 1,
    }
    if rep.get("error"):
        rec["error"] = rep["error"][:160]
    data[pkg] = rec
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        pass
