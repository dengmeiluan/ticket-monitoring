# -*- coding: utf-8 -*-
"""build.prop 身份字段校正 —— **boot 期生效**，不碰运行中的属性。

为什么走这条路（2026-11-04 实测，两条关键前置）
----------------------------------------------
1. **`/system` 确实可写**。`abi_canary` 的 remount 探针原先写成三段 argv
   （`sh -c "mount -o remount,rw / …"`），adb 拆参数后内层只剩 `sh -c mount`
   → **根本没尝试 remount**，于是可写系统被报成"块设备只读"，
   把我引向"全局改不动、只能装 Magisk"的整条弯路（见 §6.39）。
   修成单 argv 后实测输出含 `TM_RW_OK`，即写入通道是通的。
2. **只有"文件赢"的键改了才有用**。逐键比对文件值与运行时 `getprop`：
   `ro.product.system.*`、各分区 `build.fingerprint`、`ro.build.flavor/description/product`
   的 `mumu_win_x86_64` **都在 boot 期被 MuMu 官方 keys 覆盖**（现值已是 vivo/V2405A），
   改这些文件是白干。真正"文件赢"的只有 build.id 一族：

       ro.build.id / ro.system.build.id / ro.system_ext.build.id
       ro.product.build.id / ro.vendor.build.id / ro.odm.build.id  = V417IR
       ro.build.display.id = "V417IR release-keys"

   `V417IR` 是 MuMu 自己的 build 号 —— App 一次 `getprop ro.build.id` 就看得到。

为什么不热改
------------
运行中改 `ro.build.*` / `ro.product.*` 会让 system_server 重启、adbd 掉线
（今天踩了两次，见 `abi_canary._NO_HOT_WRITE`）。build.prop 是 boot 期读的静态文件，
**写完必须重启实例才生效**，因此本模块永远返回 `restart_required=True`，
并且**绝不动** `cpu.abi*` / `dalvik.vm.isa.*` 这类运行期依赖的键。

取值只有一个来源
----------------
目标值一律来自 `fingerprint.PHONE_POOL` 的既有条目（`build_id` / `build_display`），
不在这里另写一套机型常量 —— 两处定义迟早漂移。

失败面（如实报告，不假装成功）
------------------------------
* 读不到原文件 → 该文件跳过（**绝不 push 空内容**，那会把设备写坏）；
* 行数与原文不一致 → 还原并报错；
* 写后读回不等于目标值 → 记 `verified=False`；
* 只读分区 → 先 remount 该分区重试一次，仍失败就如实记下哪个文件没改成
  （部分修好 = 仍有 tell，不能让报告看起来"全绿"）。
"""
from __future__ import annotations

import os
import tempfile

from .fingerprint import PHONE_POOL, _call, _text, props_of

# 只允许这些键被改写：值全部来自池条目的 build_id / build_display。
# 用**白名单**而不是"所有含 V417IR 的行"，是为了结构性地保证
# 不会顺手改到 `ro.system.product.cpu.abilist` / `dalvik.vm.isa.x86_64.*`
# 这类运行期依赖 —— 改那些是真的会把系统写坏。
KEY_FIELDS = {
    "ro.build.id": "build_id",
    "ro.system.build.id": "build_id",
    "ro.system_ext.build.id": "build_id",
    "ro.product.build.id": "build_id",
    "ro.vendor.build.id": "build_id",
    "ro.odm.build.id": "build_id",
}
# display.id 单独处理：跟 build.id 保持同源，避免出现"两种 build 号"
DISPLAY_KEY = "ro.build.display.id"

BUILD_PROPS = (
    "/system/build.prop",
    "/system/system_ext/etc/build.prop",
    "/product/etc/build.prop",
    "/vendor/build.prop",
    "/odm/etc/build.prop",
)
BAK_DIR = "/data/local/tmp"


def _bak_path(path: str) -> str:
    """每个文件**各自**的备份路径。

    坑：这五个文件 basename 全是 `build.prop`。若用 basename 拼备份名，
    `/system`、`/product`、`/vendor`、`/odm`、`/system_ext` 会共用同一个备份 →
    第一个之外的那些**根本没有回滚点**（ls 已非空就跳过备份），
    而且 `restore()` 会把 /system 的原件灌进所有分区 —— 那是把设备写坏。
    所以备份名用整条路径转写下划线。
    """
    return "%s/%s.bootprops.orig" % (
        BAK_DIR, str(path).lstrip("/").replace("/", "_"))


def _read(dev, path):
    """返回文件内容（str），读不到返回 None。走**独立 argv**，不套 sh -c。"""
    out = _text(_call(dev, "shell", "cat", path))
    if not out or not out.strip():
        return None
    return out


def _write(dev, path, text):
    """本地临时文件 → `adb push` → 读回校验。

    不用 `echo ... > 文件`：那是三段 argv 的老坑，且长内容会被 shell 截断/转义。
    """
    fd, loc = tempfile.mkstemp(suffix=".prop")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        fn = getattr(dev, "push", None)
        if callable(fn):
            return bool(fn(loc, path))
        return False
    finally:
        try:
            os.unlink(loc)
        except OSError:
            pass


def resolve(props=None):
    """按运行时 model 找到池条目（取值的唯一来源）。找不到返回 None。

    用**运行时 props**而不是配置文件：本机实测 `ro.product.model=V2405A`，
    池里有同名条目；而配置文件里写的是另一台（漂移过一次，§6.34 的教训）。
    """
    props = props if props is not None else {}
    model = str(props.get("ro.product.model") or "").strip()
    if not model:
        return None
    for p in PHONE_POOL:
        if str(p.get("model")) == model:
            return p
    return None


def desired(profile):
    """目标键值（profile 为 None 时返回空 dict —— 不猜机型）。"""
    out = {}
    if not profile:
        return out
    bid = str(profile.get("build_id") or "").strip()
    if not bid:
        return out
    for k, field in KEY_FIELDS.items():
        v = str(profile.get(field) or "").strip() or bid
        out[k] = v
    out[DISPLAY_KEY] = "%s release-keys" % bid
    return out


def plan(dev, want=None, props=None):
    """算出要改什么，不写。返回 {"files": {path: [(key, old, new)]}, ...}。"""
    props = props if props is not None else props_of(dev)
    if want is None:
        want = desired(resolve(props))
    rep = {"files": {}, "model": str(props.get("ro.product.model") or ""),
           "profile_found": bool(resolve(props)),
           # 文件**存在**但读不到内容/内容为空：不能当"没有这个分区"静默跳过，
           # 否则旧值（V417IR）还在那儿，报告却长得像"全部处理完了"。
           "unreadable": []}
    if not want:
        return rep
    for path in BUILD_PROPS:
        text = _read(dev, path)
        if text is None:
            if _text(_call(dev, "shell", "ls", "-d", path)).strip() == path:
                rep["unreadable"].append(path)
            continue
        todo = []
        for line in text.splitlines():
            if not line.strip() or line.startswith("#") or "=" not in line:
                continue
            k = line.split("=", 1)[0].strip()
            if k in want:
                cur = line.split("=", 1)[1]
                if cur != want[k]:
                    todo.append((k, cur, want[k]))
        if todo:
            rep["files"][path] = todo
    return rep


def apply(dev, config=None, logger=None):
    """按计划改写 build.prop（**幂等**）。写后读回校验，需要重启才生效。"""
    from .fingerprint import _flag

    sec = ((config or {}).get("android") or {}).get("boot_props") or {}
    if not _flag(sec.get("enabled", True), True):
        return {"ok": True, "skipped": "config 关闭", "changed": 0,
                "files": [], "restart_required": False}

    props = props_of(dev)
    if not props:
        return {"ok": False, "error": "设备没读到 props", "changed": 0,
                "files": [], "restart_required": False}
    profile = resolve(props)
    if not profile:
        # 机型不在池里：宁可不改，也不要凭猜写一个 build 号进去
        return {"ok": False, "skipped": "model=%s 不在 PHONE_POOL，不改 build.prop"
                % props.get("ro.product.model"), "changed": 0,
                "files": [], "restart_required": False}

    want = desired(profile)
    pl = plan(dev, want=want, props=props)
    files = pl["files"]
    rep = {"ok": True, "changed": 0, "files": [], "failed": [],
           "verified": True, "restart_required": False,
           "backups": [], "target_build_id": want.get("ro.build.id", ""),
           "model": pl["model"]}
    # 先记下"存在但读不到"的分区：这些地方的旧值**还看得见**，
    # 必须让报告带伤，不能因为"没有可改项"就返回 ok=True。
    for p in pl.get("unreadable") or []:
        rep["failed"].append("%s: 文件在但读不到内容，未修改（旧值仍然可见）" % p)
        rep["ok"] = False
        rep["verified"] = False
    if not files:
        if rep["ok"]:
            # 这才是真正的"无需改动"，不能和"没读到"混为一谈
            if logger:
                logger.info("[android] build.prop 身份字段已是目标值（build_id=%s）",
                            want.get("ro.build.id"))
        return rep

    # 尝试一次全局 rw（实测这台 /system 可写）；失败也不中断，逐文件如实记录
    _call(dev, "shell", "mount", "-o", "remount,rw", "/")

    for path, todo in files.items():
        text = _read(dev, path)
        if text is None:
            rep["failed"].append("%s: 读不到原文件，跳过（绝不写空内容）" % path)
            rep["ok"] = False
            continue
        bak = _bak_path(path)
        # 备份只在**没有备份时**做一次：否则反复跑会把"原始版本"
        # 覆盖成"上一次改坏的版本"，回滚点就没了（幂等要保住回滚能力）
        if not _text(_call(dev, "shell", "ls", bak)).strip():
            _call(dev, "shell", "cp", "-f", path, bak)
            rep["backups"].append(bak)

        mapping = dict((k, new) for k, _o, new in todo)
        lines = text.splitlines()
        out = []
        for line in lines:
            if line.strip() and not line.startswith("#") and "=" in line:
                k = line.split("=", 1)[0].strip()
                if k in mapping:
                    out.append("%s=%s" % (k, mapping[k]))
                    continue
            out.append(line)
        # 结构自检：行数必须一致（我们只替换等号右边，不增删行）
        if len(out) != len(lines):
            rep["failed"].append("%s: 行数变了 %d->%d，放弃写入"
                                 % (path, len(lines), len(out)))
            rep["ok"] = False
            continue

        new_text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
        if not _write(dev, path, new_text):
            # 只读分区：remount 该分区再试一次，仍失败就如实报
            part = "/" + path.strip("/").split("/")[0]
            _call(dev, "shell", "mount", "-o", "remount,rw", part)
            if not _write(dev, path, new_text):
                rep["failed"].append("%s: 写入失败（分区 %s 可能仍只读）"
                                     % (path, part))
                rep["ok"] = False
                # 写都没写成，就谈不上"校验通过" —— 不能留 verified=True，
                # 否则消费方（hardening 汇总）会以为这件事已经落地了。
                rep["verified"] = False
                continue

        # **读回校验**：命令返回 0 不算成功
        check = _read(dev, path) or ""
        miss = []
        for key, old, new in todo:
            if ("%s=%s" % (key, new)) not in check.splitlines():
                miss.append(key)
        rep["changed"] += len(todo) - len(miss)
        if miss:
            rep["verified"] = False
            rep["failed"].append("%s: 读回不符 %s" % (path, ",".join(miss)))
        rep["files"].append(path)

    rep["restart_required"] = bool(rep["files"])
    if logger and rep["files"]:
        logger.info(
            "[android] build.prop 身份字段已改 %d 处（build_id=%s，"
            "**重启实例才生效**）；备份 %s%s",
            rep["changed"], rep.get("target_build_id"),
            ", ".join(rep["backups"]) or "(沿用已有)",
            "" if rep["ok"] and rep["verified"]
            else "；**未全部成功**：" + "; ".join(rep["failed"])[:150])
    return rep


def restore(dev, logger=None):
    """从备份还原所有被本模块改过的 build.prop（回滚用）。"""
    rep = {"ok": True, "restored": [], "failed": []}
    for path in BUILD_PROPS:
        bak = _bak_path(path)
        if not _text(_call(dev, "shell", "ls", bak)).strip():
            continue
        _call(dev, "shell", "mount", "-o", "remount,rw", "/")
        _call(dev, "shell", "cp", "-f", bak, path)
        # 读回比对：`cp` 返回 0 不代表内容对（只读分区上会静默失败）
        back = _read(dev, path)
        orig = _read(dev, bak)
        if back is not None and orig is not None and back == orig:
            rep["restored"].append(path)
        else:
            rep["failed"].append(path)
            rep["ok"] = False
    if logger and rep["restored"]:
        logger.info("[android] build.prop 已还原：%s（重启实例生效）",
                    ", ".join(rep["restored"]))
    return rep
