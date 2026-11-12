# -*- coding: utf-8 -*-
"""自动下载并校验设备侧需要的 Magisk 模块包。

为什么需要它：这套栈要 NeoZygisk（Zygisk 实现）和 Shamiko（对 App 隐藏 root），
之前是人工去 GitHub 找 release 手动放进目录——对"零配置"是硬伤。
这里把**版本和 SHA256 都钉死**在实机验证过的组合上：

    NeoZygisk v2.4   （289-release）  实测在 MuMu+Magisk 31.1 上注入正常
    Shamiko  v1.2.5  （414-release）  实测与 NeoZygisk 共存正常

钉死版本而不是"永远取 latest"：这三个组件的兼容性很脆
（我们实测 ZygiskNext v1.5.2、ReZygisk v1.0.0 都注入失败），
让用户拿到一个"昨天还能跑、今天更新就崩"的组合是最糟的体验。

用法：
    python scripts/fetch_packages.py              # 下载到 packages/
    python scripts/fetch_packages.py --list       # 只列出清单
    python scripts/fetch_packages.py --verify     # 只校验已有文件
    python scripts/fetch_packages.py --with-cloak # 顺带构建 mumu_cloak.zip
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import subprocess
import time
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "packages")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ticket-monitoring-setup"

PACKAGES = {
    "NeoZygisk.zip": {
        "url": ("https://github.com/JingMatrix/NeoZygisk/releases/download/"
                "v2.4/NeoZygisk-v2.4-289-release.zip"),
        "sha256": "93a1425c67bb89f58a0dcb9fc823ec93f6472214f221e667a70b67c6a6e061a1",
        "size": 2401208,
        "kind": "zygisk_impl",
        "note": "Zygisk 实现；v2.4 是实测在 MuMu+Magisk31.1 上注入成功的版本",
    },
    "Shamiko.zip": {
        "url": ("https://github.com/LSPosed/LSPosed.github.io/releases/download/"
                "shamiko-414/Shamiko-v1.2.5-414-release.zip"),
        "sha256": "308d31b2f52a80e49eb58f46bc4c764a6588a79e4b8d101b44860832023f88b4",
        "size": 6523936,
        "kind": "zygisk",
        "note": "对指定 App 隐藏 root；与 NeoZygisk 共存实测正常",
    },
}


def sha256_of(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_zip(path, kind="zygisk"):
    """校验是不是一个可用的 Magisk 模块包。返回 (ok, 说明)。

    判据：能打开 zip、有 module.prop、zygisk 模块还要有 zygisk/*.so。
    只看大小是不够的——GitHub 出错页也可能被存成 2MB 的"文件"。
    """
    if not os.path.isfile(path):
        return False, "文件不存在"
    try:
        z = zipfile.ZipFile(path)
        names = z.namelist()
    except Exception as e:
        return False, "不是有效 zip: %s" % str(e)[:60]
    if "module.prop" not in names:
        return False, "缺 module.prop（不是 Magisk 模块）"
    if kind == "zygisk":
        # Zygisk **模块**（Shamiko 这类）：库放在 zygisk/<abi>.so
        sos = [n for n in names
               if n.startswith("zygisk/") and n.endswith(".so")]
        if not sos:
            return False, "缺 zygisk/*.so（不是 Zygisk 模块）"
    elif kind == "zygisk_impl":
        # Zygisk **实现**（NeoZygisk 这类）：库放在 lib/<abi>/libzygisk*.so
        sos = [n for n in names
               if n.startswith("lib/") and "libzygisk" in n]
        if not sos:
            return False, "缺 lib/*/libzygisk*.so（不是 Zygisk 实现）"
    return True, "%d 个条目" % len(names)


def verify_file(path, meta):
    """校验已下载文件的 SHA256 与大小。返回 (ok, 说明)。"""
    if not os.path.isfile(path):
        return False, "缺失"
    size = os.path.getsize(path)
    if meta.get("size") and size != meta["size"]:
        return False, "大小不符（%d ≠ %d）" % (size, meta["size"])
    digest = sha256_of(path)
    if digest != meta["sha256"]:
        return False, "SHA256 不符（%s…）" % digest[:12]
    return True, "OK"


def download(url, dest, timeout=180):
    """下载。先 urllib（走系统代理环境变量），失败再退回 PowerShell。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, \
                io.open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        if os.path.getsize(dest) > 0:
            return True, "urllib"
    except Exception as e:
        last = str(e)[:80]
    else:
        last = "空文件"
    # 回退：PowerShell 的 Invoke-WebRequest（走系统代理，与 urllib 不同栈）
    ps = ("Invoke-WebRequest -Uri '%s' -OutFile '%s' -UseBasicParsing "
          "-TimeoutSec %d" % (url, dest, timeout))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=timeout + 60)
        if r.returncode == 0 and os.path.isfile(dest):
            return True, "powershell"
        last = (r.stderr or b"").decode("utf-8", "replace")[:80]
    except Exception as e:
        last = str(e)[:80]
    return False, last


def fetch_all(dest=DEST, force=False, log=print):
    """下载 + 校验全部包。返回 {文件名: (ok, 说明)}。"""
    results = {}
    for name, meta in PACKAGES.items():
        path = os.path.join(dest, name)
        if os.path.isfile(path) and not force:
            ok, why = verify_file(path, meta)
            if ok:
                zok, zwhy = validate_zip(path, meta["kind"])
                results[name] = (zok, "已存在且校验通过" if zok else zwhy)
                log("  %-16s 复用（%s）" % (name, results[name][1]))
                continue
            log("  %-16s 已存在但%s，重新下载" % (name, why))
        log("  %-16s 下载中…" % name)
        ok, how = download(meta["url"], path)
        if not ok:
            # 网络抖动不该直接判死：隔 3 秒再试一次（只重试一次，
            # 避免在"真的连不上"时把启动卡成几分钟）
            log("  %-16s 首次失败（%s），3 秒后重试一次…" % (name, how))
            time.sleep(3)
            ok, how = download(meta["url"], path)
        if not ok:
            results[name] = (False, "下载失败: %s" % how)
            log("  %-16s FAIL %s" % (name, how))
            continue
        ok, why = verify_file(path, meta)
        if not ok:
            results[name] = (False, why)
            log("  %-16s FAIL %s" % (name, why))
            continue
        zok, zwhy = validate_zip(path, meta["kind"])
        results[name] = (zok, "下载完成（%s）" % how if zok else zwhy)
        log("  %-16s %s" % (name, results[name][1]))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="下载并校验设备侧模块包")
    ap.add_argument("--dest", default=DEST)
    ap.add_argument("--force", action="store_true", help="已有也重新下载")
    ap.add_argument("--list", action="store_true", help="只列清单")
    ap.add_argument("--verify", action="store_true", help="只校验已有文件")
    ap.add_argument("--with-cloak", action="store_true",
                    help="顺带构建 mumu_cloak.zip")
    a = ap.parse_args(argv)

    if a.list:
        print("设备侧模块包清单（与 docs/DEVICE_PACKAGES.md 同源）")
        for name, m in PACKAGES.items():
            print("\n%s" % name)
            print("  版本/大小 : %d 字节" % m["size"])
            print("  SHA256    : %s" % m["sha256"])
            print("  地址      : %s" % m["url"])
            print("  用途      : %s" % m["note"])
        return 0

    if a.verify:
        bad = 0
        for name, m in PACKAGES.items():
            ok, why = verify_file(os.path.join(a.dest, name), m)
            if ok:
                zok, zwhy = validate_zip(os.path.join(a.dest, name), m["kind"])
                ok, why = zok, zwhy
            print("  [%s] %-16s %s" % ("OK" if ok else "FAIL", name, why))
            bad += 0 if ok else 1
        return 0 if not bad else 1

    print("=== 下载模块包 -> %s ===" % a.dest)
    results = fetch_all(a.dest, a.force)
    bad = [k for k, (ok, _) in results.items() if not ok]
    if bad:
        print("有包不可用: %s" % bad)
        return 1

    if a.with_cloak:
        print("=== 构建 mumu_cloak.zip ===")
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        try:
            import build_mumu_cloak as bmc
            ok, msg = bmc.build(os.path.join(a.dest, "mumu_cloak.zip"))
            print("  [%s] %s" % ("OK" if ok else "FAIL", msg))
            if not ok:
                return 1
        except Exception as e:
            print("  [FAIL] 构建失败: %s" % str(e)[:120])
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
