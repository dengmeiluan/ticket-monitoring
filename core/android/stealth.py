# -*- coding: utf-8 -*-
"""root / 模拟器痕迹隐藏：让 App 看到「一台没 root 的真机」。

和 ``fingerprint`` 的分工
-------------------------
``fingerprint`` 管**身份**（我是谁：机型、序列号、android_id）。
本模块管**负面证据**（我不是什么：没 root、没调试、不是模拟器）。
两者写的是同一批 props，但判定维度不同，所以分开维护、各自可单独关。

为什么这层直接决定「能不能登录」
--------------------------------
携程 App 的登录风控（阿里聚安全 baxia / 自研设备指纹）在提交登录请求前
先做本地环境判定：``ro.debuggable=1``、能 ``su``、``/data/adb/magisk``
可读、``ro.kernel.qemu=1`` 任一命中就直接降档——表现是「验证码收不到」、
「登录失败请稍后重试」、「账号存在安全风险」。这类失败与请求频率无关，
降速无效、换 IP 无效，只有把环境证据清掉才有用。

MuMu 的出厂状态恰好把这些全踩了：``adb root`` 默认可用（``ro.debuggable=1``
``ro.secure=0``），部分版本带 ``su``。而**我们自己的采集又必须用 root**
（快照要读 ``/data/data``）——所以策略不是「不要 root」，而是
「root 只对我们可见，对 App 不可见」。

能改与改不动（不撒谎，写清楚）
----------------------------
* 能改：props（``resetprop``）、Magisk DenyList（对本机几个包隐藏 root）、
  Magisk 管理器包、开发者选项开关、App 可读的 su 路径（DenyList 后不可见）。
* **要先验证才能改**：ABI（x86_64 → arm64-v8a）。本模块不写它；
  入口在 ``abi_canary.run()``（带自动回滚），判定 ok 后由
  ``hardening`` 的 ABI 闸门写。
* 改不动：Play Integrity / SafetyNet 的设备认证（需要真机 TEE）、
  传感器数量、内核版本字符串。这些留在 ``detect()`` 的 ``unfixable`` 里，
  让操作员知道「还剩什么」，而不是以为已经干净。

失败一律 fail-soft：没有 Magisk、没有 root、设备掉线，都只让报告变短，
绝不抛异常、绝不中断采集。
"""
from __future__ import annotations

import time

from .fingerprint import _call, _text, as_root, props_of, _root, _magisk, _q

# 渠道 → 包名（与 crawlers/app_*.py 的 `_APP_PKG` 一致；这里不复用是为
# 了让本模块可以脱开 crawlers 单测）
KNOWN_APPS = {
    "ctrip": "ctrip.android.view",
    "fliggy": "com.taobao.trip",
    "qunar": "com.Qunar",
    "tongcheng": "com.tongcheng.android",
    "zhixing": "cn.suanya.zhixing",
    "tuniu": "com.tuniu.app",
}

# root 相关 props：目标值。这些是「App 本地判定」的直接输入。
ROOT_PROPS = {
    "ro.debuggable": "0",
    "ro.secure": "1",
    "ro.adb.secure": "1",
    "service.adb.root": "0",
    "ro.build.tags": "release-keys",
    "ro.build.type": "user",
    # 完整性相关的 boot 状态（部分风控 SDK 会读）
    "ro.boot.verifiedbootstate": "green",
    "ro.boot.flash.locked": "1",
    "ro.boot.veritymode": "enforcing",
    "ro.boot.warranty_bit": "0",
    "ro.warranty_bit": "0",
    "ro.boot.secureboot": "1",
    "ro.boot.vbmeta.device_state": "locked",
}

# 模拟器厂商自己的 props：存在本身即证据，直接删掉
EMU_PROP_PAT = ("mumu", "netease", "nemu", "vbox", "goldfish", "qemu",
                "bluestacks", "ldplayer", "noxtn")

# 本层不处理的残留（如实报告，不要假装清掉了）
UNFIXABLE = (
    ("play_integrity", "Play Integrity / SafetyNet 需要真机 TEE，任何模拟器都过不了"),
    # ABI 已经能改了，但**不归本层**：走 MuMu 官方 per-app 表
    # （core/android/vendor.py::set_app_abi），改完重启实例生效。
    ("abi", "ABI 走 MuMu 官方 abi-select 表（vendor.set_app_abi），本层不碰"),
    ("sensors", "传感器数量/类型来自 HAL，props 改不了"),
    ("kernel", "内核版本字符串来自真实内核"),
)

# 记录「本 boot 周期已处理过」的标记，避免每轮都跑一遍 denylist 检查
_MARK = "/data/local/tmp/tm_stealth_%d.ok"


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------
def detect(dev) -> dict:
    """采集当前设备的 root / 模拟器证据（只读，不改任何东西）。

    返回 ``{"root": [...], "emulator": [...], "magisk": {...},
    "unfixable": [...], "score": int}``。``score`` 100 = 已知证据全清。
    """
    rep = {"root": [], "emulator": [], "magisk": {}, "unfixable": [],
           "score": 0, "debuggable": False}
    props = props_of(dev)
    if not props:
        rep["error"] = "device offline"
        return rep

    # --- props 层 ---
    for k, needle in (("ro.debuggable", "1"), ("ro.secure", "0"),
                      ("ro.adb.secure", "0"), ("service.adb.root", "1"),
                      ("ro.build.tags", "test-keys"), ("ro.build.type", "eng"),
                      ("ro.build.type", "userdebug")):
        if needle in str(props.get(k, "")).lower():
            rep["root"].append("prop:%s=%s" % (k, props.get(k)))
    rep["debuggable"] = "1" in str(props.get("ro.debuggable", ""))

    for k, needle in (("ro.kernel.qemu", "1"), ("ro.hardware", "goldfish"),
                      ("ro.hardware", "ranchu"), ("ro.product.model", "sdk_"),
                      ("ro.product.brand", "generic"),
                      ("ro.build.fingerprint", "generic")):
        if needle.lower() in str(props.get(k, "")).lower():
            rep["emulator"].append("prop:%s=%s" % (k, props.get(k)))
    blob = " ".join("%s=%s" % (k, v) for k, v in props.items()
                    if any(p in k.lower() for p in EMU_PROP_PAT))
    if blob.strip():
        rep["emulator"].append("props:%s" % blob[:200])

    # --- 文件系统层（与 props 独立，props 干净也可能命中）---
    fs = _text(_call(dev, "shell", "sh", "-c",
                     "ls /system/bin/su /system/xbin/su /sbin/su "
                     "/system/app/Superuser.apk /data/adb/magisk "
                     "/dev/qemu_pipe 2>/dev/null || true"))
    for line in fs.splitlines():
        p = line.strip()
        if p:
            (rep["emulator"] if "qemu_pipe" in p else rep["root"]).append(
                "fs:%s" % p)
    # 模拟器厂商的共享目录：App 一个 File.exists() 就能判定，props 改不掉。
    # MuMu 的 /mnt/shared 与 /sdcard/MuMuSharedFolder 是默认存在的一对。
    shared = _text(_call(
        dev, "shell", "sh", "-c",
        "ls -d /mnt/shared /sdcard/MuMuSharedFolder /sdcard/MuMu 2>/dev/null"
        " || true"))
    for line in shared.splitlines():
        p = line.strip()
        if p:
            rep["emulator"].append("shared:%s（MuMu 共享目录，需在模拟器设置里关掉）"
                                   % p)

    # --- Magisk ---
    rp = _magisk(dev)
    rep["magisk"] = {"installed": bool(rp), "resetprop": rp}
    if rp:
        ver = _text(as_root(dev, "magisk -V 2>/dev/null || true")).strip()
        rep["magisk"]["version"] = ver.splitlines()[0] if ver else ""
        zyg = _text(as_root(
            dev, "magisk --sqlite \"SELECT value FROM settings WHERE "
                 "key='zygisk'\" 2>/dev/null || true")).strip()
        rep["magisk"]["zygisk"] = zyg

    rep["unfixable"] = [{"key": k, "why": w} for k, w in UNFIXABLE]
    hits = len(rep["root"]) + len(rep["emulator"])
    rep["score"] = max(0, 100 - 8 * hits)
    return rep


# ---------------------------------------------------------------------------
# 隐藏
# ---------------------------------------------------------------------------
def _denylist(dev, packages, rp: str) -> list:
    """把目标包加进 Magisk DenyList（Magisk 24+ 的官方隐藏机制）。

    DenyList 生效后，这些进程里的 ``mount`` 视图看不到 Magisk、
    ``su`` 不可执行、``/data/adb`` 不可读——正是 App 本地检测要看的几项。
    需要 Zygisk 开启（``settings`` 表里的 ``zygisk=1``）。
    """
    acts = []
    if not rp:
        return acts
    # 确保 zygisk 打开（DenyList 依赖它）
    zyg = _text(as_root(
        dev, "magisk --sqlite \"SELECT value FROM settings WHERE "
             "key='zygisk'\" 2>/dev/null || true")).strip()
    if zyg and not zyg.strip().endswith("1"):
        _text(as_root(dev, "magisk --sqlite \"UPDATE settings SET value=1 "
                           "WHERE key='zygisk'\" 2>/dev/null || true"))
        acts.append({"cmd": "zygisk=1", "ok": True, "why": "DenyList 依赖 Zygisk"})
    listing = _text(as_root(dev, "magisk --denylist ls 2>/dev/null || true"))
    for pkg in packages:
        if not pkg:
            continue
        if pkg in listing:
            acts.append({"cmd": "denylist:%s" % pkg, "ok": True,
                         "why": "已在 DenyList"})
            continue
        out = _text(as_root(dev, "magisk --denylist add %s 2>&1 || true"
                            % _q(pkg)))
        ok = "denylist add" not in out.lower() or not out.strip()
        # Magisk 版本差异：老版本没有 --denylist，退回 sqlite 直写
        if not ok:
            sql = ("INSERT OR REPLACE INTO denylist (package_name, process) "
                   "VALUES ('%s','%s');" % (pkg, pkg))
            out = _text(as_root(dev, "magisk --sqlite %s 2>&1 || true"
                                % _q(sql)))
            ok = not out.strip() or "error" not in out.lower()
        acts.append({"cmd": "denylist:%s" % pkg, "ok": bool(ok),
                     "why": "对 %s 隐藏 root" % pkg})
    return acts


def hide(dev, packages=None, config=None) -> dict:
    """清掉 root / 模拟器证据。返回 ``{"actions": [...], "detect": {...}}``。

    ``packages`` 省略时用 ``KNOWN_APPS`` 的全部包名；也可以传渠道名列表
    （``["ctrip", "qunar"]``），内部自动映射成包名。
    """
    cfg = (config or {}).get("android") if isinstance(config, dict) else None
    sec = (cfg or {}).get("stealth") if isinstance(cfg, dict) else None
    sec = sec if isinstance(sec, dict) else {}

    names = []
    for p in (packages if packages is not None else KNOWN_APPS.values()):
        s = str(p or "").strip()
        if not s:
            continue
        names.append(KNOWN_APPS.get(s, s))
    names = [n for n in dict.fromkeys(names) if n]

    acts = []
    root = _root(dev)
    if not root:
        acts.append({"cmd": "adb root", "ok": False,
                     "why": "拿不到 root：快照与 denylist 都需要它"})
        return {"actions": acts, "detect": detect(dev), "root": False}

    rp = _magisk(dev)

    # 1) props：root 痕迹 + 模拟器厂商 props
    script = []
    for k, v in ROOT_PROPS.items():
        if rp:
            script.append("%s -n %s %s >/dev/null 2>&1 && echo 'OK %s'"
                          % (rp, _q(k), _q(v), k))
        else:
            script.append("setprop %s %s >/dev/null 2>&1 && echo 'OK %s'"
                          % (_q(k), _q(v), k))
    if rp:
        # 厂商 props 直接删（存在即证据）
        for line in _text(_call(dev, "shell", "getprop")).splitlines():
            if "]: [" not in line:
                continue
            key = line.strip()[1:].split("]: [")[0]
            if any(p in key.lower() for p in EMU_PROP_PAT):
                script.append("%s --delete %s >/dev/null 2>&1 && echo 'DEL %s'"
                              % (rp, _q(key), key))
    out = _text(as_root(dev, "; ".join(script) or "true"))
    ok_keys = [ln[3:].strip() for ln in out.splitlines()
               if ln.strip().startswith("OK ")]
    del_keys = [ln[4:].strip() for ln in out.splitlines()
                if ln.strip().startswith("DEL ")]
    acts.append({"cmd": "props:%d set / %d deleted" % (len(ok_keys),
                                                       len(del_keys)),
                 "ok": bool(ok_keys or del_keys), "why": "清 root/厂商 props"})
    if not rp:
        acts.append({"cmd": "resetprop", "ok": False,
                     "why": "没有 Magisk：ro.* 只读，setprop 会失败（这些键改不动）"})

    # 2) Magisk DenyList
    acts += _denylist(dev, names, rp)

    # 3) 藏起 Magisk 管理器自己（装着它在桌面/包列表里就是一条证据）
    mgr = _text(_call(dev, "shell", "pm", "list", "packages",
                      "com.topjohnwu.magisk")).strip()
    if "com.topjohnwu.magisk" in mgr:
        _call(dev, "shell", "am", "force-stop", "com.topjohnwu.magisk")
        out = _text(_call(dev, "shell", "pm", "disable-user", "--user", "0",
                          "com.topjohnwu.magisk"))
        acts.append({"cmd": "hide-magisk-app", "ok": "disabled" in out.lower(),
                     "why": "隐藏 Magisk 管理器包"})

    # 4) 开发者选项开关（部分 SDK 会读；不影响 adb 本身）
    if sec.get("hide_dev_options", True):
        _call(dev, "shell", "settings", "put", "global",
              "development_settings_enabled", "0")

    rep = {"actions": acts, "detect": detect(dev), "root": True,
           "resetprop": rp, "packages": names}
    return rep


def verify(dev, packages=None) -> dict:
    """隐藏后的复核：denylist 是否含目标包、关键 props 是否已落。"""
    names = [KNOWN_APPS.get(str(p), str(p))
             for p in (packages if packages is not None else KNOWN_APPS.values())]
    names = [n for n in dict.fromkeys(names) if n]
    props = props_of(dev)
    bad = [k for k, v in ROOT_PROPS.items()
           if k in ("ro.debuggable", "ro.secure", "ro.build.tags")
           and str(props.get(k, "")).lower() != v.lower()]
    listing = _text(as_root(dev, "magisk --denylist ls 2>/dev/null || true"))
    return {
        "props_ok": not bad,
        "props_bad": bad,
        "denylisted": [n for n in names if n in listing],
        "missing": [n for n in names if n not in listing],
        "debuggable": str(props.get("ro.debuggable", "")),
        "tags": str(props.get("ro.build.tags", "")),
    }


def prepare(dev, config: dict = None, logger=None, *, packages=None,
            vm: int = 0, force: bool = False) -> dict:
    """对外唯一入口：本 boot 周期做一次「检测 → 隐藏 → 复核」。

    标记文件按 boot_id 失效，所以模拟器重启后会重做一次；同一周期内
    只有一条 adb 开销（读标记）。
    """
    from .fingerprint import boot_id
    sec = ((config or {}).get("android") or {}).get("stealth") \
        if isinstance(config, dict) else None
    sec = sec if isinstance(sec, dict) else {}
    if sec.get("enabled") is False:
        return {"ok": True, "skipped": "stealth disabled", "actions": []}

    mark_path = _MARK % int(vm)
    boot = boot_id(dev)
    cur = _text(_call(dev, "shell", "cat", mark_path)).strip()
    if not force and boot and cur == boot:
        return {"ok": True, "skipped": "done this boot", "actions": []}

    rep = hide(dev, packages=packages, config=config)
    rep["verify"] = verify(dev, packages)
    _call(dev, "shell", "sh", "-c",
          "echo %s > %s" % (_q(boot or "1"), mark_path))
    rep["ok"] = True
    if logger:
        d = rep.get("detect") or {}
        logger.info(
            "[android] root/模拟器隐藏：%d 条动作，自检 %d 分（剩余：%s）",
            len(rep.get("actions") or []), d.get("score", 0),
            ", ".join([x for x in (d.get("root") or []) +
                       (d.get("emulator") or [])][:4]) or "无")
    return rep


# ---------------------------------------------------------------------------
# 换身份时的 App 侧清理
# ---------------------------------------------------------------------------
# 这些 App 会把自己生成的设备 ID 落盘（utdid/umid/guid/deviceId）。换了
# android_id 却留着旧文件，等于「新设备 + 旧设备 ID」——比不换更可疑。
_ID_PATTERN = "utdid|umid|deviceId|device_id|guid|android_id|oaid|imei"


def _id_files(dev, pkg: str) -> list:
    out = _text(as_root(
        dev, "grep -rlE '%s' /data/data/%s/shared_prefs "
             "/data/data/%s/files 2>/dev/null | head -40 || true"
             % (_ID_PATTERN, pkg, pkg)))
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def clear_app_identity(dev, packages=None, config: dict = None,
                       logger=None, *, dry_run: bool = True) -> dict:
    """清掉 App 里缓存的设备 ID（**先备份**，默认只演练不删）。

    换身份之后必须做这一步，否则 App 拿着旧 utdid 继续用新 android_id，
    服务端看到的组合是矛盾的。因为文件是 App 私有目录、删错会掉登录，
    所以默认 ``dry_run=True``：先列出会动哪些文件，操作员确认再关掉。

    备份落地：``/data/local/tmp/tm_idbak-<pkg>-<ts>/``。
    """
    names = [(KNOWN_APPS.get(str(p), str(p)))
             for p in (packages if packages is not None else KNOWN_APPS.values())]
    names = [n for n in dict.fromkeys(names) if n]
    rep = {"dry_run": bool(dry_run), "packages": {}, "backup_dir": ""}
    ts = time.strftime("%Y%m%d-%H%M%S")
    for pkg in names:
        files = _id_files(dev, pkg)
        rec = {"files": files, "removed": 0, "backup": ""}
        if files and not dry_run:
            bak = "/data/local/tmp/tm_idbak-%s-%s" % (pkg, ts)
            _call(dev, "shell", "mkdir", "-p", bak)
            for f in files:
                _call(dev, "shell", "cp", "-f", f, bak + "/")
            for f in files:
                _call(dev, "shell", "rm", "-f", f)
                rec["removed"] += 1
            rec["backup"] = bak
            rep["backup_dir"] = bak
            if logger:
                logger.warning("[android] 已清理 %s 的设备 ID 文件 %d 个（备份 %s）",
                               pkg, rec["removed"], bak)
        rep["packages"][pkg] = rec
    return rep
