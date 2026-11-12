# -*- coding: utf-8 -*-
"""设备伪装一键落地 / 自检（MuMu + Magisk 栈）。

背景：2026-11-06 这一整套伪装是逐项摸出来的，散落在会话里——
身份属性、`/proc/cpuinfo`、SELinux 视图、电话层指纹、包名清理、Zygisk、
Shamiko 隐藏、以及自建的 `mumu_cloak`（属性/文件隐藏）。
换机器或重装后如果靠人工回忆，必然漏项。本脚本把这些固化下来。

用法：
    python scripts/device_hardening.py --check        # 只体检，不改任何东西
    python scripts/device_hardening.py --apply        # 落地 + 体检
    python scripts/device_hardening.py --apply --packages D:\\path\\to\\packages

`--packages` 里需要（缺哪个会明确告诉你，不会假装成功）：
    NeoZygisk.zip       Zygisk 实现（JingMatrix/NeoZygisk）
    Shamiko.zip         对指定 App 隐藏 root（LSPosed 仓库的 shamiko-*）
    mumu_cloak.zip      本项目自建模块，用 scripts/build_mumu_cloak.py 构建

设计原则：
  * **默认只读**：不加 --apply 绝不改设备。
  * **每步自检**：改完立刻读回验证，失败就报错，不"看起来成功"。
  * **幂等**：可重复执行，已到位的步骤会被跳过。
  * **不碰身份**：身份由 `scripts/identity_boot_module.py` 负责，
    本脚本只调用它，不自己写这个那个 prop（避免两个事实源）。
"""
import argparse
import io
import os
import re
import subprocess
import time
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台通常是 GBK：打印设备原始输出时可能撞上不可编码字符，
# 导致"装到一半崩在 print 上"。这里做编码纠错（保留原编码，仅替换坏字符）。
try:  # pragma: no cover - 只影响 CLI 输出
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


# adb / 串号默认值：**自动探测**，不写死安装盘符
# （本机 MuMu 在 D 盘，别人多半在 C 盘；写死会让"clone 下来就能跑"失效）
DEFAULT_SERIAL = "127.0.0.1:16384"


def _mumu_candidates():
    """MuMu 安装目录候选：先问项目自己的配置探测，再补常见位置。"""
    cands = []
    try:
        from core.android.config import DEFAULT_INSTALL_DIRS
        cands.extend(DEFAULT_INSTALL_DIRS or [])
    except Exception:
        pass
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            cands.append(os.path.join(base, "Netease", "MuMu"))
    for drive in ("C:", "D:", "E:"):
        cands.append(drive + r"\Program Files\Netease\MuMu")
    # 去重但保持顺序
    seen, out = set(), []
    for c in cands:
        c = (c or "").rstrip("\\/")
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def find_adb():
    """找 adb：MuMu 安装目录 → PATH。找不到返回空串。"""
    for base in _mumu_candidates():
        p = os.path.join(base, "nx_main", "adb.exe")
        if os.path.isfile(p):
            return p
    import shutil as _sh
    return _sh.which("adb") or ""


def find_mumu_manager():
    for base in _mumu_candidates():
        p = os.path.join(base, "nx_main", "MuMuManager.exe")
        if os.path.isfile(p):
            return p
    return ""


DEFAULT_ADB = find_adb()

# 需要对其隐藏 root 的 App（本项目实际采集/登录用的）
# **已知会破坏 MuMu ARM 翻译层**的模块：装上后所有 arm64 App 会崩
# （houdini 被遮 → arm64 原生库按原生加载 → UnsatisfiedLinkError）。
# 脚本每次都把它们停用；这不是"可选优化"，是保命项。
BAD_MODULES = {
    "hma_oss_zygisk": "隐藏应用列表，但会遮住 houdini 翻译层",
    "zygisk-assistant": "隐藏 root 痕迹，同样遮住翻译层",
    "zygisk_vector": "LSPosed（Vector），daemon 库架构不匹配且遮翻译层",
    "hide_my_goldfish": "AOSP 模拟器伪装，会把 Build 字段换成 Pixel 导致 App 崩",
}

# MuMu 实例设置（MuMuManager setting -k <key> -val <val>）
MUMU_SETTINGS = {
    "root_permission": "false",   # 关掉 MuMu 自带 root：两个 root 框架会打架
}

TARGET_APPS = [
    "ctrip.android.view",      # 携程
    "com.taobao.trip",         # 飞猪
    "com.Qunar",               # 去哪儿
    "com.tongcheng.android",   # 同程
    "cn.suanya.zhixing",       # 智行
]

# 必须安装的 Magisk 模块（id -> 压缩包名）
MODULES = [
    ("zygisksu", "NeoZygisk.zip"),
    ("zygisk_shamiko", "Shamiko.zip"),
    ("mumu_cloak", "mumu_cloak.zip"),
]


class MuMu:
    """MuMuManager 的封装（不依赖 adb，adb 挂了也能用）。"""

    def __init__(self, exe=None, vm=0, timeout=180):
        self.exe = exe or find_mumu_manager()
        self.vm = vm
        self.timeout = timeout

    def _run(self, args, timeout=None):
        try:
            p = subprocess.run([self.exe] + list(args), capture_output=True,
                               timeout=timeout or self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return (p.stdout or b"").decode("utf-8", "replace")

    def available(self):
        return self._run(["info", "-v", str(self.vm)]) is not None

    def setting(self, key, value):
        return self._run(["setting", "-v", str(self.vm), "-k", key,
                          "-val", str(value)], timeout=60)

    def restart(self):
        return self._run(["control", "-v", str(self.vm), "restart"], timeout=180)

    def sh(self, cmd):
        return self._run(["sh", "-v", str(self.vm), "-c", cmd], timeout=120)


class Dev:
    """adb 的最小封装（只读优先；要改设备前必须确认 root）。"""

    def __init__(self, adb=DEFAULT_ADB, serial=DEFAULT_SERIAL, timeout=120):
        self.adb = adb
        self.serial = serial
        self.timeout = timeout

    def _run(self, args, timeout=None):
        cmd = [self.adb, "-s", self.serial] + list(args)
        try:
            p = subprocess.run(cmd, capture_output=True,
                               timeout=timeout or self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return (p.stdout or b"").decode("utf-8", "replace")

    def sh(self, cmd, timeout=None):
        return self._run(["shell", cmd], timeout)

    def push(self, local, remote):
        return self._run(["push", local, remote])

    def root(self):
        """尽力拿 root：先 adb root，再验证 id。返回是否 root。"""
        self._run(["root"], timeout=60)
        out = self.sh("id") or ""
        return "uid=0" in out

    def is_root(self):
        out = self.sh("id") or ""
        return "uid=0" in out


def parse_packages(text):
    """从 `pm list packages` 输出里取出包名集合。"""
    return {m.group(1) for m in re.finditer(r"package:(\S+)", text or "")}


def parse_denylist(text):
    """从 `magisk --denylist ls` 输出里取出包名集合（格式 pkg|proc）。"""
    out = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if "|" in line:
            out.add(line.split("|")[0])
    return out


def module_ids(text):
    """从 `magisk --path` 目录列表里取模块 id（本脚本只用来判断是否已装）。"""
    return {l.strip() for l in (text or "").splitlines() if l.strip()}


def verdict(checks):
    """checks: [(名称, 是否通过, 说明)] -> (全部通过?, 报告文本)"""
    lines = []
    ok_all = True
    for name, ok, detail in checks:
        if not ok:
            ok_all = False
        lines.append("  [%s] %-28s %s" % ("PASS" if ok else "FAIL", name,
                                          detail))
    return ok_all, "\n".join(lines)


# ---------------------------------------------------------------- 体检
def _decode_out(raw):
    """解子进程输出：Windows 控制台程序常是 GBK，直接按 UTF-8 解会变问号。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


# 一次往返取全部体检信息。值里可能带空格（CPU / 包列表 / 模块列表），
# 解析时取第一个 '=' 之后的部分即可。
_PROBE = r"""
echo "MODEL=$(getprop ro.product.model 2>/dev/null)"
echo "ABI=$(getprop ro.product.cpu.abilist 2>/dev/null)"
echo "CPU=$(head -2 /proc/cpuinfo 2>/dev/null | tr '\n' ' ')"
echo "ENF=$(getenforce 2>/dev/null)"
echo "RIL=$(getprop gsm.version.ril-impl 2>/dev/null)"
echo "CARRIER=$(getprop ro.carrier 2>/dev/null)"
echo "NET=$(getprop gsm.network.type 2>/dev/null)"
echo "PKGS=$(pm list packages 2>/dev/null | tr '\n' ' ')"
ZP=$(pidof zygote64 2>/dev/null | cut -d' ' -f1)
echo "ZPID=$ZP"
echo "ZYG=$( [ -n "$ZP" ] && grep -c zygisk /proc/$ZP/maps 2>/dev/null )"
echo "MODS=$(ls /data/adb/modules 2>/dev/null | tr '\n' ' ')"
echo "MV=$(su -c 'magisk -V' 2>/dev/null)"
echo "DENY=$(su -c 'magisk --denylist ls' 2>/dev/null | tr '\n' ' ')"
echo "ROOT=$(id 2>/dev/null | grep -c 'uid=0')"
echo "CLOAK_OFF=$(ls /data/adb/modules/mumu_cloak/disable 2>/dev/null)"
for m in hma_oss_zygisk zygisk-assistant zygisk_vector hide_my_goldfish; do
  echo "DIS:$m:$(ls /data/adb/modules/$m/disable 2>/dev/null)"
done
echo "END"
"""


def parse_probe_report(text):
    """把 _PROBE 的输出解析成 dict；末尾没有 END 就返回 None（→ 走回退路径）。"""
    if not text or "END" not in text:
        return None
    rep = {"dis": {}}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("DIS:"):
            _, name, rest = line.split(":", 2)
            rep["dis"][name] = rest.strip()
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        rep[k.strip()] = v.strip()
    return rep


def checks_from_report(rep):
    """从汇总报告算出 13 项体检（判据与逐条探测版完全一致）。"""
    checks = []

    mver = rep.get("MV", "").strip()
    checks.append(("Magisk 已安装", bool(mver),
                   mver if mver else
                   "未检测到 Magisk：先按 docs/DEVICE_IDENTITY_PLAYBOOK.md "
                   "「Magisk 落地」一节安装，再跑 --apply"))

    root = rep.get("ROOT", "").strip()
    checks.append(("adb 可用且为 root", root not in ("", "0"),
                   "ok" if root not in ("", "0") else "不是 root"))

    model = rep.get("MODEL", "").strip()
    checks.append(("机型身份", bool(model), model or "(空)"))

    abi = rep.get("ABI", "").strip()
    checks.append(("ABI 首项 arm64", abi.startswith("arm64"), abi or "(空)"))

    cpu = rep.get("CPU", "")
    arm_view = ("CPU implementer" in cpu) or ("BogoMIPS" in cpu)
    checks.append(("/proc/cpuinfo = ARM 视图", arm_view,
                   "已伪装" if arm_view else "仍是宿主 CPU（Intel?）"))

    enf = rep.get("ENF", "").strip()
    checks.append(("SELinux 视图 Enforcing", enf == "Enforcing", enf or "(空)"))

    ril = rep.get("RIL", "").strip()
    carrier = rep.get("CARRIER", "").strip()
    net = rep.get("NET", "").strip()
    tel_ok = ("reference" not in ril.lower()) and carrier != "unknown" \
        and net not in ("", "HSPA")
    checks.append(("电话层去模拟器化", tel_ok,
                   "ril=%s carrier=%s net=%s" % (ril or "?", carrier or "?",
                                                net or "?")))

    pkgs = {m.group(1) for m in re.finditer(r"package:(\S+)", rep.get("PKGS", ""))}
    leak = sorted(x for x in pkgs
                  if re.search(r"magisk|kernelsu|hide_my|mumu|nemu", x, re.I))
    leak = [x for x in leak if x != "com.nemu.oaidmanager"]
    checks.append(("包名暴露面", not leak, "泄漏=%s" % (leak or "无")))

    zyg = rep.get("ZYG", "").strip()
    injected = bool(zyg) and zyg.isdigit() and int(zyg) > 0
    checks.append(("Zygisk 已注入 zygote", injected,
                   "zygote=%s" % (rep.get("ZPID") or "?")))

    mods = set((rep.get("MODS") or "").split())
    missing = [mid for mid, _z in MODULES if mid not in mods]
    checks.append(("Magisk 模块齐全", not missing, "缺=%s" % (missing or "无")))

    deny = set()
    for tok in (rep.get("DENY") or "").split():
        deny.add(tok.split("|")[0])
    miss_deny = [x for x in TARGET_APPS if x not in deny]
    checks.append(("目标 App 已在隐藏名单", not miss_deny,
                   "缺=%s" % (miss_deny or "无")))

    active_bad = [m for m in BAD_MODULES
                  if m in mods and not (rep["dis"].get(m) or "").strip()]
    checks.append(("有害模块已停用", not active_bad,
                   "仍在启用=%s" % (active_bad or "无")))

    cloak_off = (rep.get("CLOAK_OFF") or "").strip()
    cloak_ok = ("mumu_cloak" in mods) and not cloak_off
    checks.append(("mumu_cloak 已启用", cloak_ok,
                   "启用" if cloak_ok else "被 disable 文件停用"))
    return checks


def disable_bad_modules(dev):
    """把已知会破坏 ARM 翻译层的模块停用。返回 (ok, 说明)。"""
    mods = module_ids(dev.sh("ls /data/adb/modules 2>/dev/null"))
    touched, absent = [], []
    for mid in BAD_MODULES:
        if mid not in mods:
            absent.append(mid)
            continue
        dev.sh("touch /data/adb/modules/%s/disable" % mid)
        touched.append(mid)
    # 复查
    still = [m for m in touched
             if (dev.sh("ls /data/adb/modules/%s/disable" % m) or "").strip()
             == ""]
    return (not still,
            "已停用=%s 未安装=%s 失败=%s" % (touched or "无", absent or "无",
                                        still or "无"))


def wait_for_hardening(dev, timeout=300, interval=15, log=None):
    """轮询等待开机伪装生效（cpuinfo / SELinux / 电话层）。

    为什么必须轮询：开机模块的 service.sh 里有 25s+40s 的等待，
    伪装在**开机 2–3 分钟后**才生效。固定 sleep 要么太短误判失败、
    要么太长浪费时间；本会话里我至少三次"查太早以为失败"。
    """
    import time
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        cpu = dev.sh("head -2 /proc/cpuinfo") or ""
        enf = (dev.sh("getenforce") or "").strip()
        ril = (dev.sh("getprop gsm.version.ril-impl") or "").strip()
        arm = ("CPU implementer" in cpu or "BogoMIPS" in cpu)
        tel = ("reference" not in ril.lower()) and bool(ril)
        last = "cpuinfo_arm=%s selinux=%s ril=%s" % (arm, enf or "?", ril or "?")
        if arm and enf == "Enforcing" and tel:
            if log:
                log("  伪装已生效（等待 %.0fs）" % (time.time() - t0))
            return True, last
        if log:
            log("  等待中… %.0fs  %s" % (time.time() - t0, last))
        time.sleep(interval)
    return False, last


def inspect(dev, packages_dir=None):
    """只读体检，返回 [(名称, ok, 说明)]。

    优先用**一次 adb 往返**的汇总报告（`_PROBE`）；拿不到就退回逐条探测。
    """
    try:
        rep = parse_probe_report(dev.sh(_PROBE, timeout=45) or "")
    except TypeError:
        # 部分假设备/旧调用只接受一个参数
        rep = parse_probe_report(dev.sh(_PROBE) or "")
    except Exception:
        rep = None
    if rep is not None:
        return checks_from_report(rep)
    return _inspect_slow(dev, packages_dir)


def _inspect_slow(dev, packages_dir=None):
    """回退路径：逐条 adb 探测（老设备 / 拿不到汇总报告时）。"""
    checks = []

    root = dev.is_root()
    checks.append(("adb 可用且为 root", root,
                   "ok" if root else "不是 root：先 adb root，或检查 MuMu root 权限"))

    # Magisk 本身（没有它后面所有模块都装不了，必须先说清楚）
    mver = (dev.sh("su -c 'magisk -V' 2>/dev/null", timeout=20) or "").strip()
    if not mver:
        mver = (dev.sh("magisk -V 2>/dev/null", timeout=20) or "").strip()
    has_magisk = bool(mver)
    checks.append(("Magisk 已安装", has_magisk,
                   mver if has_magisk else
                   "未检测到 Magisk：先按 docs/DEVICE_IDENTITY_PLAYBOOK.md "
                   "「Magisk 落地」一节安装，再跑 --apply"))

    # 身份
    model = (dev.sh("getprop ro.product.model") or "").strip()
    checks.append(("机型身份", bool(model) and model != "",
                   model or "(空)"))
    abi = (dev.sh("getprop ro.product.cpu.abilist") or "").strip()
    checks.append(("ABI 首项 arm64", abi.startswith("arm64"),
                   abi or "(空)"))

    # 内核视角
    cpu = dev.sh("head -2 /proc/cpuinfo") or ""
    arm_view = "CPU implementer" in cpu or "BogoMIPS" in cpu
    checks.append(("/proc/cpuinfo = ARM 视图", arm_view,
                   "已伪装" if arm_view else "仍是宿主 CPU（Intel?）"))

    # SELinux
    enf = (dev.sh("getenforce") or "").strip()
    checks.append(("SELinux 视图 Enforcing", enf == "Enforcing", enf))

    # 电话层
    ril = (dev.sh("getprop gsm.version.ril-impl") or "").strip()
    carrier = (dev.sh("getprop ro.carrier") or "").strip()
    net = (dev.sh("getprop gsm.network.type") or "").strip()
    tel_ok = ("reference" not in ril.lower()) and carrier != "unknown" \
        and net not in ("", "HSPA")
    checks.append(("电话层去模拟器化", tel_ok,
                   "ril=%s carrier=%s net=%s" % (ril or "?", carrier or "?",
                                                 net or "?")))

    # 包名暴露面
    pkgs = parse_packages(dev.sh("pm list packages"))
    leak = sorted(p for p in pkgs
                  if re.search(r"magisk|kernelsu|hide_my|mumu|nemu", p, re.I))
    # com.nemu.oaidmanager 是有意保留的（提供 OAID）
    leak = [p for p in leak if p != "com.nemu.oaidmanager"]
    checks.append(("包名暴露面", not leak, "泄漏=%s" % (leak or "无")))

    # Zygisk 注入
    zpid = (dev.sh("pidof zygote64") or "").strip().split(" ")[0]
    injected = False
    if zpid:
        n = dev.sh("grep -c zygisk /proc/%s/maps 2>/dev/null" % zpid) or "0"
        injected = (n.strip() not in ("", "0"))
    checks.append(("Zygisk 已注入 zygote", injected,
                   "zygote=%s" % (zpid or "?")))

    # 模块
    mods = module_ids(dev.sh("ls /data/adb/modules 2>/dev/null"))
    missing = [mid for mid, _z in MODULES if mid not in mods]
    checks.append(("Magisk 模块齐全", not missing,
                   "缺=%s" % (missing or "无")))

    # 隐藏名单
    deny = parse_denylist(dev.sh("su -c 'magisk --denylist ls' 2>/dev/null", timeout=20)
                          or dev.sh("magisk --denylist ls"))
    miss_deny = [p for p in TARGET_APPS if p not in deny]
    checks.append(("目标 App 已在隐藏名单", not miss_deny,
                   "缺=%s" % (miss_deny or "无")))

    # 已知有害模块必须处于停用状态（否则 arm64 App 会崩）
    active_bad = [m for m in BAD_MODULES
                  if m in mods and not (dev.sh(
                      "ls /data/adb/modules/%s/disable" % m) or "").strip()]
    checks.append(("有害模块已停用", not active_bad,
                   "仍在启用=%s" % (active_bad or "无")))

    # 自建模块的隐藏面（属性）
    cloak = dev.sh("ls /data/adb/modules/mumu_cloak/disable 2>/dev/null")
    cloak_on = cloak is None or cloak.strip() == ""
    checks.append(("mumu_cloak 已启用", cloak_on,
                   "启用" if cloak_on else "被 disable 文件停用"))

    return checks


# ---------------------------------------------------------------- 落地
def apply(dev, packages_dir, log=print, mumu=None, do_reboot=False):
    """按顺序落地。返回 [(步骤, ok, 说明)]。"""
    steps = []
    if not dev.root():
        return [("获取 root", False, "adb root 失败，先处理 root 再跑 --apply")]

    # Magisk 缺失时不要往下走：后面每一步都依赖它，继续只会给出一串
    # 看不懂的失败（`magisk: not found`）。
    mver = (dev.sh("su -c 'magisk -V' 2>/dev/null", timeout=20) or "").strip() \
        or (dev.sh("magisk -V 2>/dev/null", timeout=20) or "").strip()
    if not mver:
        return [("Magisk 预检", False,
                 "设备上没有 Magisk，模块全部装不了。先装 Magisk"
                 "（见 docs/DEVICE_IDENTITY_PLAYBOOK.md 的 Magisk 一节），"
                 "装好后重跑本命令")]
    steps.append(("Magisk 预检", True, "版本 %s" % mver))

    # ① MuMu 实例设置（关 MuMu 自带 root，避免两个 root 框架打架）
    if mumu is not None and mumu.available():
        ok = True
        detail = []
        for k, v in MUMU_SETTINGS.items():
            out = mumu.setting(k, v)
            text = (out or "").strip()
            # 成功时 MuMuManager 可能回空行、也可能回显键值；只有**明确报错**
            # 才算失败（原来用 "值 in 输出" 判，空输出会被误判成未确认）。
            err = any(w in text.lower() for w in
                      ("error", "fail", "invalid", "not found",
                       "不存在", "失败", "错误"))
            good = out is not None and not err
            ok = ok and good
            detail.append("%s=%s%s" % (
                k, v, "" if good else "(失败: %s)" % (text[:40] or "无输出")))
        if ok:
            detail.append("（可用 mumu.info 复核实例设置）")
        steps.append(("MuMu 实例设置", ok, " ".join(detail)))
    else:
        steps.append(("MuMu 实例设置", True, "未提供 MuMuManager，跳过"))

    # ② 停用已知有害模块（保命项）
    ok, detail = disable_bad_modules(dev)
    steps.append(("停用有害模块", ok, detail))

    # ① 身份开机模块（含 cpuinfo / SELinux / 电话层 / 包名清理）
    try:
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "scripts",
                                         "identity_boot_module.py"),
                            "--via", "mumu"],
                           capture_output=True, timeout=600)
        ok = r.returncode == 0
        out = _decode_out(r.stdout).strip().splitlines()
        err = _decode_out(r.stderr).strip()
        steps.append(("部署身份开机模块", ok,
                      (out[-1] if ok and out else (err[:120] or "无输出"))))
    except Exception as e:
        steps.append(("部署身份开机模块", False, str(e)[:120]))

    # ② 装 Magisk 模块（缺包就明确报）
    for mid, zname in MODULES:
        mods = module_ids(dev.sh("ls /data/adb/modules 2>/dev/null"))
        if mid in mods:
            steps.append(("安装模块 %s" % mid, True, "已存在，跳过"))
            continue
        zp = os.path.join(packages_dir or "", zname)
        if not os.path.isfile(zp):
            steps.append(("安装模块 %s" % mid, False,
                          "缺压缩包：%s" % zp))
            continue
        remote = "/data/local/tmp/%s" % zname
        dev.push(zp, remote)
        out = dev.sh("su -c 'magisk --install-module %s' 2>&1" % remote) or ""
        ok = "Done" in out or "success" in out.lower()
        steps.append(("安装模块 %s" % mid, ok, out.strip().splitlines()[-1]
                      if out.strip() else "无输出"))

    # ③ 补 x86_64 zygisk 库（架构错配会让模块加载不了）
    fill = _fill_x64(dev)
    steps.append(("补齐 x86_64 zygisk 库", fill[0], fill[1]))

    # ④ 隐藏名单
    miss = []
    for p in TARGET_APPS:
        out = dev.sh("su -c 'magisk --denylist add %s' 2>&1" % p,
                             timeout=30) or ""
        if "already exists" in out or out.strip() == "":
            continue
        miss.append(p)
    deny = parse_denylist(dev.sh("su -c 'magisk --denylist ls' 2>&1"))
    lack = [p for p in TARGET_APPS if p not in deny]
    steps.append(("配置隐藏名单", not lack, "缺=%s" % (lack or "无")))

    return steps


def _fill_x64(dev):
    """把各 zygisk 模块缺失的 x86_64 库从原 zip 补进模块目录。

    MuMu 为了让 arm64-only 的 App 能跑，设备声称 arm64 优先，
    于是 Magisk 的模块安装器只铺 arm64 的 zygisk 库；
    而 zygote/App 进程实际是 x86_64 → 模块库加载不上（HMA 显示"模块未激活"）。

    返回 (ok, 说明)。**没有可用解压工具时 ok=False**——不能静默跳过，
    否则故障会以"模块装了但不生效"的形式出现在很远的地方。
    """
    script = r'''
set -e
TMP=/data/local/tmp
# 解压工具探测：系统 unzip 最稳，其次 busybox applet，最后 toybox
if [ -x /system/bin/unzip ]; then UZ=/system/bin/unzip
else
  BB=/data/adb/magisk/busybox
  [ -x "$BB" ] || BB=/debug_ramdisk/busybox
  [ -x "$BB" ] || BB=$(command -v busybox 2>/dev/null)
  if [ -n "$BB" ] && $BB --list 2>/dev/null | grep -qx unzip; then UZ="$BB unzip"
  elif toybox 2>/dev/null | tr ' ' '\n' | grep -qx unzip; then UZ="toybox unzip"
  else UZ=""; fi
fi
if [ -z "$UZ" ]; then echo "NO_UNZIP"; exit 0; fi

fill() {
  MOD=$1; ZIP=$2
  D=/data/adb/modules/$MOD/zygisk
  [ -d "$D" ] || { echo "skip:$MOD(未安装)"; return 0; }
  [ -f "$ZIP" ] || { echo "skip:$MOD(无源包)"; return 0; }
  [ -f "$D/x86_64.so" ] && { echo "ok:$MOD(已齐全)"; return 0; }
  cd "$D" || return 0
  $UZ -o "$ZIP" 'zygisk/x86_64.so' -j >/dev/null 2>&1 || true
  [ -f libzygisk.so ] && cp libzygisk.so x86_64.so
  if [ -f x86_64.so ]; then chmod 644 x86_64.so; echo "filled:$MOD"
  else echo "fail:$MOD(解压不出 x86_64.so)"; fi
}
fill zygisksu "$TMP/NeoZygisk.zip"
fill zygisk_shamiko "$TMP/Shamiko.zip"
fill mumu_cloak "$TMP/mumu_cloak.zip"
echo "DONE"
'''
    out = dev.sh("su -c %s" % _quote(script)) or ""
    if "NO_UNZIP" in out:
        return (False, "设备上没有可用的解压工具（无 /system/bin/unzip、"
                       "busybox 也无 unzip applet）——x86_64 库补不了，"
                       "模块会因为缺 x86_64.so 加载不上")
    filled = re.findall(r"filled:(\S+)", out)
    failed = re.findall(r"fail:(\S+)", out)
    if failed:
        return (False, "补库失败: %s" % failed)
    if "DONE" not in out:
        return (False, "补库脚本未正常结束: %s" % out.strip()[:120])
    return (True, ("已补: %s" % filled) if filled else "各模块 x86_64 库已齐全")


def _quote(s):
    """把脚本安全地塞进 sh -c 的单引号里。"""
    return "'" + s.replace("'", "'\\''") + "'"


def main(argv=None):
    ap = argparse.ArgumentParser(description="设备伪装一键落地 / 自检")
    ap.add_argument("--apply", action="store_true", help="实际改动设备")
    ap.add_argument("--check", action="store_true", help="只体检（默认）")
    ap.add_argument("--adb", default=DEFAULT_ADB)
    ap.add_argument("--serial", default=DEFAULT_SERIAL)
    ap.add_argument("--packages", default=os.path.join(ROOT, "packages"),
                    help="存放 NeoZygisk.zip / Shamiko.zip / mumu_cloak.zip 的目录")
    ap.add_argument("--mumu", default=None,
                    help="MuMuManager.exe 路径（默认按安装目录探测）")
    ap.add_argument("--reboot", action="store_true",
                    help="落地后重启模拟器并轮询等待伪装生效")
    a = ap.parse_args(argv)

    dev = Dev(a.adb, a.serial)
    if not dev.sh("echo ok"):
        print("adb 连不上 %s（检查 MuMu 是否在跑、adb 路径是否正确）" % a.serial)
        return 2

    mumu = MuMu(a.mumu) if (a.mumu or os.path.isfile(
        MuMu().exe)) else None

    if a.apply:
        print("=== 落地 ===")
        for name, ok, detail in apply(dev, a.packages, mumu=mumu):
            print("  [%s] %-24s %s" % ("OK" if ok else "FAIL", name, detail))
        if a.reboot and mumu is not None:
            print("=== 重启并等待伪装生效 ===")
            mumu.restart()
            for _ in range(30):
                if dev.sh("getprop sys.boot_completed", timeout=30) is not None:
                    time.sleep(10)
                    break
                time.sleep(5)
            ok, detail = wait_for_hardening(dev, log=print)
            print("  [%s] 伪装生效 %s" % ("OK" if ok else "FAIL", detail))
        print()

    print("=== 体检 ===")
    ok_all, report = verdict(inspect(dev, a.packages))
    print(report)
    print()
    print("总判定:", "全部通过" if ok_all else "有未通过项（见上）")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
