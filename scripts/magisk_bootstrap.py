# -*- coding: utf-8 -*-
"""把 Magisk 的 `resetprop` 能力部署到设备，并清掉 `ro.*` 暴露面。

为什么需要这个脚本（2026-11-04 实测背景）
----------------------------------------
MuMu 只提供 ``adb root``（adbd 跑 root），**没有 Magisk 守护进程**，
所以 ``resetprop`` 命令不存在。但 **Magisk 的 ``magisk`` 二进制自带
``resetprop`` 子命令**——把 APK 里的 ``lib/x86_64/libmagisk.so`` 提出来
改名 ``magisk`` 就能直接用。

实测（MuMu / Android 15 / SDK 35）：

    getprop ro.nemu                 → 1        （Ctrip SDK 读到就报 50003）
    getprop ro.build.version.nemux  → true
    magisk resetprop ro.nemu ''     → 生效
    getprop ro.nemu                 → （空）
    → 携程登录从「存在风险，限制登录 50003」变成「请完成拼图验证」

两件事必须分开看：

* **二进制部署是持久的**：``/data/local/tmp/magisk_bin/`` 在 /data 分区上，
  实例重启不丢；
* **props 是内存态**：重启后 MuMu 的 ``nemuinit`` 会重新 set 回去，
  所以每次开机都要再清一次——``stealth.prepare()`` 按 ``boot_id`` 失效，
  会自动重跑，前提是**二进制还在**。

本脚本负责"二进制不在就补上"，这样硬化流程永远有 resetprop 可用。

用法：
    python scripts/magisk_bootstrap.py            # 检查 + 部署 + 清 props
    python scripts/magisk_bootstrap.py --check    # 只检查
    python scripts/magisk_bootstrap.py --restore  # 回滚（恢复 ro.nemu=1 等）

依赖：``_magisk_dl/magisk_v28.1.apk`` 存在即可自动提取（不需联网）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 需要清掉的 ro.* 暴露面。它们的值本身就在"自报家门"：
#   ro.nemu=1                     → "我是 MuMu"
#   ro.build.version.nemux=true   → 同上
# 实测 Ctrip SDK 读到就返回 50003（限制登录）。
TARGET_PROPS = ("ro.nemu", "ro.build.version.nemux")

# 二进制在设备上的持久位置（/data 分区，重启不丢）
# **必须用 /data/adb/magisk**（2026-11-04 实测）：magisk 二进制按自身所在
# 目录找配套文件（magisk32/64、sepolicy）。放 /data/local/tmp/ 时找不到，
# resetprop 会退化成普通 setprop。md5 一样、命令一样，只有位置不同。
BIN_DIR = "/data/adb/magisk"
APK_REMOTE = "/data/local/tmp/magisk.apk"
# APK 里 x86_64 的库名 → 设备上的可执行名
_LIBS = (
    ("lib/x86_64/libmagisk.so", "magisk"),
    ("lib/x86_64/libmagiskinit.so", "magiskinit"),
    ("lib/x86_64/libmagiskpolicy.so", "magiskpolicy"),
)

# 本地 APK 候选（按优先级）
_LOCAL_APK = os.path.join(ROOT, "_magisk_dl", "magisk_v28.1.apk")
_LOCAL_APK_ALT = os.path.join(ROOT, "_magisk_dl", "magisk_v27.0.apk")


# MuMu 自带 adb 的常见位置（`adb` 裸命令在 PATH 里通常找不到，
# 那样 AdbDevice 的所有调用都会静默失败——`_magisk()` 就永远返回空）。
_ADB_CANDIDATES = (
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMu\emulator\nemu\adb.exe",
    "adb",
)


def _adb_path() -> str:
    env = os.environ.get("TM_ADB")
    if env:
        return env
    for p in _ADB_CANDIDATES:
        if p == "adb" or os.path.isfile(p):
            return p
    return "adb"


def _serial() -> str:
    return os.environ.get("TM_SERIAL", "127.0.0.1:16384")


def _dev():
    from core.android.device import AdbDevice
    return AdbDevice(_adb_path(), _serial())


def acquire_root(dev=None, wait_s: float = 6.0) -> bool:
    """**主动**执行 `adb root` 并等待 adbd 回来。返回是否已经是 root。

    为什么必须主动拿：实例重启后 adbd 回到 **shell 身份**（uid=2000），
    而 `resetprop` 写 `ro.*` **需要 root**。原来这里只调
    `fingerprint._root(dev)`——那个函数**只做检查、不做获取**，
    于是 ⓪ 步的探针必然失败、报"部署失败"（2026-11-04 实测），
    而真正需要 root 的 ③ stealth 反而在后面才拿到 root。
    """
    import time
    adb = _adb_path()
    serial = _serial()
    try:
        cur = str(_sh(dev or _dev(), "shell", "id") or "")
        if "uid=0" in cur:
            return True
    except Exception:
        pass
    try:
        subprocess.run([adb, "-s", serial, "root"],
                       capture_output=True, timeout=60)
    except Exception:
        return False
    time.sleep(wait_s)
    try:
        subprocess.run([adb, "connect", serial], capture_output=True,
                       timeout=60)
    except Exception:
        pass
    try:
        out = str(_sh(dev or _dev(), "shell", "id") or "")
        return "uid=0" in out
    except Exception:
        return False


def _sh(dev, *args, timeout=90):
    try:
        return dev.sh(*args, timeout=timeout) if hasattr(dev, "sh") \
            else dev._sh(*args, timeout=timeout)
    except Exception:
        return ""


def _getprop(dev, key: str) -> str:
    """读一个 prop；设备不支持返回空串。"""
    try:
        return str(_sh(dev, "shell", "getprop", key) or "").strip()
    except Exception:
        return ""


def probe(dev) -> dict:
    """现状：二进制在不在、两条暴露面还在不在。"""
    from core.android.fingerprint import _magisk
    rp = ""
    try:
        rp = _magisk(dev) or ""
    except Exception:
        rp = ""
    return {
        "resetprop": rp,
        "bin_ok": bool(rp),
        "props": {k: _getprop(dev, k) for k in TARGET_PROPS},
        "exposed": [k for k in TARGET_PROPS if _getprop(dev, k)],
    }


def deploy(dev, apk_local: str = "") -> dict:
    """把 magisk 二进制部署到 ``BIN_DIR``。返回 ``{"ok", "detail"}``。

    APK 已经在设备上就不再 push（省一次 11MB 传输）。
    """
    rep = {"ok": False, "detail": ""}
    # 1) 设备上没有 APK 就从本地 push
    have_apk = APK_REMOTE in str(_sh(dev, "shell", "ls", APK_REMOTE) or "")
    if not have_apk:
        src = apk_local or (_LOCAL_APK if os.path.isfile(_LOCAL_APK)
                            else (_LOCAL_APK_ALT
                                  if os.path.isfile(_LOCAL_APK_ALT) else ""))
        if not src:
            rep["detail"] = ("设备与本地都没有 Magisk APK；请先下载 "
                             "Magisk-v28.1.apk 放到 _magisk_dl/")
            return rep
        try:
            dev.push(src, APK_REMOTE) if hasattr(dev, "push") else None
        except Exception:
            pass
        have_apk = APK_REMOTE in str(_sh(dev, "shell", "ls", APK_REMOTE) or "")
        if not have_apk:
            # push 接口不一定有：退回 adb push
            try:
                subprocess.run(
                    [os.environ.get("TM_ADB", "adb"), "-s",
                     os.environ.get("TM_SERIAL", "127.0.0.1:16384"),
                     "push", src, APK_REMOTE],
                    capture_output=True, timeout=180)
                have_apk = True
            except Exception:
                pass
        if not have_apk:
            rep["detail"] = "APK 推送到设备失败"
            return rep

    # 2) **优先直接 push 本地已解包好的文件**，不要在设备上 unzip。
    #
    # 原实现在设备上跑 `sh -c "unzip ... 'lib/x86_64/...'"`，而**单引号经
    # adb shell 传输会丢**（本轮已第三次踩同一类问题）：解包静默失败，
    # 日志只留下"解包失败："后面什么也没有。
    # 本地 `_magisk_stage/` 是脚本 `--stage` 时解好的，直接推最稳。
    stage_local = os.path.join(ROOT, "_magisk_stage")
    if os.path.isdir(stage_local):
        missing = [dst for _src, dst in _LIBS
                   if not os.path.isfile(os.path.join(stage_local, dst))
                   and dst != ".init-ld"]
        if not missing:
            pushed = 0
            for _src, dst in _LIBS:
                lp = os.path.join(stage_local, dst)
                if not os.path.isfile(lp):
                    continue
                try:
                    subprocess.run(
                        [os.environ.get("TM_ADB") or _adb_path(), "-s",
                         _serial(), "push", lp, "%s/%s" % (BIN_DIR, dst)],
                        capture_output=True, timeout=180)
                    pushed += 1
                except Exception:
                    pass
            # 配套文件也要（magisk 按自身目录找 busybox/magisk32/64）
            for extra in ("busybox", "magiskboot", "magisk32", "magisk64",
                          ".init-ld"):
                lp = os.path.join(stage_local, extra)
                if os.path.isfile(lp):
                    try:
                        subprocess.run(
                            [os.environ.get("TM_ADB") or _adb_path(), "-s",
                             _serial(), "push", lp,
                             "%s/%s" % (BIN_DIR, extra)],
                            capture_output=True, timeout=180)
                    except Exception:
                        pass
            _sh(dev, "shell", "mkdir", "-p", BIN_DIR)
            for _src, dst in _LIBS:
                _sh(dev, "shell", "chmod", "755", "%s/%s" % (BIN_DIR, dst))
            _sh(dev, "shell", "chmod", "755", "%s/busybox" % BIN_DIR)
            seen = str(_sh(dev, "shell", "ls", BIN_DIR + "/magisk") or "")
            if (BIN_DIR + "/magisk") in seen:
                rep["ok"] = True
                rep["detail"] = "已从本地 stage 推送 %d 个二进制" % pushed
                return rep

    # 3) 退回：在设备上解包（注意引号可能丢，失败就如实报）
    names = " ".join("'%s'" % p for p, _ in _LIBS)
    script = (
        "rm -rf /data/local/tmp/magisk_x && "
        "mkdir -p /data/local/tmp/magisk_x && "
        "cd /data/local/tmp/magisk_x && "
        "unzip -o -j %s %s >/dev/null 2>&1 ; " % (APK_REMOTE, names)
    )
    for src_name, dst in _LIBS:
        script += ("[ -f %s ] && mv %s %s ; "
                   % (os.path.basename(src_name),
                      os.path.basename(src_name), dst))
    script += ("mkdir -p %s && cp %s/* %s/ 2>/dev/null ; "
               "chmod 755 %s/* 2>/dev/null ; "
               "ls %s/magisk" % (BIN_DIR, "/data/local/tmp/magisk_x",
                                 BIN_DIR, BIN_DIR, BIN_DIR))
    # **整条脚本作为单个 argv**：写成 `("shell","sh","-c",script)` 时 adb 会
    # 拼成一条命令交给设备 shell 重解析，内层只剩 `sh -c rm`
    # （`-rf /path` 被当位置参数丢掉）→ 后面 `&&` 串起来的 unzip 全不执行。
    # 这正是 19:16 那次"部署失败：解包失败："（detail 空白、没有任何报错）
    # 的成因 —— 失败信息也被同一种写法吞掉了。
    out = str(_sh(dev, "shell", script) or "")
    # 用 ls 直传复核（`sh -c "test -e ..."` 经 adb 引号会丢，实测误判）
    seen = str(_sh(dev, "shell", "ls", BIN_DIR + "/magisk") or "")
    rep["ok"] = (BIN_DIR + "/magisk") in seen
    rep["detail"] = "已部署" if rep["ok"] else ("解包失败：%s" % out[:120])
    return rep


def clear_props(dev) -> dict:
    """用 resetprop 清掉 ``TARGET_PROPS``，并**读回校验**。

    为什么必须读回：``setprop``/``resetprop`` 都可能"报成功但值不变"，
    这个仓库已经被骗过三次（第 3 轮、第 11 轮、第 34 轮）。只有读回才算数。
    """
    from core.android.fingerprint import _magisk, _q
    rp = ""
    try:
        rp = _magisk(dev) or ""
    except Exception:
        rp = ""
    rep = {"ok": False, "resetprop": rp, "cleared": [], "still": [],
           "detail": ""}
    if not rp:
        rep["detail"] = "没有可用的 resetprop（先 deploy）"
        return rep
    for k in TARGET_PROPS:
        if not _getprop(dev, k):
            rep["cleared"].append(k)          # 本来就是空
            continue
        try:
            # `rp` 可能是 `resetprop`（完整 Magisk）或
            # `"/path/magisk resetprop"`（二进制形态），两种都能直接拼参数
            _sh(dev, "shell", "%s %s ''" % (rp, _q(k)))
        except Exception:
            pass
        if _getprop(dev, k):
            rep["still"].append(k)
        else:
            rep["cleared"].append(k)
    rep["ok"] = not rep["still"]
    rep["detail"] = ("全部清空" if rep["ok"]
                     else "仍有残留：%s" % ", ".join(rep["still"]))
    return rep


def restore(dev) -> dict:
    """回滚：把两条 prop 恢复成 MuMu 原值（调试/对比用）。"""
    from core.android.fingerprint import _magisk, _q
    rp = ""
    try:
        rp = _magisk(dev) or ""
    except Exception:
        rp = ""
    rep = {"ok": False, "restored": [], "detail": ""}
    if not rp:
        rep["detail"] = "没有 resetprop，无法恢复（重跑实例即可自然恢复）"
        return rep
    for k, v in (("ro.nemu", "1"),
                 ("ro.build.version.nemux", "true")):
        try:
            _sh(dev, "shell", "%s %s %s" % (rp, _q(k), _q(v)))
        except Exception:
            pass
        if _getprop(dev, k):
            rep["restored"].append(k)
    rep["ok"] = bool(rep["restored"])
    rep["detail"] = "已恢复 %d 条" % len(rep["restored"])
    return rep


def ensure(dev=None, logger=None) -> dict:
    """**硬化流程用的入口**：二进制不在就部署，然后清 props。

    幂等：二进制已在、props 已空时几乎零开销（两次 adb）。
    """
    dev = dev or _dev()
    # **先拿 root**：`resetprop` 写 `ro.*` 需要它，而探针在拿不到 root 时
    # 会一路判成"没有可用 resetprop"，白白放弃整条清理链。
    try:
        acquire_root(dev)
    except Exception:
        pass
    st = probe(dev)
    out = {"probe": st, "deploy": None, "clear": None}
    if not st["bin_ok"]:
        out["deploy"] = deploy(dev)
        if not out["deploy"].get("ok"):
            if logger:
                logger.warning("[magisk] 部署失败：%s",
                               out["deploy"].get("detail"))
            return out
    if st["exposed"] or not st["bin_ok"]:
        out["clear"] = clear_props(dev)
        if logger:
            (logger.info if out["clear"].get("ok") else logger.warning)(
                "[magisk] 清理 ro.* 暴露面：%s", out["clear"].get("detail"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="部署 Magisk resetprop 并清 ro.*")
    ap.add_argument("--check", action="store_true", help="只检查现状")
    ap.add_argument("--restore", action="store_true", help="恢复 ro.* 原值")
    ap.add_argument("--apk", default="", help="本地 APK 路径")
    args = ap.parse_args()

    dev = _dev()
    try:
        dev.connect()
    except Exception:
        pass

    if args.check:
        st = probe(dev)
        print("resetprop:", st["resetprop"] or "（无）")
        print("二进制就绪:", st["bin_ok"])
        for k, v in st["props"].items():
            print("  %-28s = %r" % (k, v))
        print("暴露面:", st["exposed"] or "无")
        return 0 if st["bin_ok"] and not st["exposed"] else 1

    if args.restore:
        r = restore(dev)
        print("恢复:", r["detail"])
        return 0 if r["ok"] else 1

    st = probe(dev)
    if not st["bin_ok"]:
        dep = deploy(dev, args.apk)
        print("部署:", dep["detail"])
        if not dep["ok"]:
            return 1
    cl = clear_props(dev)
    print("清理:", cl["detail"])
    print("resetprop:", cl["resetprop"] or "（无）")
    return 0 if cl["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
