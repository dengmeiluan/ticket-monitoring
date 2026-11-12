"""设备隐藏层体检与修复（r1063 T106）：`python -m core.android.hide`

背景（2026-11-08 真机实测，携程 50003 / 阿里滑块"点完就堵"）：
设备上装了 Shamiko / Vector / HMA / hide_my_goldfish / mumu_cloak 这些强力隐藏模块，
**但三个被禁用、DenyList 强制开关没开** —— 于是目标 App 的 `/proc/<pid>/maps` 里
赫然出现 `magisk` 6 行、`ksu` 4 行，风控只要扫一眼 maps 就知道这是 root 过的机器。

开 DenyList 强制后复测：`magisk 0 行`。

用法：
```
python -m core.android.hide status           # 模块开关 / DenyList / 关键开关
python -m core.android.hide fix             # 打开 DenyList 强制 + 启用被禁的隐藏模块
python -m core.android.hide tells --pkg com.taobao.trip   # 看目标 App 还能看见什么
```

判据（`tells`）：在目标 App 进程的 maps 里搜标记词，命中即为**泄漏**：
`magisk / ksu / zygisk / shamiko / xposed / lspd / goldfish / nemu / mumu`。
其中 `nemu`（`/dev/__properties__/u:object_r:vendor_nemu_default_prop:s0`）
是 SELinux 属性上下文的**文件名**，`mumu_cloak` 只 hook 属性名与 /system/bin 路径，
盖不到它——需要重编 C++ 模块挂 libc `open/openat/stat`（本仓 `native/mumu_cloak/`）。
"""
from __future__ import annotations

import subprocess

# 标记词 → 匹配方式。`ksu` 这种裸子串会命中文 `libvndKSUpport.so`（实测误报），
# 所以细词一律用**具体路径**匹配。
MARKERS = {
    "magisk": "magisk",
    "kernelsu": "/data/adb/ksu",
    "ksud": "ksud",
    "zygisk": "zygisk",
    "shamiko": "shamiko",
    "xposed": "xposed",
    "lspd": "lspd",
    "goldfish": "goldfish",
    "nemu": "nemu",
    "mumu": "mumu",
    "netease": "netease",
    "houdini": "houdini",
}

# 值得启用（隐藏面）的模块；Vector 是 Xposed 框架，单独按需
# tm_maps_cloak 是我们自己的 maps 洗白模块：它**不依赖 Zygisk**
# （靠 wrap.<pkg> + LD_PRELOAD 注入），所以即使 Zygisk 全灭它也能工作。
HIDE_MODULES = ("zygisk_shamiko", "hma_oss_zygisk", "hide_my_goldfish",
                "mumu_cloak", "tm_identity", "zygisksu", "tm_maps_cloak")
ALL_MODULES = HIDE_MODULES + ("zygisk_vector", "zygisk-assistant")


def _sh(cmd: str, timeout: int = 60) -> str:
    dev = None
    try:
        from core.android.emulator import device
        dev = device()
    except Exception:
        dev = None
    if dev is not None:
        try:
            return str(dev._sh("shell", cmd) or "")
        except Exception:
            pass
    return ""


def _cmd(cmd: str, timeout: int = 60) -> str:
    """走 adb（容器内没有 dev 对象时的兜底）。"""
    adb = "adb"
    try:
        import shutil
        adb = shutil.which("adb") or adb
    except Exception:
        pass
    try:
        return subprocess.run([adb, "-s", "127.0.0.1:16384", "shell", cmd],
                              capture_output=True, timeout=timeout
                              ).stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def run(cmd: str) -> str:
    out = _sh(cmd)
    return out if out.strip() else _cmd(cmd)


def status() -> dict:
    """模块开关 + Magisk 关键设置。"""
    mods = {}
    for m in ALL_MODULES:
        r = run("test -f /data/adb/modules/%s/disable && echo disabled "
                "|| echo on" % m).strip()
        mods[m] = r.splitlines()[-1] if r.strip() else "缺失"
    settings = {}
    raw = run("magisk --sqlite 'SELECT * FROM settings'")
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln.startswith("key=") and "|value=" in ln:
            k, v = ln[4:].split("|value=", 1)
            settings[k] = v
    deny = [x.strip() for x in run("magisk --denylist ls").splitlines()
            if "|" in x]
    # maps 洗白的实际注入点：wrap.<pkg> 有值才算生效（重启后应自动出现）
    wrap = {}
    for pkg in ("com.taobao.trip",):
        v = run("getprop wrap.%s" % pkg).strip()
        if v:
            wrap[pkg] = v
    return {"modules": mods, "settings": settings,
            "denylist": deny, "wrap": wrap,
            "enforce": settings.get("denylist_enforce") == "1"}


def fix() -> dict:
    """打开 DenyList 强制 + 启用所有"隐藏面"模块。

    两者都要求重启才完全生效（Zygisk 模块只在开机装载）。
    """
    out = {"changed": [], "need_reboot": False}
    st = status()
    if not st["enforce"]:
        run("magisk --sqlite \"REPLACE INTO settings (key,value) "
            "VALUES('denylist_enforce',1)\"")
        out["changed"].append("denylist_enforce=1")
        out["need_reboot"] = True
    for m in HIDE_MODULES:
        if st["modules"].get(m) == "disabled":
            run("su -c 'rm -f /data/adb/modules/%s/disable'" % m)
            out["changed"].append("启用 " + m)
            out["need_reboot"] = True
    out["ok"] = True
    return out


def tells(pkg: str = "com.taobao.trip") -> dict:
    """目标 App 进程 maps 里还看得见哪些标记词（命中即泄漏）。"""
    pid = (run("pidof %s" % pkg).split() or [""])[0]
    if not pid:
        return {"ok": False, "why": "%s 未运行（先拉起它再测）" % pkg,
                "leaks": {}}
    leaks = {}
    for name, pat in MARKERS.items():
        n = run("su -c 'grep -ci \"%s\" /proc/%s/maps 2>/dev/null || echo 0'"
                % (pat, pid)).strip().split()
        try:
            cnt = int(n[0]) if n else 0
        except ValueError:
            cnt = 0
        if cnt:
            leaks[name] = cnt
    return {"ok": not leaks, "pid": pid, "pkg": pkg, "leaks": leaks}


def _main(argv=None):                              # pragma: no cover - CLI
    import json
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "fix":
        rep = fix()
    elif cmd == "tells":
        pkg = "com.taobao.trip"
        for i, a in enumerate(argv):
            if a == "--pkg" and i + 1 < len(argv):
                pkg = argv[i + 1]
        rep = tells(pkg)
    else:
        rep = status()
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok", True) else 1
    if cmd == "status":
        print("模块:", " | ".join("%s=%s" % (k, v)
                                 for k, v in rep["modules"].items()))
        print("DenyList 强制:", "开" if rep["enforce"] else "关（root 会暴露）")
        print("DenyList 包:", ", ".join(rep["denylist"][:6]) or "（空）")
        _w = rep.get("wrap") or {}
        print("maps 洗白注入点:",
              ("；".join("%s → %s" % (k, v) for k, v in _w.items())
               if _w else "（无 → 未生效）"))
        return 0 if rep["enforce"] else 1
    if cmd == "fix":
        print("已改:", "、".join(rep["changed"]) or "无需改")
        if rep["need_reboot"]:
            print("→ 需要重启模拟器才完全生效（Zygisk 模块只在开机装载）")
        return 0
    print("泄漏:", " | ".join("%s×%s" % (k, v) for k, v in rep["leaks"].items())
          or "无")
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                         # pragma: no cover
    raise SystemExit(_main())
