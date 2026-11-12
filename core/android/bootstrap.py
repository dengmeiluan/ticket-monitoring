# -*- coding: utf-8 -*-
"""首次引导：检测 Android 运行时状态，给出可执行的下一步。

设计原则（对齐 `ensure_chromium` 的按需模式，但更保守）：
  * **chromium 是 ~120MB 能静默下，MuMu 是 ~7GB + 需要一次管理员确认**，
    所以这里只做「检测 + 明确指引」，绝不偷偷替用户装一个大软件。
  * 引导必须是**可执行的一条路**：告诉用户点哪里、装完回来看什么。
  * 未启用 App 渠道时**完全不执行**（不探测磁盘、不跑子进程）。
"""
from __future__ import annotations

import os
import re
import sys

from .config import normalize, resolve_install_dir
from .mumu import MuMuManager

# MuMu 官方下载入口（与本项目实测一致的渠道）
MUMU_DOWNLOAD_HINT = "https://mumu.163.com/"

def _apk_step_label() -> str:
    """「安装 App」这一步的文案按**已注册的 App 渠道**拼，不写死智行。

    原先写死「安装智行 App」，接入去哪儿 App 后这一步仍只报智行——
    用户看到「五步已完成」却不知道去哪儿 App 是否也装上了（实际安装
    检查早已遍历 APP_CHANNELS）。名字从 `core.channels` 派生（单一源）。
    """
    try:
        from core.channels import APP_CHANNELS, plat_cn
        names = [plat_cn(p) for p in APP_CHANNELS]
    except Exception:
        names = []
    return ("安装 App 渠道（%s）" % " / ".join(names)
            if names else "安装 App 渠道")


# 首次引导的阶段（与 UI 进度态一一对应）
STEPS = (
    ("check", "检测 Android 运行时"),
    ("install", "安装 MuMu 模拟器"),
    ("boot", "启动并等待实例就绪"),
    ("apk", _apk_step_label()),
    ("verify", "验证可采集"),
)


# 伪装检查项：与 scripts/device_hardening.py 的体检同源（那边是权威实现，
# 这里只做**读回**的轻量子集，供 UI/CLI 引导用；真正的落地与全量体检在脚本里）。
HARDENING_HINT = "python scripts/setup_device.py --apply --reboot"


# 一次往返取全部伪装信息（单条 shell 脚本，避免多次 adb round-trip）
PROBE_SCRIPT = r"""
echo "enforce=$(getenforce 2>/dev/null)"
echo "cpu=$(head -2 /proc/cpuinfo 2>/dev/null | tr '\n' ' ')"
ZP=$(pidof zygote64 2>/dev/null | cut -d' ' -f1)
echo "zpid=$ZP"
echo "zyg=$( [ -n "$ZP" ] && grep -c zygisk /proc/$ZP/maps 2>/dev/null )"
echo "cloak=$(ls /data/adb/modules/mumu_cloak/zygisk 2>/dev/null | head -1)"
echo "cloak_off=$(ls /data/adb/modules/mumu_cloak/disable 2>/dev/null)"
"""


def parse_probe(text: str) -> dict:
    """把 PROBE_SCRIPT 的输出解析成检查结果。纯函数，便于单测。

    返回 {ok, checks, missing, next}；拿不到关键行时 ok=None（未知）。
    """
    vals = {}
    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r"^([a-z_]+)=(.*)$", line)
        if m:
            vals[m.group(1)] = m.group(2).strip()

    if "enforce" not in vals:
        return {"ok": None, "checks": [], "missing": [],
                "next": "读不到设备状态（adb 未就绪），伪装无法确认"}

    checks, missing = [], []

    enf = vals.get("enforce", "")
    ok = (enf == "Enforcing")
    checks.append(("SELinux 视图", ok, enf or "(空)"))
    if not ok:
        missing.append("SELinux 视图=%s" % (enf or "空"))

    cpu = vals.get("cpu", "")
    ok = ("CPU implementer" in cpu) or ("BogoMIPS" in cpu)
    checks.append(("/proc/cpuinfo ARM 视图", ok,
                   "已伪装" if ok else "仍是宿主 CPU"))
    if not ok:
        missing.append("cpuinfo 未伪装")

    zyg = vals.get("zyg", "")
    ok = bool(zyg) and zyg.isdigit() and int(zyg) > 0
    checks.append(("Zygisk 注入", ok,
                   "zygote=%s 命中=%s" % (vals.get("zpid") or "?", zyg or "0")))
    if not ok:
        missing.append("Zygisk 未注入")

    cloak_ok = bool(vals.get("cloak")) and not vals.get("cloak_off")
    checks.append(("mumu_cloak", cloak_ok,
                   "启用" if cloak_ok else "未安装或已停用"))
    if not cloak_ok:
        missing.append("mumu_cloak 未启用")

    if missing:
        return {"ok": False, "checks": checks, "missing": missing,
                "next": "设备伪装未就位：%s；执行 %s"
                        % ("、".join(missing), HARDENING_HINT)}
    return {"ok": True, "checks": checks, "missing": [], "next": ""}


def probe_hardening(dev) -> dict:
    """读回设备伪装状态（只读、绝不抛异常）。"""
    try:
        out = dev.run_script(PROBE_SCRIPT)
    except Exception:
        return {"ok": None, "checks": [], "missing": [],
                "next": "伪装检查异常，未能确认"}
    if not out:
        return {"ok": None, "checks": [], "missing": [],
                "next": "设备无响应，伪装无法确认"}
    return parse_probe(out)


def _with_hint(st: dict) -> dict:
    """把"伪装缺项"的修复提示并到 `next` **最前面**（原有原因保留在后面）。

    为什么要统一在这里合并：`next` 会在 `status()` 后半段被"缺 App / 待验证"
    等分支重新赋值，先前写进去的伪装提示就被覆盖了——那正是"设备起来了但
    伪装没做，用户却看不到任何提示"的成因。
    """
    hd = st.get("hardening") or {}
    if hd.get("ok") is False and hd.get("next"):
        base = st.get("next") or ""
        st["next"] = hd["next"] + (("\n" + base) if base else "")
    return st


def status(cfg: dict, evidence=None) -> dict:
    """返回引导状态。未启用时立刻返回 disabled，不碰任何外部资源。"""
    android = (cfg or {}).get("android") or {}
    if not (android.get("enabled") or False):
        return {"state": "disabled", "detail": "App 渠道未启用",
                "steps": [], "next": ""}

    ac = normalize(android)
    install_dir = resolve_install_dir(ac)

    if not install_dir:
        return {
            "state": "not_installed",
            "detail": "未检测到 MuMu 模拟器（约 7 GB，需一次管理员确认）",
            "steps": [{"key": k, "label": v,
                       "done": k == "check"} for k, v in STEPS],
            "next": f"从 {MUMU_DOWNLOAD_HINT} 下载安装 MuMu 12，"
                    f"装完后回到本页点「重新检测」",
        }

    mgr = MuMuManager(install_dir=install_dir, vm_index=ac.vm_index,
                      timeout=ac.action_timeout_s)
    if not mgr.available():
        return {"state": "error", "detail": f"安装目录不完整：{install_dir}",
                "steps": [], "next": "检查 android.install_dir 配置"}

    info = mgr.info() or {}
    started = bool(info.get("is_android_started"))
    adb_port = info.get("adb_port") or ""

    if not started:
        return {
            "state": "stopped",
            "detail": "MuMu 已安装，实例未启动",
            "steps": [{"key": k, "label": v, "done": k in ("check", "install")}
                      for k, v in STEPS],
            "next": "启动实例后可开始采集（首轮会自动拉起）",
        }

    state = {
        "state": "ready",
        "detail": f"实例已就绪 · adb {info.get('adb_host_ip', '127.0.0.1')}"
                  f":{adb_port}",
        "steps": [{"key": k, "label": v,
                   "done": k in ("check", "install", "boot")}
                  for k, v in STEPS],
        "next": "",
    }

    # 后两步必须真的检查：只看「模拟器起来了」就宣布 ready，会让
    # 「安装智行 App / 验证可采集」永远不勾——用户照引导走完却发现
    # 清单还是未完成，而实际 App 早就装好且在采数（真机实测如此）。
    # 包名从渠道注册表派生，不在这里另写一份（同项目「名字单一源」约定）。
    plats = []
    try:
        from crawlers import APP_CHANNELS, REGISTRY
        from core.channels import plat_cn
        plats = [(p, getattr(REGISTRY.get(p), "package", "") or "")
                 for p in APP_CHANNELS]
        plats = [(p, pkg) for p, pkg in plats if pkg]
    except Exception:
        plats = []
        plat_cn = lambda p: p  # noqa: E731
    missing, installed = [], False
    dev = None
    try:
        from .device import AdbDevice
        dev = AdbDevice(mgr.adb_path, mgr.adb_serial(),
                        timeout=ac.action_timeout_s)
        # **两个 App 渠道都要装上**才算这一步完成：文案点了两个名字、
        # 实际只装一个却打勾，用户会以为去哪儿 App 也装好了。
        missing = [(p, pkg) for p, pkg in plats
                   if not dev.app_installed(pkg)]
        installed = bool(plats) and not missing
    except Exception:
        missing = []
        installed = False
    # 伪装探针（只读，失败不阻断）。dev 拿不到就明确"未确认"，不猜——
    # 之前这里直接 probe_hardening(dev)，dev 未定义时抛 NameError 被
    # 吞成 ok=None，UI 上表现为"伪装那栏不显示"（静默失效）。
    if dev is None:
        state["hardening"] = {"ok": None, "checks": [], "missing": [],
                              "next": "设备句柄不可用，伪装无法确认"}
    else:
        try:
            state["hardening"] = probe_hardening(dev)
        except Exception:
            state["hardening"] = {"ok": None, "checks": [], "missing": [],
                                  "next": "伪装检查异常，未能确认"}

    done = {"check", "install", "boot"}
    if installed:
        done.add("apk")
    state["steps"] = [{"key": k, "label": v, "done": k in done}
                      for k, v in STEPS]
    if not installed:
        if missing:
            names = "、".join("%s（%s）" % (plat_cn(p), pkg)
                             for p, pkg in missing)
            state["next"] = ("实例已就绪，还缺 App：%s——"
                             "在模拟器里装一次即可" % names)
        elif plats:
            state["next"] = "实例已就绪，但读不到 App 安装状态（adb 查询失败）"
        else:
            state["next"] = "实例已就绪，但没有注册任何 App 渠道"
        return _with_hint(state)
    # 「验证可采集」只认**真的采到过数**：光装着 App 不等于能采
    # （登录墙、风控都会让采集失败）。evidence 回调由调用方注入，
    # 不注入就保持未勾选——不猜。
    verified = False
    try:
        verified = bool(evidence() if evidence else False)
    except Exception:
        verified = False
    if verified:
        done.add("verify")
        state["steps"] = [{"key": k, "label": v, "done": k in done}
                          for k, v in STEPS]
        state["next"] = "五步已完成：App 渠道已可用"
    else:
        _names = (" / ".join(plat_cn(p) for p, _ in plats)
                  if plats else "App 渠道")
        state["next"] = ("已就绪：在 配置 · 渠道登录 里登录 %s；"
                         "登录后跑一轮采集即会点亮「验证可采集」" % _names)
    return _with_hint(state)


def ensure_android_runtime(platforms, cfg, logger=None) -> str:
    """启动时调用：只在启用 App 渠道时检查，返回一句可打印的状态。

    与 `ensure_chromium` 的差别：**不自动下载**。MuMu 体积与权限要求
    都不适合静默安装，越界替用户装会被当成流氓行为。
    """
    from crawlers import APP_CHANNELS
    wanted = set(platforms or []) & set(APP_CHANNELS)
    if not wanted:
        return ""

    st = status(cfg)
    state = st["state"]
    if state == "disabled":
        msg = ("已勾选 App 渠道但「Android 真机通道」未启用——"
               "到 配置 · 全局参数 → Android 真机通道 打开总开关")
    elif state == "not_installed":
        msg = f"未检测到 MuMu：{st['next']}"
    elif state == "ready":
        msg = st["detail"]
        # 实例起来了但**伪装没就位**时，必须把修复命令带到启动日志里：
        # 否则用户看到"已就绪"就以为万事大吉，采集却一直失败。
        _hd = st.get("hardening") or {}
        if _hd.get("ok") is False:
            msg = (msg + "；但" + (_hd.get("next") or "")).strip("；")
    else:
        msg = f"{st['detail']}：{st.get('next', '')}".strip("：")

    if logger is not None:
        try:
            (logger.warning if state in ("disabled", "not_installed")
             else logger.info)("[app] %s", msg)
        except Exception:
            pass
    return msg
