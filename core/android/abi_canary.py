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

from .fingerprint import _call, _text, as_root, boot_id

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
    """写一组 props（有 Magisk 用 resetprop，否则 setprop）。返回逐键结果。"""
    from .fingerprint import _magisk, _q

    rp = _magisk(dev) if use_root else ""
    lines = []
    for k, v in mapping.items():
        if rp:
            cmd = "%s -n %s %s" % (rp, _q(k), _q(v))
        else:
            cmd = "setprop %s %s" % (_q(k), _q(v))
        lines.append("%s >/dev/null 2>&1 && echo 'OK %s' || echo 'FAIL %s'"
                     % (cmd, k, k))
    out = _text(as_root(dev, "; ".join(lines) or "true"))
    rep = {"applied": [], "failed": [], "resetprop": rp}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("OK "):
            rep["applied"].append(s[3:].strip())
        elif s.startswith("FAIL "):
            rep["failed"].append(s[5:].strip())
    return rep


def _logcat_tail(dev, n: int = 400) -> str:
    return _text(_call(dev, "shell", "logcat", "-d", "-t", str(int(n)),
                       timeout=30))


def probe(dev, pkg: str, wait_s: int = 30) -> dict:
    """判据：前台回到 ``pkg`` + UI 树非空 + logcat 无崩溃特征。"""
    rep = {"ok": False, "activity": "", "nodes": 0, "errors": []}
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
    rep["errors"] = [m for m in CRASH_MARKS if m in log]
    rep["ok"] = (rep["activity"].split("/")[0].strip() == pkg
                 and rep["nodes"] >= 6 and not rep["errors"])
    if not rep["ok"] and log:
        # 留证据：只截崩溃行附近 300 字符，别把整个 logcat 写进报告
        idx = min([log.find(m) for m in rep["errors"] if log.find(m) >= 0]
                  or [0])
        rep["log_excerpt"] = log[max(0, idx - 80):idx + 220].replace("\n", " | ")
    return rep


def _verdict_path(user_data_dir: str) -> str:
    return os.path.join(str(user_data_dir or "user_data"), "device",
                        VERDICT_FILE)


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
           "error": ""}
    try:
        rep["before"] = snapshot(dev)
        if dry_run:
            rep["ok"] = True
            rep["verdict"] = spoof_allowed(pkg, user_data_dir)
            return rep

        from .fingerprint import restart_framework

        ap = apply_props(dev, ABI_ARM)
        rep["apply"] = ap
        if not ap.get("applied"):
            rep["error"] = "props 写不进去（无 root / 无 Magisk）"
            return rep
        boot = boot_id(dev)
        restart_framework(dev, "zygote", wait_s=restart_wait_s)

        rep["probe"] = probe(dev, pkg, wait_s=wait_s)
        rep["ok"] = bool(rep["probe"].get("ok"))
    except Exception as e:                      # 任何异常都不许跳过恢复
        rep["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        try:
            if not dry_run and rep.get("apply", {}).get("applied"):
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
                rep["restored"] = bool(restore.get("applied"))
                rep["after"] = snapshot(dev)
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
