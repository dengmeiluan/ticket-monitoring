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

from .fingerprint import (_call, _text, as_root, props_of, _root, _magisk,
                          _q, _exact_path_exists, app_can_see)

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

# 这些前缀的键**不是可写的 prop**，删不掉也不该算"没清掉"：
# ``init.svc.*`` / ``init.svc_debug_pid.*`` 是 init 的服务运行状态
# （``init.svc.nemuinit=running`` 之类），由系统维护，resetprop 删了也会立刻回来。
# 把它们算进"厂商残留"只会让自检永远清不了零分（2026-11-04 实机踩到）。
_NONPROP_PREFIX = ("init.svc.", "init.svc_debug_pid.", "ro.boottime.",
                   "sys.", "dev.")


def _is_vendor_prop(key: str, value=None) -> bool:
    """这个键是不是"厂商注入的可清理 prop"（而不是系统运行态）。

    给了 ``value`` 时**只把"值非空"算作暴露面**：清空后的键还在
    （``[nemud.player_engine]: []``），但它已经不再自报"我是 MUMU15"，
    若仍算残留，自检就永远到不了满分（2026-11-04 实机踩到）。
    """
    k = str(key or "").lower()
    if not k or k.startswith(_NONPROP_PREFIX):
        return False
    if not any(p in k for p in EMU_PROP_PAT):
        return False
    if value is not None and not str(value).strip():
        return False
    return True

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
def _fmt_hidden_note(items) -> str:
    """把「存在但 App 摸不到」的条目渲染成日志尾巴（纯函数，便于钉测试）。

    这类条目**不参与扣分**，所以它们不解释分数缺口；单独列出来只为两件事：
      1) 证明探针真的在工作，而不是恒假的死件（§6.38：`test -e` 三段 argv
         写法让 root 探测 55 轮全判"不存在"，操作员看到的一直是假清白）；
      2) 挡住「看到 /data/adb/magisk 就想去删」的误操作——自检跑在 `adb root`
         下能看到 App 永远进不去的目录（`/data/adb` 是 0700），今天差点为此
         删掉 resetprop 的工位，白损能力。
    措辞必须把「未计入」和「别去动它们」都说清；空列表返回空串，
    不能印出「另有 0 条」这种噪音。
    """
    n = len(items or [])
    if not n:
        return ""
    return "；另有 %d 条存在但 App 摸不到，未计入（别去动它们）" % n


def detect(dev) -> dict:
    """采集当前设备的 root / 模拟器证据（只读，不改任何东西）。

    返回 ``{"root": [...], "emulator": [...], "magisk": {...},
    "unfixable": [...], "score": int}``。``score`` 100 = 已知证据全清。
    """
    # **`score` 初值不能是 0**（2026-11-04 实机踩到）。
    #
    # 原来是 `score: 0` + 设备读不到时直接 return，于是返回
    # ``{"score": 0, "root": [], "emulator": [], "error": "device offline"}``，
    # 而 prepare 的日志把它渲染成：
    #
    #     [android] root/模拟器隐藏：1 条动作，自检 0 分（剩余：无）
    #
    # **"0 分"和"无残留"是互相矛盾的两句话**：0 分的意思是"检测到 13 条以上
    # 证据"，而它真实的意思是"这条 adb 压根没读到"（采集进行中端口被占用时
    # 很常见）。操作员看到"自检 0 分"会以为隐藏彻底失败、去折腾设备，
    # 实际什么坏事都没发生。
    #
    # `None` = "未知"，消费方本来就按未知处理：`riskscore` 是
    # `if val is None: continue`（不会因为读不到而加风险分），
    # `app_base` 用 `isinstance(数值)` 过滤。
    rep = {"root": [], "emulator": [], "magisk": {}, "unfixable": [],
           "score": None, "debuggable": False,
           # 存在、但 App 摸不到（父目录 0700 之类）→ 列出、**不扣风险分**
           "hidden_from_app": []}
    # App 可见性判定的权限位缓存：一次 detect 内多条路径共享，省 adb 往返
    _see = {}
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
                    if _is_vendor_prop(k, v))
    if blob.strip():
        rep["emulator"].append("props:%s" % blob[:200])

    # --- 文件系统层（与 props 独立，props 干净也可能命中）---
    #
    # 逐路径判存在走**共享实现** `fingerprint._exact_path_exists`。
    # 这里错过两次、方向相反，成因都是同一个 —— **adb 把命令行按空格拆开**
    # 送进设备 shell，所以探测命令里不许出现 `-c`/`&&`/`||`/`|`/引号：
    #   ① 多条 `ls /a /b /c`：参数里的目录被列**内容** → 冒出 17 条幽灵残留，
    #      自检被扣到 0 分（操作员以为隐藏失败，其实是误报）。
    #   ② 改用 `sh -c "test -e X && echo TM_YES || echo TM_NO"`：设备实际执行
    #      `sh -c test`（内层拿不到参数 → **恒假**）+ 外层 `|| echo TM_NO`
    #      → **任何路径都判"不存在"**。于是"root 痕迹: []、自检 100 分"
    #      **从未被验证过**（用 `/system/bin/sh` 自测立刻暴露）。
    #      假阴性比假阳性危险：假阳性吵人，假阴性让人放心。
    #
    # **并且按 App 的权限判存在**（见 `app_can_see`）：自检跑在 `adb root`
    # （uid=0）下，能看到 App 永远进不去的目录。实测 `/data/adb` 是
    # `drwx------ 0700` → App 连 traverse 都做不到，`/data/adb/magisk`
    # 对它**等于不存在**；而 `/data/local/tmp` 是 `0771`（others 有 x），
    # 放那儿的那份才真会被 stat 到。看不见的不扣风险分，但如实列出。
    # 这条判据挡住了一次误操作：否则会为消一条 App 看不见的"泄漏"
    # 去删 resetprop 的工位，白损能力。
    _FS_ROOTS = ("/system/bin/su", "/system/xbin/su", "/sbin/su",
                 "/system/app/Superuser.apk", "/data/adb/magisk")
    for p in _FS_ROOTS:
        if not _exact_path_exists(dev, p):
            continue
        if app_can_see(dev, p, _see):
            rep["root"].append("fs:%s" % p)
        else:
            rep["hidden_from_app"].append("fs:%s" % p)
    if (_exact_path_exists(dev, "/dev/qemu_pipe")
            and app_can_see(dev, "/dev/qemu_pipe", _see)):
        rep["emulator"].append("fs:/dev/qemu_pipe")

    # 模拟器厂商的共享目录：App 一个 File.exists() 就能判定，props 改不掉。
    # `/mnt/shared` 实测 `drwxrwxr-x`（others 有 r-x）→ **App 真能 stat 到**，
    # 所以这条是必须处理的暴露面：只能在 MuMu 设置里关掉文件夹共享。
    for p in ("/mnt/shared", "/sdcard/MuMuSharedFolder", "/sdcard/MuMu"):
        if _exact_path_exists(dev, p) and app_can_see(dev, p, _see):
            rep["emulator"].append(
                "shared:%s（MuMu 共享目录，需在模拟器设置里关掉）" % p)

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
    # 厂商 props：**删不掉就清空**（2026-11-04 实机实测）
    #
    # MuMu 会注入一整套 `nemud.*`，里面直接自报家门：
    #     nemud.player_engine      = MUMU15      ← 比机型字段更致命
    #     nemud.player_architecture= x86_64
    #     nemud.device.id          = <手机号/设备号>
    # App 一个 getprop 就能确认"这是 MuMu 15"。
    #
    # 实测：这些键**不是 ro.\***，`setprop` 可以把值写成空（键仍在，值为 `[]`）。
    # 风控 SDK 判的是"值里有没有内容"，所以**清空就够了**——不必纠结"键还在"。
    # 有 Magisk 时优先 `resetprop --delete`（连键一起消掉，更干净）。
    vendor_keys = []
    for line in _text(_call(dev, "shell", "getprop")).splitlines():
        if "]: [" not in line:
            continue
        key = line.strip()[1:].split("]: [")[0]
        val = line.strip()[1:].partition("]: [")[2].rstrip("]")
        # 只碰**厂商注入的 prop**；`init.svc.*` 之类是系统运行态，删不掉也不该算残留
        # **值已空的跳过**：清过一次就不用每轮再清 41 次（省 adb 往返）。
        if _is_vendor_prop(key, val):
            vendor_keys.append(key)
    readonly_keys = []
    for key in vendor_keys:
        if rp:
            script.append("%s --delete %s >/dev/null 2>&1 && echo 'DEL %s'"
                          % (rp, _q(key), key))
        elif key.startswith("ro."):
            # **`ro.*` 没有 resetprop 一定改不动**：`setprop` 会返回 0（成功）
            # 但值不变——第 3 轮就吃过"命令报成功、读回没变"的亏。
            # 原来这里照样 `echo CLR`，于是日志报"已清空 42 条"而实际一条没清
            # （2026-11-04 实机复核：清完 `ro.nemu` 仍是 1）。
            # 现在明确列进"改不动"，让操作员知道该装 Magisk，而不是以为清干净了。
            readonly_keys.append(key)
        else:
            # 非 ro.* 可以清：setprop 写空串（值空即无信息量）
            script.append("setprop %s '' >/dev/null 2>&1 && echo 'CLR %s'"
                          % (_q(key), key))
    out = _text(as_root(dev, "; ".join(script) or "true"))
    ok_keys = [ln[3:].strip() for ln in out.splitlines()
               if ln.strip().startswith("OK ")]
    del_keys = [ln[4:].strip() for ln in out.splitlines()
                if ln.strip().startswith("DEL ")]
    clr_keys = [ln[4:].strip() for ln in out.splitlines()
                if ln.strip().startswith("CLR ")]
    acts.append({"cmd": "props:%d set / %d deleted / %d cleared"
                        % (len(ok_keys), len(del_keys), len(clr_keys)),
                 "ok": bool(ok_keys or del_keys or clr_keys),
                 "why": "清 root/厂商 props（厂商键删不掉时清空值）"})
    if readonly_keys:
        # 如实报"这些改不动"，并在 why 里点明根治手段——不要让人以为清了
        acts.append({"cmd": "props-readonly:%d" % len(readonly_keys),
                     "ok": False,
                     "why": "ro.* 只读改不动（需 Magisk resetprop）：%s"
                            % ", ".join(readonly_keys[:6])})
    if not rp:
        acts.append({"cmd": "resetprop", "ok": False,
                     "why": "没有 Magisk：ro.* 只读改不动；nemud.* 等可写键已改用清空"})

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


# **`adb root` 之后一定会出现的运行态 prop**：真机上没有"adbd 是 root"这条，
# 所以 detect() 把它算作 root 证据；而它**不在厂商键命名空间里**
# （`_is_vendor_prop` 判 False），于是 hide() 从来不清它 ——
# 检测报了个自己不管的洞（2026-11-04 实测：自检因此长期停在 84 分）。
# 实测删得掉且会保持（delete 后 20s 仍为空）：adbd 启动时由 init 置位，
# 之后没人再写，所以清一次能撑到 adbd 下次重启。
#
# **为什么可以放心清（2026-11-04 实测，此前这是个未验证的顾虑）**：
# 这条标记要清、又必须留着 root 跑 resetprop（清 `ro.nemu`，实测 Ctrip SDK
# 读到它就返回 50003），直觉上像是个二选一的取舍。实测不是：
#
#   setprop service.adb.root 0 → getprop 回读 '0'
#                              → `adb shell id` 仍是 **uid=0(root)**
#                              → `resetprop --delete`+set 探针仍可用（读回 'tmprobe62'）
#                              → 自检 **76 → 84**，root 归空
#
# 也就是说这个属性只是**状态记录**，adbd 并不监听它，改它不会把通道切断。
# 所以「既要 root 通道又不露 root 标记」不是取舍，两头都能要。
# 反过来提醒：真把 adbd 重启回非 root 时（实例重启后就是），
# 通道会断，那时必须重新 `adb root` —— 与本条无关，别混为一谈。
_RUNTIME_ROOT_PROPS = ("service.adb.root",)


def refresh(dev, config: dict = None, logger=None) -> dict:
    """**轻量重清**：只把厂商/运行态 props 再删一遍，不做贵的动作。

    为什么必须有这一步（2026-11-04 实测）：
    `prepare()` 按 `boot_id` 标记**每个 boot 只跑一次**，
    但 MuMu 的 `nemuinit` 守护进程**会在几分钟内把 `nemud.*` 重新写回来**——

    ```
    19:19  stealth 跑完   → 含 nemu 的 prop 行数 0
    19:26  （没再动过）   → 含 nemu 的 prop 行数 57
    ```

    也就是说：同一 boot 内的后续轮次，模拟器标记是**裸露**的。
    而一次轮 ≈ 30 分钟，正好被写回覆盖。

    所以"按 boot 一次"对 props 是不够的，但"每轮全量 hide()"又太贵
    （denylist 要读 sqlite、快照要抓 logcat）。折中：**props 单独做成廉价重清**，
    每轮都跑；贵的动作仍按 boot 一次。

    成本：1 条 `getprop` + 命中几条就几条 `resetprop --delete`。
    实测清空后 45 秒内不回升，所以每轮一次是够的。
    """
    from .fingerprint import _magisk, as_root, props_of, _text
    rep = {"ok": False, "deleted": [], "detail": ""}
    props = props_of(dev)
    if not props:
        rep["detail"] = "设备没读到 props，跳过重清"
        return rep
    targets = []
    for k, v in props.items():
        v = str(v or "")
        if not v:
            continue                     # 已经是空值：不用重复清
        if _is_vendor_prop(k, v) or k in _RUNTIME_ROOT_PROPS:
            targets.append(k)
    if not targets:
        # **没东西要清时不许去探测 magisk**：`_magisk()` 带 delete-then-set
        # 探针（要验"真能改 ro.*"），一次 4~5 条 adb。而 refresh() 是
        # **每轮都跑**的 —— 在干净设备上白烧这些往返，等于把"廉价重清"
        # 做成不廉价（2026-11-04 被自己的测试抓到）。
        rep["ok"] = True
        rep["detail"] = "无残留 props"
        return rep
    rp = _magisk(dev)
    # `rp` 可能是 "/path/magisk resetprop"（一整串）或 "/path/resetprop"。
    # **必须拆成独立参数传**：塞进单个字符串会被 Windows 的命令行把引号吃掉
    # （本轮已在 `sh -c "test -e '...'"` 上踩过同一个坑）。
    # prop 键名都是纯标识符，本来也不需要引号。
    #
    # **一条脚本批量做完**：逐条发就是每个键 2 个 adb 往返（删 + 读回），
    # 厂商键有几十条就是上百次往返；放进 as_root 一次执行只要一次。
    # 每个键自己 echo 一个标记，读回为空才算真删掉（命令返回码不可信，
    # `setprop ro.*` 一直是"返回 0 但值不变"）。
    lines = []
    for k in targets:
        if rp:
            # 用 %s 直接展开（键名是纯标识符，不需要引号）
            lines.append(
                "%s --delete %s >/dev/null 2>&1; "
                "test -z \"$(getprop %s)\" && echo 'GONE %s'"
                % (rp, k, k, k))
        else:
            lines.append(
                "setprop %s '' >/dev/null 2>&1; "
                "test -z \"$(getprop %s)\" && echo 'GONE %s'"
                % (k, k, k))
    out = str(_text(as_root(dev, "; ".join(lines) or "true")) or "")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("GONE "):
            rep["deleted"].append(line[5:].strip())
    rep["ok"] = len(rep["deleted"]) == len(targets)
    rep["detail"] = "重清 %d/%d 条 props" % (len(rep["deleted"]), len(targets))
    if logger and rep["deleted"]:
        logger.info("[android] 厂商 props 已被写回，重清 %d 条：%s",
                    len(rep["deleted"]),
                    "、".join(rep["deleted"][:3]) +
                    ("…" if len(rep["deleted"]) > 3 else ""))
    return rep


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
        # **本 boot 做过全量隐藏，不等于现在还是干净的**：`nemuinit` 会在
        # 几分钟内把 `nemud.*` 写回来（实测 19:19 归零 → 19:26 又 57 行）。
        # 所以这里仍然要跑一次**廉价重清**，只清 props、不碰 denylist/快照。
        rf = refresh(dev, config, logger)
        return {"ok": True, "skipped": "done this boot", "actions": [],
                "refresh": rf}

    rep = hide(dev, packages=packages, config=config)
    rep["verify"] = verify(dev, packages)
    # 用统一的 write_remote：原来这里是 `sh -c "echo X > path"`，
    # 实测在 Windows 上**静默不生效**（写进去是空的），于是这个
    # "本 boot 已完成"的门槛**从来没成立过** —— hide() 每轮全量重跑
    # （denylist 读写 sqlite + 抓 logcat 快照），既慢又没人发现。
    from .fingerprint import write_remote
    write_remote(dev, mark_path, boot or "1")
    rep["ok"] = True
    if logger:
        d = rep.get("detect") or {}
        # `hidden_from_app` 是**存在但 App 摸不到**的东西（父目录 0700 之类），
        # 不参与扣分，所以它不解释分数缺口；列出来是为了两件事：
        #   1) 让操作员知道探针确实在工作（不是"什么都没查到"的死件）；
        #   2) 挡住"看到 /data/adb/magisk 就想去删"的误操作——今天差点
        #      为此删掉 resetprop 的工位，白损能力（见 §6.38）。
        _tail = _fmt_hidden_note(d.get("hidden_from_app"))
        logger.info(
            "[android] root/模拟器隐藏：%d 条动作，自检 %s（剩余：%s）%s",
            len(rep.get("actions") or []),
            ("%d 分" % d["score"]) if isinstance(d.get("score"), int)
            else "未知（设备没读到）",
            ", ".join([x for x in (d.get("root") or []) +
                       (d.get("emulator") or [])][:4]) or "无",
            _tail)
    return rep


# ---------------------------------------------------------------------------
# 换身份时的 App 侧清理
# ---------------------------------------------------------------------------
# 这些 App 会把自己生成的设备 ID 落盘（utdid/umid/guid/deviceId）。换了
# android_id 却留着旧文件，等于「新设备 + 旧设备 ID」——比不换更可疑。
_ID_PATTERN = "utdid|umid|deviceId|device_id|guid|android_id|oaid|imei"


# 真正"存设备 ID"的文件长这样：`*id*.xml`、`*guid*`、`*utdid*`…；
# 而业务配置（chat_config.xml）与库（*.so）只是**内容里偶尔出现**这些子串。
_ID_NAME_HINT = ("utdid", "umid", "deviceid", "device_id", "guid", "android_id",
                 "oaid", "imei", "id_")
_ID_SAFE_MAX_BYTES = 262144          # 真 ID 文件都很小；大文件一律不碰


def _id_files(dev, pkg: str) -> list:
    """列出**该删的**设备 ID 文件（r1063 T74 收紧）。

    三道闸（都是这次误删换来的）：
      1. 只看 `shared_prefs/`，**不碰 `files/`**（那里放的是解包出的 .so、缓存）；
      2. 文件名要像 ID 容器（`*utdid*` `*guid*` `*deviceid*` …），
         或内容里出现 `key=值` 形态的命中；光是 grep 命中不算；
      3. 大小 > 256KB 的跳过（`ctrip_package_pkg_sp` 那种 4MB 文件不是 ID 文件）。
    """
    base = "/data/data/%s/shared_prefs" % pkg
    # ① 文件名直判（最可靠，不依赖内容）
    by_name = _text(as_root(
        dev, "ls %s 2>/dev/null | grep -iE '%s' | head -40 || true"
             % (base, "|".join(_ID_NAME_HINT))))
    picked = []
    for ln in by_name.splitlines():
        n = ln.strip()
        if n:
            picked.append("%s/%s" % (base, n))
    # ② 内容判：只收 shared_prefs 下、体积小的 xml
    by_body = _text(as_root(
        dev, "grep -rlE '%s' %s 2>/dev/null | head -40 || true"
             % (_ID_PATTERN, base)))
    for ln in by_body.splitlines():
        p = ln.strip()
        if not p or p in picked or not p.endswith(".xml"):
            continue
        try:
            sz = int(_text(as_root(dev, "stat -c %%s '%s' 2>/dev/null || echo 0"
                                   % p)).strip() or 0)
        except (TypeError, ValueError):
            sz = 0
        if sz and sz <= _ID_SAFE_MAX_BYTES:
            picked.append(p)
    # ③ 兜底：绝不返回库/可执行/大文件
    return [p for p in picked
            if not p.endswith((".so", ".dex", ".jar", ".apk", ".oat", ".vdex"))]


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
