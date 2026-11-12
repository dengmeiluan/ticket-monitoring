# -*- coding: utf-8 -*-
"""**一条命令**把设备侧准备到位（相对"零配置"）。

对标的 PC 侧入口是 `start.ps1`；设备侧一直缺一个等价物——本来要人工做：
下模块包 → 解压放对位置 → 装 Magisk → 补 x86_64 库 → 配隐藏名单
→ 部署开机模块 → 装 App → 生成配置。任何一步漏了，表现都是
"装了但不生效"或"App 秒崩"，极难自查。

用法：
    python scripts/setup_device.py                 # 体检 + 告诉你还差什么（不改设备）
    python scripts/setup_device.py --apply         # 真装
    python scripts/setup_device.py --apply --reboot # 装完重启并等待伪装生效

它做四件事：
  1. 取包：下载 NeoZygisk / Shamiko（版本与 SHA256 钉死）并构建 mumu_cloak
  2. 生成配置：`config.yaml` 不存在时从 `config.example.yaml` 复制
  3. 落地设备：调 `device_hardening.py` 的全套（含自动停用有害模块）
  4. 装 App：`packages/apks/*.apk` 里有的就装（APK 需自备，不随仓库分发）
最后打印**下一步唯一要跑的命令**。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import io
import os
import re
import shutil
import time
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Windows 控制台通常是 GBK：打印设备原始输出时可能撞上不可编码字符，
# 导致"装到一半崩在 print 上"。这里做编码纠错（保留原编码，仅替换坏字符）。
try:  # pragma: no cover - 只影响 CLI 输出
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass



def _load(name, filename):
    p = os.path.join(ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 期望装到设备上的 App（包名 -> 用途）
APPS = {
    "ctrip.android.view": "携程",
    "com.taobao.trip": "飞猪",
    "com.Qunar": "去哪儿",
    "com.tongcheng.android": "同程",
    "cn.suanya.zhixing": "智行",
}


# 默认启用的 App 渠道：只放**实测可采集**的。
# app_fliggy / app_ctrip 的登录有账号层风控，默认不开，避免"装了却一直失败"。
DEFAULT_APP_CHANNELS = ("app_zhixing", "app_qunar", "app_tongcheng")


def add_platforms(text, ids):
    """在 platforms 里补上 ids。支持行内列表与块列表两种写法。

    返回 (新文本, 实际新增的 id 列表)。已经是 YAML 里存在的项不会重复添加。
    """
    lines = text.splitlines()
    # 定位 platforms: 行
    idx = None
    for i, l in enumerate(lines):
        st = l.strip()
        # 跳过注释行：配置里有形如 `# 改回 `platforms: []` 即可` 的说明，
        # 不排除会把注释当成真的配置段（真机上差点踩到）。
        if st.startswith("#"):
            continue
        if st.startswith("platforms:"):
            idx = i
            break
    if idx is None:
        # 没有 platforms 段：补一段（放在文件末尾最安全）
        exist = set()
        body = "\n".join(lines)
        return (body + "\nplatforms:\n" +
                "".join("  - %s\n" % x for x in ids), list(ids))

    head = lines[idx]
    after = head.split("platforms:", 1)[1].strip()
    if after.startswith("["):
        # 行内列表
        inner = after[after.find("[") + 1:after.rfind("]")]
        cur = [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]
        added = [x for x in ids if x not in cur]
        new_list = cur + added
        lines[idx] = head.split("platforms:")[0] + "platforms: [" + \
            ", ".join(new_list) + "]"
        return ("\n".join(lines) + ("\n" if text.endswith("\n") else ""),
                added)
    # 块列表：收集下面的 `- item`
    cur = []
    j = idx + 1
    while j < len(lines):
        st = lines[j].strip()
        if st.startswith("- "):
            cur.append(st[2:].strip().strip("'\""))
            j += 1
        elif st == "" or st.startswith("#"):
            j += 1
        else:
            break
    added = [x for x in ids if x not in cur]
    if not added:
        return text, []
    ins = ["  - %s" % x for x in added]
    lines[j:j] = ins
    return ("\n".join(lines) + ("\n" if text.endswith("\n") else ""), added)


def enable_app_channels(path, ids=DEFAULT_APP_CHANNELS, log=print):
    """打开 App 渠道采集（写好 platforms + android.enabled）。"""
    if not os.path.isfile(path):
        return False, "配置不存在: %s" % path
    raw = io.open(path, "rb").read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    text = raw.decode("utf-8", "replace")

    new_text, added = add_platforms(text, list(ids))
    # android.enabled: false -> true
    flipped = False
    out_lines = []
    in_android = False
    for line in new_text.splitlines():
        if line and not line.startswith((" ", "\t", "#")) and line.rstrip(":") == "android":
            in_android = True
            out_lines.append(line)
            continue
        if in_android and line and not line.startswith((" ", "\t")):
            in_android = False
        if in_android and line.strip() == "enabled: false":
            indent = line[:len(line) - len(line.lstrip())]
            out_lines.append(indent + "enabled: true")
            flipped = True
            continue
        out_lines.append(line)
    new_text = "\n".join(out_lines) + ("\n" if new_text.endswith("\n") else "")

    if new_text != text:
        io.open(path, "wb").write(new_text.encode("utf-8"))
    return True, "platforms 新增=%s android.enabled%s" % (
        added or "无", " 已打开" if flipped else " 已是开")


def ensure_config(log=print):
    """config.yaml 不在就从 example 复制。返回 (ok, 说明)。"""
    dst = os.path.join(ROOT, "config.yaml")
    src = os.path.join(ROOT, "config.example.yaml")
    if os.path.isfile(dst):
        return True, "已存在，未改动"
    if not os.path.isfile(src):
        return False, "连 config.example.yaml 都找不到"
    shutil.copyfile(src, dst)
    # 复制来源要统一成 LF（仓库 EOL 门禁要求）
    import io as _io
    b = _io.open(dst, "rb").read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    _io.open(dst, "wb").write(b)
    return True, "已从 config.example.yaml 生成"


def parse_packages(text):
    """从 `pm list packages` 输出里取包名集合。"""
    return {m.group(1) for m in re.finditer(r"package:(\S+)", text or "")}


def guess_package(apk_path):
    """从 APK 文件名猜它属于哪个 App（按 packages/apks/README.md 的约定）。

    为什么靠文件名：解析 APK 里的包名要 aapt/zip+manifest 解析，装一次
    依赖不值当。约定文件名即可换来"已装就跳过"，而重复安装 5 个 App
    每次要白等一分多钟。
    认不出来返回空串 —— 那就照装（不能因为猜不出就不装）。
    """
    name = os.path.basename(apk_path).lower()
    table = (
        ("ctrip", "ctrip.android.view"),
        ("携程", "ctrip.android.view"),
        ("fliggy", "com.taobao.trip"),
        ("飞猪", "com.taobao.trip"),
        ("feizhu", "com.taobao.trip"),
        ("qunar", "com.Qunar"),
        ("去哪儿", "com.Qunar"),
        ("tongcheng", "com.tongcheng.android"),
        ("同程", "com.tongcheng.android"),
        ("ly", "com.tongcheng.android"),
        ("zhixing", "cn.suanya.zhixing"),
        ("智行", "cn.suanya.zhixing"),
        ("suanya", "cn.suanya.zhixing"),
    )
    for key, pkg in table:
        if key in name:
            return pkg
    return ""


def install_apks(dev, apk_dir, log=print):
    """装 packages/apks/*.apk 里存在、且设备上还没有的 App。

    两处关键改进（2026-11-06）：
      * **已装就跳过**：原来读了 `pm list packages` 却没用，每次 --apply 都把
        5 个 App 全量重装一遍（白等一分多钟，还无谓重置运行状态）；
      * **装后复核**：`pm install` 回 Success 不等于包真在（安装器可能半途失败），
        装完再查一次 `pm list packages`，查不到就算失败——不假装成功。
    """
    if not os.path.isdir(apk_dir):
        return (True, "无 APK 目录（App 需自备：从各自官网/应用商店获取），跳过")
    apks = sorted(glob.glob(os.path.join(apk_dir, "*.apk")))
    if not apks:
        return (True, "APK 目录为空，跳过")
    installed = parse_packages(dev.sh("pm list packages") or "")
    done, skipped, failed, unknown = [], [], [], []
    for apk in apks:
        base = os.path.basename(apk)
        pkg = guess_package(apk)
        if pkg and pkg in installed:
            skipped.append(base)
            continue
        remote = "/data/local/tmp/" + base
        dev.push(apk, remote)
        out = dev.sh("pm install -r -g %s" % remote) or ""
        if "Success" not in out:
            failed.append(base)
            continue
        if pkg:
            # 装后复核：Success 也要落地成"包真的在"
            now = parse_packages(dev.sh("pm list packages") or "")
            if pkg in now:
                done.append(base)
                installed = now
            else:
                failed.append(base + "(装后查不到包)")
        else:
            # 猜不出包名：如实记为"已尝试安装，未复核到具体包"
            done.append(base)
            unknown.append(base)
    ok = not failed
    detail = "安装=%s 已装跳过=%s 失败=%s" % (
        done or "无", skipped or "无", failed or "无")
    if unknown:
        detail += " 未复核包名=%s" % (unknown,)
    return ok, detail


def missing_apps(dev):
    """哪些目标 App 还没装。"""
    pkgs = dev.sh("pm list packages") or ""
    return [f"{p}({APPS[p]})" for p in APPS
            if ("package:" + p) not in pkgs]


def _resolve_mumu(val):
    """把 --mumu 的入参解析成 MuMuManager.exe 的路径；解析不出返回 ""。

    接受三种写法（用户不会去记 `nx_main` 这一层）：
      * 可执行文件：`...\MuMuManager.exe`
      * 安装目录：  `...\MuMu Player 12`（自动补 `nx_main\MuMuManager.exe`）
      * `nx_main` 目录本身
    解析不出来就原样返回——由 MuMu 侧报错，好过在这里静默失败。
    """
    if not val:
        return ""
    p = os.path.abspath(os.path.expanduser(str(val)))
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        for sub in (("nx_main", "MuMuManager.exe"),
                    ("MuMuManager.exe",)):
            cand = os.path.join(p, *sub)
            if os.path.isfile(cand):
                return cand
        # 目录里再找一层（有的装在 `MuMuPlayer-12.0\shell` 之类）
        for root, _dirs, files in os.walk(p):
            if "MuMuManager.exe" in files:
                return os.path.join(root, "MuMuManager.exe")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description="设备侧一键准备")
    ap.add_argument("--apply", action="store_true", help="真装（默认只体检）")
    ap.add_argument("--reboot", action="store_true", help="装完重启并等待生效")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-start", action="store_true",
                    help="adb 连不上时不要尝试自动拉起 MuMu 实例")
    ap.add_argument("--enable-app-channels", action="store_true",
                    help="把可用的 App 渠道写进 platforms 并打开 android.enabled")
    ap.add_argument("--mumu", default=None,
                    help="MuMuManager.exe 路径，或 MuMu 安装目录"
                         "（默认自动发现）")
    ap.add_argument("--vm", type=int, default=0,
                    help="MuMu 实例序号（默认 0）")
    ap.add_argument("--adb", default=None)
    ap.add_argument("--serial", default=None)
    a = ap.parse_args(argv)

    dh = _load("device_hardening", "device_hardening.py")
    fp = _load("fetch_packages", "fetch_packages.py")

    dev = dh.Dev(a.adb or dh.DEFAULT_ADB, a.serial or dh.DEFAULT_SERIAL)
    if not dev.sh("echo ok") and not a.no_start:
        # 实例没起来是最常见的卡点：先试着拉起，再决定是否报错
        _mm = _resolve_mumu(getattr(a, "mumu", None))
        mumu = dh.MuMu(_mm, vm=a.vm) if (_mm or dh.find_mumu_manager()) else None
        if mumu is not None and mumu.available():
            print("adb 未连接，尝试拉起 MuMu 实例…")
            mumu._run(["control", "-v", str(mumu.vm), "launch"], timeout=120)
            for _ in range(36):
                time.sleep(5)
                if dev.sh("echo ok", timeout=20):
                    break
            if dev.sh("echo ok", timeout=20):
                print("  实例已启动")
    if not dev.sh("echo ok"):
        print("✗ adb 连不上模拟器。逐条核对：")
        print("  1) MuMu 实例真的在跑（MuMu 多开器里状态=运行中）；")
        print("  2) MuMu 设置 → 其他 → 打开「ADB 调试」，端口记下来"
              "（默认 16384）；")
        print("  3) adb 路径对（没自动找到就 --adb <adb.exe 完整路径>）；")
        print("  4) 端口不同就 --serial 127.0.0.1:<端口>。")
        if not dev.adb:
            print("  没自动找到 adb：MuMu 可能没装，或装在非常规目录。")
            print("  装好 MuMu 后重跑；或用 --adb 指定 adb.exe 的完整路径。")
        else:
            print("  adb: %s" % dev.adb)
            print("  确认 MuMu 已启动（实例运行中），或改用 --serial 指定设备。")
        return 2

    print("=== 1/4 取包 ===")
    if a.skip_download:
        print("  跳过（--skip-download）")
    else:
        res = fp.fetch_all(os.path.join(ROOT, "packages"))
        bad = [k for k, (ok, _) in res.items() if not ok]
        if bad:
            print("  ✗ 缺包且下载失败: %s" % bad)
            return 1
        try:
            import build_mumu_cloak as bmc
            ok, msg = bmc.build(os.path.join(ROOT, "packages",
                                             "mumu_cloak.zip"))
            print("  [%s] mumu_cloak.zip %s" % ("OK" if ok else "FAIL", msg))
            if not ok:
                return 1
        except Exception as e:
            print("  ✗ 构建 mumu_cloak 失败: %s" % str(e)[:120])
            return 1

    print("=== 2/4 配置 ===")
    ok, msg = ensure_config()
    print("  [%s] config.yaml %s" % ("OK" if ok else "FAIL", msg))
    if not ok:
        return 1
    if a.enable_app_channels:
        ok2, msg2 = enable_app_channels(os.path.join(ROOT, "config.yaml"))
        print("  [%s] App 渠道 %s" % ("OK" if ok2 else "FAIL", msg2))
        if not ok2:
            return 1

    print("=== 3/4 设备 ===")
    if a.apply:
        _mm2 = _resolve_mumu(getattr(a, "mumu", None)) or dh.find_mumu_manager()
        mumu = dh.MuMu(_mm2, vm=a.vm) if os.path.isfile(_mm2) else None
        for name, ok, detail in dh.apply(dev, os.path.join(ROOT, "packages"),
                                         mumu=mumu):
            print("  [%s] %-22s %s" % ("OK" if ok else "FAIL", name, detail))
        ok, detail = install_apks(dev, os.path.join(ROOT, "packages", "apks"))
        print("  [%s] %-22s %s" % ("OK" if ok else "FAIL", "安装 App", detail))
        if a.reboot and mumu is not None:
            print("  重启并等待伪装生效…")
            mumu.restart()
            for _ in range(40):
                time.sleep(10)
                if (dev.sh("getprop sys.boot_completed") or "").strip() == "1":
                    break
            ok, detail = dh.wait_for_hardening(dev, log=print)
            print("  [%s] 伪装生效 %s" % ("OK" if ok else "FAIL", detail))
    else:
        print("  （只体检模式，未改动设备；加 --apply 才会装）")

    print("=== 4/4 体检 ===")
    ok_all, report = dh.verdict(dh.inspect(dev))
    print(report)

    lack = missing_apps(dev)
    if lack:
        print("\n还缺 App: %s" % "、".join(lack))
        print("  把 APK 放进 packages/apks/ 再跑 --apply 即可自动安装"
              "（地址与包名对照见 docs/DEVICE_PACKAGES.md）")

    print("\n下一步：")
    print("  powershell -File start.ps1        # 启动采集")
    print("  或 python -m core.scheduler       # 只跑调度")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
