# -*- coding: utf-8 -*-
"""把设备身份部署成 KernelSU 开机模块 —— **zygote 启动前**写 props。

为什么必须是开机模块
--------------------
`android.os.Build` 的静态字段在 **zygote 里定型**，App 进程 fork 出来继承
的是 zygote 那一刻的值。所以：

* 采集时热写 props → 对已启动的 App **完全无效**；
* 热写后再 `ctl.restart zygote` → 能让 App 读到新值，但**会把 adb 传输弄坏**
  （2026-11-05 反复实测：`adb devices` 变 offline，设备本身一直健康，
  得重启整个实例才救得回来）。

开机模块把 props 在 zygote 起来**之前**写对，于是：不需要运行时重启
zygote、adb 不会被反复打断、App 从第一次启动看到的就是真机口径。

上一版把开机搞挂了，原因已查明，这一版针对性改掉
------------------------------------------------
上一版 `post-fs-data.sh` 里带了：

  1. `while [ $i -lt 40 ]; do getprop ...; sleep 0.5; done` —— 最多 20 秒等待；
  2. `getprop | grep -oE ... | grep -iE ...` 的反引号扫描（清厂商属性用）。

在 `post-fs-data` 阶段，**任何阻塞都会让 init 卡住**（现象：虚拟机时钟
每秒丢一秒、`VERR_ROM_START_TIMEOUT`、`is_android_started=false`）。
所以这一版硬性约束：

  * `post-fs-data.sh` **只写不读** —— 没有 `getprop`、没有循环、没有管道、
    没有反引号；写完直接 `exit 0`；
  * 厂商属性清扫挪到 `service.sh`（late_start，init 早已放行），且**限次**。

取值只有一个来源
----------------
要写的键值由 ``fingerprint.Identity.props()`` 生成 —— 与采集链路**同一份**。
本脚本不写机型常量，改机型只改 `PHONE_POOL`。

用法::

    python scripts/identity_boot_module.py            # 生成并推送
    python scripts/identity_boot_module.py --dry-run  # 只打印，不碰设备
    python scripts/identity_boot_module.py --remove   # 卸载模块
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULE_ID = "tm_identity"
MODULE_DIR = "/data/adb/modules/" + MODULE_ID

# KernelSU 自带的 resetprop（符号链接到 /data/adb/ksud，实测可写 ro.*）
_KSU_RP = "/data/adb/ksu/bin/resetprop"

_EMU_PAT = "nemu|mumu|netease|goldfish|qemu|vbox|bluestack|ldplayer|noxtn"
_NONPROP_EXCLUDE = "init\\.svc\\.|init\\.svc_debug_pid\\.|ro\\.boottime\\."

# ABI：**arm64 优先，但保留 x86_64/x86**（2026-11-05）。
#
# 为什么改：`Build.SUPPORTED_ABIS` 的首项在模拟器上是 `x86_64`，而真机
# （arm64 手机）必然是 `arm64-v8a` —— 这是设备风控里最经典的一条硬特征。
# 携程的深度设备检测正好发生在**登录校验**环节（发码成功、确认时才
# 返回 50003「当前登录环境存在风险」），所以把首项改成 arm64 值得一试。
#
# 为什么**保留 x86_64/x86 在列表里**（关键取舍）：
# 系统自带的 so 全是 x86_64 编的。如果把 abilist 改成只有 arm64，
# linker 会去找 vndk/arm64 那套不存在的路径 → 系统应用直接起不来
# （仓库里记过 `Runtime.load0` 主线程死锁 / ANR 120s）。
# 保留 x86_64 之后：**系统应用仍按自己的 primaryCpuAbi(x86_64) 加载**，
# 而 `Build.SUPPORTED_ABIS` 的**顺序**已经变成真机形态。
#
# 实测（2026-11-05）：写入后 `boot_completed=1`、zygote 正常、
# 携程/同程都能正常启动，无 SIGSEGV。
ABI_ARM64_FIRST = {
    "ro.product.cpu.abilist":
        "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
    "ro.product.cpu.abi": "arm64-v8a",
    "ro.product.cpu.abilist64": "arm64-v8a,x86_64",
    "ro.product.cpu.abilist32": "armeabi-v7a,armeabi,x86",
    "ro.system.product.cpu.abilist":
        "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
    "ro.system.product.cpu.abilist64": "arm64-v8a,x86_64",
    "ro.system.product.cpu.abilist32": "armeabi-v7a,armeabi,x86",
    "ro.vendor.product.cpu.abilist":
        "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
}

# **原值保留**（不是伪装）的运行时关键键。
#
# 为什么必须显式写回原值、而不是"干脆不写"：
# 这两个键在 MuMu 上**不是稳定存在**的——实测某次重启后
# `ro.vndk.version` 直接变成空串，而**空值同样会让携程启动即 SIGSEGV**
# （linker 找不到 VNDK 命名空间）。所以正确做法是：
# 开机时把它们写成**设备本该有的那个值**（生成模块时从设备读，读不到用
# 已实测可用的 31）。
#
# 判据：这两个键是 linker / PackageManager 的**运行时输入**，不是描述性
# 字段。可以"保持"，绝不能"改成更漂亮的值"（改成 35 会崩）。
_PRESERVE_KEYS = {
    "ro.vndk.version": "31",
    "ro.product.first_api_level": "31",
}


def _read_props_via_mumu(keys, vm: int = 0) -> dict:
    """从设备读若干个 prop 的当前值（走 MuMuManager sh，不依赖 adb）。"""
    out = {}
    try:
        from core.android.vendor import _manager
        mgr = _manager(vm_index=vm)
        if not mgr.available():
            return out
        for k in keys:
            raw = mgr._call(["sh", "-v", str(mgr._vm(vm)), "-c",
                             "getprop " + k], timeout=30)
            v = str(raw or "").strip()
            # MuMuManager 会把输出整段返回；取第一行非空
            for line in v.splitlines():
                if line.strip():
                    v = line.strip()
                    break
            if v and " " not in v:
                out[k] = v
    except Exception:
        pass
    return out


def _device(serial: str):
    from core.android.device import AdbDevice
    from core.android.config import normalize, resolve_install_dir
    from core.android.fingerprint import adb_root
    cfg = normalize(None)
    adb = os.path.join(resolve_install_dir(cfg), "nx_main", "adb.exe")
    if not os.path.isfile(adb):
        adb = "adb"
    dev = AdbDevice(adb, serial)
    try:
        dev.connect()
    except Exception:
        pass
    # `/data/adb/modules` 是 root-only：不先 `adb root` 的话 mkdir/push 全静默失败
    # （实测：`ls` 返回空串，脚本看起来"部署成功但什么都没有"）。
    try:
        adb_root(dev)
    except Exception:
        pass
    return dev


def _rp_block() -> list:
    """选 resetprop 的公共片段；没有可用实现时立刻 exit 0（绝不阻塞）。"""
    return [
        "if [ -x " + _KSU_RP + " ]; then",
        "  RP=" + _KSU_RP,
        "elif [ -x /data/adb/magisk/magisk ]; then",
        '  RP="/data/adb/magisk/magisk resetprop"',
        "else",
        "  exit 0",
        "fi",
        "",
    ]


def render_post_fs_data(props: dict) -> str:
    """**只写不读**的 post-fs-data 脚本（不改挂开机的关键约束）。"""
    lines = [
        "#!/system/bin/sh",
        "# 由 scripts/identity_boot_module.py 生成，请勿手改。",
        "# 约束：本脚本【只写不读】——没有 getprop、没有循环、没有管道。",
        "# 原因：post-fs-data 阶段任何阻塞都会让 init 卡住（上一版栽在这）。",
        "",
    ]
    lines += _rp_block()
    for k, v in props.items():
        lines.append('$RP %s "%s" >/dev/null 2>&1'
                     % (k, str(v).replace('"', '\\"')))
    lines += ["", "exit 0", ""]
    return "\n".join(lines)


def render_service() -> str:
    """late_start：清厂商属性（限次循环，不阻塞 boot）。"""
    return "\n".join([
        "#!/system/bin/sh",
        "# 由 scripts/identity_boot_module.py 生成，请勿手改。",
        "# late_start：init 早已放行，慢一点只影响自己这一次。",
    ] + _rp_block() + [
        "# 等 MuMu 的 nemuinit 把属性写回来（它开机后几分钟内会写一批）",
        "sleep 25",
        "i=0",
        "while [ $i -lt 6 ]; do",
        "  i=$((i+1))",
        "  KEYS=`getprop | grep -oE '^\\[[^]]+\\]' | tr -d '[]' \\",
        "    | grep -iE '" + _EMU_PAT + "' \\",
        "    | grep -vE '" + _NONPROP_EXCLUDE + "'`",
        "  for k in $KEYS; do",
        '    $RP --delete "$k" >/dev/null 2>&1',
        "  done",
        "  sleep 20",
        "done",
        "",
        # **藏掉 MuMu 的共享目录**（2026-11-05）：
        # `/mnt/shared` 不是挂载点，只是 MuMu 建的普通目录，名称本身就是
        # 模拟器特征（`MuMuShared`/`install_apk`/`keymap_config`），
        # App 一个 `File.exists("/mnt/shared")` 就能判定。
        # 实测 `umount` 报 Invalid argument（本来就没挂载），改名可行。
        # 改成点号开头的隐藏名，既不暴露特征，也保留原内容可回滚。
        "if [ -e /mnt/shared ] && [ ! -e /mnt/.sys_share ]; then",
        "  mv /mnt/shared /mnt/.sys_share 2>/dev/null",
        "fi",
        "",
        # **清掉暴露 root / 模拟器的包名**（2026-11-06）：
        # 这些包名任何 App 一个 `getInstalledPackages()` 就能读到，是最硬的
        # 环境判据之一（比 props 更难狡辩）：KernelSU / Magisk 管理器 = 已 root，
        # com.mumu.* / com.nemu.* = 模拟器。
        #
        # 实测：`pm uninstall --user 0` 能立即清掉，但**重启后 MuMu 会把
        # `me.weishu.kernelsu` 装回来**（2026-11-06 实测），所以必须每次开机
        # 再清一遍。用 `pm install-existing` 可随时还原。
        # **保留 `com.nemu.oaidmanager`**：它可能在提供 OAID，摘了会让 OAID
        # 变空、反而多一个异常点。
        "sleep 40",
        "for p in me.weishu.kernelsu com.topjohnwu.magisk "
        "com.mumu.store com.mumu.acc com.mumu.shared.sdk "
        "com.netease.mumu.cloner com.nemu.nlp; do",
        "  pm uninstall --user 0 $p >/dev/null 2>&1",
        "done",
        "",
        # **藏掉宿主 CPU 特征**（2026-11-06 实测）：
        # 模拟器的 /proc/cpuinfo 明写 `vendor_id : GenuineIntel` /
        # `model name : Intel(R) Core(TM) i7-14700`，而真机这里是 ARM 核 +
        # `Hardware : MT6991`。这个文件**全局可读**，App 三行代码就能判定。
        # 用模块自带的一份真机格式 cpuinfo 覆盖上去；标签与权限对齐真机
        # （u:object_r:proc_cpuinfo:s0 / 644），App 读到的内容与真机一致。
        # 放在最后执行，避免影响前面的 resetprop 与包名清理。
        # 回滚：umount /proc/cpuinfo
        "CPUI=%s/fake_cpuinfo" % MODULE_DIR,
        "if [ -f \"$CPUI\" ]; then",
        "  chcon u:object_r:proc_cpuinfo:s0 \"$CPUI\" 2>/dev/null",
        "  chmod 644 \"$CPUI\" 2>/dev/null",
        "  (",
        "    n=0",
        "    while [ $n -lt 12 ]; do",
        "      n=$((n+1))",
        "      # 用 case 读首个标记，避免依赖本机偶发段错误的 grep",
        "      HAS=0",
        "      while read -r line; do",
        "        case \"$line\" in",
        "          *'CPU implementer'*) HAS=1; break;;",
        "        esac",
        "      done < /proc/cpuinfo",
        "      if [ $HAS -eq 0 ]; then",
        "        mount --bind \"$CPUI\" /proc/cpuinfo 2>/dev/null",
        "      fi",
        "      sleep 20",
        "    done",
        "  ) &",
        "fi",
        "",
        # **伪造 SELinux 状态**（2026-11-06 实测）：MuMu 是 Permissive，
        # App 读 /sys/fs/selinux/enforce 就能判定"可调试/已 root"。
        # 真把内核改成 Enforcing 会让 adbd/init 崩（实测过），
        # 所以只把 1 字节的 "1" 盖在这个文件上：读的人看到 1，内核仍是
        # permissive，系统照常跑。实测 getenforce=Enforcing 且 App 采集正常。
        # **电话层去模拟器化**（2026-11-06）：MuMu 伪造了 SIM，但 RIL 实现名
        # 是 AOSP 的 "android reference-ril 1.0"、ro.carrier 是 unknown、
        # 网络类型是 HSPA（3G）。这三条在 Java 层一读就露馅，改成真机样式，
        # 并与设备身份（MT6991）自洽。放在 RIL 起来之后的 late_start 阶段。
        "sleep 5",
        "for kv in \\",
        "  'gsm.version.ril-impl=MediaTek RIL 1.0' \\",
        "  'ro.carrier=OPEN' \\",
        "  'ro.carrier.name=China Mobile' \\",
        "  'gsm.network.type=LTE' \\",
        "  'gsm.version.baseband=MOLY.NR15.R3.TC8.PR2.SP.V1.0.1'; do",
        "  k=${kv%%=*}; v=${kv#*=}",
        "  resetprop \"$k\" \"$v\" 2>/dev/null",
        "done",
        "",
        "ENF=/data/adb/modules/tm_identity/enforce1",
        "if [ -f \"$ENF\" ]; then",
        "  chcon u:object_r:selinuxfs:s0 \"$ENF\" 2>/dev/null",
        "  chmod 644 \"$ENF\" 2>/dev/null",
        "  (",
        "    n=0",
        "    while [ $n -lt 12 ]; do",
        "      n=$((n+1))",
        "      CUR=$(cat /sys/fs/selinux/enforce 2>/dev/null)",
        "      if [ \"$CUR\" != \"1\" ]; then",
        "        mount --bind \"$ENF\" /sys/fs/selinux/enforce 2>/dev/null",
        "      fi",
        "      sleep 20",
        "    done",
        "  ) &",
        "fi",
        "",
    ])


# SoC → (Hardware 行, 核构成)。核 part 值用 ARM implementer 0x41 系列，
# 与真机 aarch64 的写法一致；认不出的 SoC 用通用布局 + 真实 Hardware 串。
SOC_CPUINFO = {
    "MT6991": ("MT6991", ((1, "0xd85"), (3, "0xd82"), (4, "0xd87"))),
    "MT6989": ("MT6989", ((1, "0xd85"), (3, "0xd82"), (4, "0xd87"))),
    "SM8650": ("Qualcomm Technologies, Inc SM8650",
               ((1, "0xd4e"), (3, "0xd81"), (2, "0xd81"), (2, "0xd80"))),
    "SM8550": ("Qualcomm Technologies, Inc SM8550",
               ((1, "0xd4e"), (3, "0xd81"), (4, "0xd80"))),
    "SM8475": ("Qualcomm Technologies, Inc SM8475",
               ((1, "0xd46"), (3, "0xd48"), (4, "0xd49"))),
}
SOC_CPUINFO_FALLBACK = ((1, "0xd0c"), (3, "0xd0b"), (4, "0xd0a"))


def render_fake_cpuinfo(props: dict = None) -> str:
    """真机格式的 /proc/cpuinfo，**按当前身份的 SoC 渲染**（r1063 T89）。

    为什么必须跟着身份走：身份换成骁龙 8 Gen 3（SM8650）之后，若这里还写
    `Hardware : MT6991`（联发科），就是"同机型两个芯片"——正是风控最爱抓的矛盾。
    """
    props = props or {}
    soc = str(props.get("ro.soc.model") or "").strip().upper()
    hw, layout = SOC_CPUINFO.get(soc, (soc or "Qualcomm Technologies, Inc",
                                       SOC_CPUINFO_FALLBACK))
    feats = ("fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp "
             "asimdhp cpuid asimdrdm lrcpc dcpop asimddp")
    out = []
    idx = 0
    for count, part in layout:
        for _ in range(count):
            out += ["processor\t: %d" % idx,
                    "BogoMIPS\t: 38.40",
                    "Features\t: %s" % feats,
                    "CPU implementer\t: 0x41",
                    "CPU architecture: 8",
                    "CPU variant\t: 0x0",
                    "CPU part\t: %s" % part,
                    "CPU revision\t: 0",
                    ""]
            idx += 1
    out += ["Hardware\t: %s" % hw,
            "Revision\t: 0000",
            "Serial\t\t: 0000000000000000"]
    return "\n".join(out) + "\n"


def render_module_prop(props: dict) -> str:
    return "\n".join([
        "id=" + MODULE_ID,
        "name=设备身份（%s）" % (props.get("ro.product.model") or "device"),
        "version=v2",
        "versionCode=2",
        "author=ticket-monitor",
        "description=zygote 之前写入自洽真机身份字段；late_start 清 MuMu 厂商属性",
        "",
    ])


def build_payload(vm: int = 0) -> dict:
    """算出要写进模块的三份文件。**

    刻意**不创建设备对象**：取值只需 `MuMuManager setting --all`（宿主机
    API），跟 adb 无关。这样默认的 `--via mumu` 路径从生成到部署全程
    不碰 adb，也就不会触发 `adb root` 把 adbd 弄坏。
    """
    from core.android import fingerprint as fp
    from core.android import vendor as vd
    ident = fp.build_from_vendor(vd.read(vm_index=vm), seed=6, vm=vm)
    props = ident.props()
    # 运行时关键键：**原值保留**（见 _PRESERVE_KEYS 的说明）
    now = _read_props_via_mumu(list(_PRESERVE_KEYS), vm=vm)
    for k, fallback in _PRESERVE_KEYS.items():
        props[k] = now.get(k) or fallback
    # ABI：arm64 优先（保留 x86_64/x86）——见 ABI_ARM64_FIRST 的说明
    props.update(ABI_ARM64_FIRST)
    return {
        "module.prop": render_module_prop(props),
        "post-fs-data.sh": render_post_fs_data(props),
        "service.sh": render_service(),
        "fake_cpuinfo": render_fake_cpuinfo(props),
        # /sys/fs/selinux/enforce 的替身内容："1"（1 字节，无换行）
        "enforce1": "1",
        "props": props,
    }


def push_via_mumu(files: dict, vm: int = 0) -> dict:
    """通过 **MuMu 自己的 root shell** 部署模块（不碰 adb）。

    为什么不用 adb：`/data/adb/modules` 是 root-only，要写就得 `adb root`，
    而本机 `adb root` 会把 adbd 重启坏（`adb devices` 变 offline、shell 挂住，
    设备本身健康）。`MuMuManager sh -v N -c` 直接就是 root（`u:r:nemuinit:s0`），
    且**不依赖 adbd**——adb 已经坏掉的时候它照样能用，是最可靠的部署通道。

    文件内容走 base64 落盘：避免引号/管道被 Windows 与 adb 两层吃掉
    （仓库里记过多次"脚本没推上去、结果执行了上一个残留脚本"的事故）。
    """
    import base64
    rep = {"ok": False, "via": "mumu-sh", "files": [], "error": ""}
    try:
        from core.android.vendor import _manager
        mgr = _manager(vm_index=vm)
    except Exception as e:
        rep["error"] = "MuMuManager 不可用: %s" % e
        return rep
    if not mgr.available():
        rep["error"] = "MuMuManager 路径不存在"
        return rep

    def _sh(cmd, timeout=60):
        return mgr._call(["sh", "-v", str(mgr._vm(vm)), "-c", cmd],
                         timeout=timeout)

    _sh("mkdir -p " + MODULE_DIR)
    for name in ("module.prop", "post-fs-data.sh", "service.sh",
                 "fake_cpuinfo", "enforce1"):
        content = (files.get(name) or "").replace("\r\n", "\n")
        if not content:
            continue
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        # 单条命令里 base64 无特殊字符，最安全
        out = _sh("echo %s | base64 -d > %s/%s && echo TMOK"
                  % (b64, MODULE_DIR, name))
        if "TMOK" not in str(out or ""):
            rep["error"] = "写入失败: %s" % name
            return rep
        rep["files"].append(name)
    _sh("chmod 755 %s/post-fs-data.sh %s/service.sh; chmod 644 %s/module.prop; "
        "chmod 644 %s/fake_cpuinfo 2>/dev/null; "
        "chmod 755 %s" % (MODULE_DIR, MODULE_DIR, MODULE_DIR, MODULE_DIR,
                          MODULE_DIR))
    listing = _sh("ls -l " + MODULE_DIR) or ""
    rep["listing"] = listing
    rep["ok"] = ("module.prop" in listing
                 and "post-fs-data.sh" in listing)
    return rep


def push(dev, files: dict) -> dict:
    import tempfile
    rep = {"ok": False, "dir": MODULE_DIR, "files": [], "error": ""}
    dev._sh("shell", "mkdir", "-p", MODULE_DIR)
    tmp = tempfile.mkdtemp(prefix="tm_ident_")
    for name in ("module.prop", "post-fs-data.sh", "service.sh",
                 "fake_cpuinfo", "enforce1"):
        content = files.get(name) or ""
        if not content:
            continue
        local = os.path.join(tmp, name)
        # 必须 LF：CRLF 脚本在设备上会 `: not found`
        with open(local, "wb") as fh:
            fh.write(content.replace("\r\n", "\n").encode("utf-8"))
        if dev._sh("push", local, MODULE_DIR + "/" + name) is None:
            rep["error"] = "push 失败: " + name
            return rep
        rep["files"].append(name)
    dev._sh("shell", "chmod", "755", MODULE_DIR + "/post-fs-data.sh")
    dev._sh("shell", "chmod", "755", MODULE_DIR + "/service.sh")
    dev._sh("shell", "chmod", "644", MODULE_DIR + "/module.prop")
    dev._sh("shell", "chmod", "755", MODULE_DIR)
    listing = dev._sh("shell", "ls", "-l", MODULE_DIR) or ""
    rep["ok"] = "module.prop" in listing and "post-fs-data.sh" in listing
    rep["listing"] = listing
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="部署 KernelSU 设备身份开机模块")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--via", default="mumu", choices=("mumu", "adb"),
                    help="部署通道：mumu=MuMuManager sh（默认，不碰 adb）")
    args = ap.parse_args(argv)

    dev = None
    if args.remove:
        from core.android.vendor import _manager
        _manager(vm_index=0)._call(
            ["sh", "-v", "0", "-c", "rm -rf " + MODULE_DIR], timeout=60)
        print("已移除模块目录：", MODULE_DIR)
        return 0

    files = build_payload(vm=0)
    if args.dry_run:
        for name in ("module.prop", "post-fs-data.sh", "service.sh"):
            print("=" * 20, name, "=" * 20)
            print(files[name])
        return 0

    if args.via == "adb":
        rep = push(_device(args.serial), files)
    else:
        rep = push_via_mumu(files, vm=0)
    print("部署：", "OK" if rep["ok"] else "FAILED", rep.get("error", ""),
          "| 通道:", rep.get("via", args.via))
    print(rep.get("listing", ""))
    print("字段数：", len(files["props"]))
    print("重启实例后生效（post-fs-data 早于 zygote，不需要再重启 zygote）。")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
