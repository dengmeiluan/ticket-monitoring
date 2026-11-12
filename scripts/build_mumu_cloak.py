# -*- coding: utf-8 -*-
"""把 native/mumu_cloak 编译成 Magisk 模块 zip（x86_64 + arm64）。

用法：
    python scripts/build_mumu_cloak.py                 # 自动找 NDK
    python scripts/build_mumu_cloak.py --ndk D:\\path\\to\\ndk
    python scripts/build_mumu_cloak.py --out build/mumu_cloak.zip

NDK 不随仓库分发（体积 ~745MB）。找不到 NDK 时脚本会明确报错并说明怎么装，
不会静默产出坏包。

为什么必须静态链接 libc++：动态链接会在 .so 里留下 `libc++_shared.so` 依赖，
而 App 沙箱的 namespace 里没有这个库 → Magisk/Zygisk dlopen 失败 →
模块被判 unloaded、且日志里什么都看不到（2026-11-06 实测踩过）。
"""
import argparse
import io
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(ROOT, "build")
SRC_DIR = os.path.join(ROOT, "native", "mumu_cloak")
SRC = os.path.join(SRC_DIR, "mumu_cloak.cpp")

TARGETS = {
    "x86_64.so": "x86_64-linux-android29-clang++.cmd",
    "arm64-v8a.so": "aarch64-linux-android29-clang++.cmd",
}
# 静态链接 libc++（见文件头说明）；-fvisibility=hidden 让只有 zygisk 入口导出
FLAGS = ["-shared", "-fPIC", "-O2", "-std=c++17", "-fvisibility=hidden",
         "-static-libstdc++", "-Wl,--exclude-libs,ALL"]

MARKERS_TXT = """# mumu_cloak 隐藏词表 —— 一行一个词，`#` 开头为注释
#
# 这里列的词会用于三处判断：
#   1) 属性名包含该词 → App 读 SystemProperties 时返回默认值（隐藏）
#   2) 文件路径包含该词（限 /system/bin、/system/xbin）→ 视为不存在
#   3) 包名/服务名的暴露面体检（device_hardening）
#
# 改完**不需要重编译**：重启模拟器（或等目标 App 重新拉起）即生效。
# 删空文件 = 退回内置默认（nemu / mumu / netease / houdini）。

nemu
mumu
netease
houdini
"""

MODULE_PROP = """id=mumu_cloak
name=MuMu Cloak
version=v0.3.0
versionCode=5
author=ticket-monitor
description=在 App 进程内替换 SystemProperties/ServiceManager，隐藏 MuMu 特征
managedFeatures=kernel_umount
"""

CANDIDATE_NDK = [
    r"D:\tm_local_tools\_tools\android-ndk-r27c",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\ndk"),
    os.path.expandvars(r"%USERPROFILE%\android-ndk"),
]


def find_ndk(explicit=None):
    """找 NDK 根目录（含 toolchains/llvm/prebuilt/*/bin）。"""
    cands = [explicit] if explicit else []
    cands += CANDIDATE_NDK
    for base in cands:
        if not base or not os.path.isdir(base):
            continue
        pre = os.path.join(base, "toolchains", "llvm", "prebuilt")
        if os.path.isdir(pre):
            for name in os.listdir(pre):
                if os.path.isdir(os.path.join(pre, name, "bin")):
                    return base
    return None


def find_compiler(ndk, pattern):
    pre = os.path.join(ndk, "toolchains", "llvm", "prebuilt")
    for name in os.listdir(pre):
        b = os.path.join(pre, name, "bin")
        if not os.path.isdir(b):
            continue
        hits = sorted(f for f in os.listdir(b) if f.endswith(pattern))
        if hits:
            return os.path.join(b, hits[0])
    return None


def build(out_zip, ndk=None, quiet=False):
    """返回 (ok, 说明)。ok=False 时 out_zip 不会产生。"""
    os.makedirs(BUILD_DIR, exist_ok=True)
    ndk = find_ndk(ndk)
    if not ndk:
        return False, ("找不到 Android NDK。请安装 NDK r27 并用 --ndk 指定，"
                       "或放到 %s" % CANDIDATE_NDK[0])
    if not os.path.isfile(SRC):
        return False, "源码不存在: %s" % SRC

    sos = {}
    for soname, pattern in TARGETS.items():
        cc = find_compiler(ndk, pattern)
        if not cc:
            return False, "NDK 里找不到编译器 %s" % pattern
        dst = os.path.join(BUILD_DIR, soname)
        r = subprocess.run([cc] + FLAGS + ["-o", dst, SRC, "-llog"],
                           capture_output=True, timeout=600)
        if not os.path.isfile(dst):
            return False, ("编译 %s 失败: %s" % (
                soname, (r.stderr or b"").decode("utf-8", "replace")[:300]))
        sos[soname] = dst
        if not quiet:
            print("  %-14s %d 字节" % (soname, os.path.getsize(dst)))

    os.makedirs(os.path.dirname(out_zip), exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("module.prop", MODULE_PROP)
        z.writestr("markers.txt", MARKERS_TXT)
        for soname, path in sos.items():
            z.writestr("zygisk/" + soname, io.open(path, "rb").read())
    return True, out_zip


def main(argv=None):
    ap = argparse.ArgumentParser(description="编译 mumu_cloak 模块")
    ap.add_argument("--ndk", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "build",
                                                  "mumu_cloak.zip"))
    a = ap.parse_args(argv)
    ok, msg = build(a.out, a.ndk)
    print(("OK  " if ok else "FAIL ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
