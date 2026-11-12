# -*- coding: utf-8 -*-
"""飞猪 App「安全页白屏」处置工具。

背景（2026-11-06 实测）：飞猪 App 被阿里安全 SDK 拦时，前台是
`com.alibaba.wireless.security...ContainerActivity`，画面是**纯白**
——没有可点的验证码、没有滑块，所以"手动过一下"不成立。
罚则通常随设备风险分衰减，也可能存在 App 私有数据里。

本工具只做三件事，都需显式选择：
  --check    只看状态（默认，无副作用）
  --relaunch 冷启一次再看（无副作用，用来确认是否已自然解封）
  --reset    清 App 数据后再冷启（**会退出登录**，必须加 --yes 确认）

用法::

    python scripts/fliggy_app_reset.py            # 只看状态
    python scripts/fliggy_app_reset.py --relaunch # 冷启一次再看
    python scripts/fliggy_app_reset.py --reset --yes   # 清数据（会掉登录！）
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PKG = "com.taobao.trip"
_SECURITY_MARK = "alibaba.wireless.security"
_BLOCK_HINTS = ("访问被拒绝", "安全验证", "环境异常", "操作过于频繁")


def _device():
    from core.android.device import AdbDevice
    adb = os.environ.get("TM_ADB") or resolve_adb_path()
    serial = os.environ.get("TM_SERIAL") or "127.0.0.1:16384"
    return AdbDevice(adb, serial)


def resolve_adb_path() -> str:
    """找 adb：优先项目配置，其次 MuMu 自带。"""
    try:
        from core.android.config import normalize
        cfg = normalize(None)
        p = (cfg or {}).get("adb_path") or ""
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    for cand in (r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
                 r"C:\Program Files\Netease\MuMu\nx_main\adb.exe"):
        if os.path.exists(cand):
            return cand
    return "adb"


def status(dev):
    """当前 Activity 是否安全容器（**只有这一步看不出"机票模块被封"**）。"""
    act = ""
    try:
        act = str(dev.current_activity() or "")
    except Exception:
        pass
    blocked = _SECURITY_MARK in act or "ContainerActivity" in act
    return act, blocked


def flight_module_ok(dev, wait_s=14):
    """**真正**的判据：点首页「机票」宫格，看落点是不是表单。

    首页是本地页面，永远能开；拦截发生在点进机票模块时（实测
    2026-11-06：冷启落 HomeActivity 看似正常，点「机票」立刻回
    `ContainerActivity`）。只看 Activity 会给出**误报的"已恢复"**。
    """
    import re
    import time
    xml = ""
    try:
        xml = str(dev.dump() or "")
    except Exception:
        pass
    tile = None
    for m in re.finditer(r"<node[^>]*>", xml):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        ds = re.search(r'content-desc="([^"]*)"', tag)
        s = ((t.group(1) if t else "") or (ds.group(1) if ds else "")).strip()
        if s != "机票":
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        y1 = int(b.group(2))
        if y1 < 300:            # 顶部营销 banner 里的「机票」不算
            continue
        cx = (int(b.group(1)) + int(b.group(3))) // 2
        cy = (y1 + int(b.group(4))) // 2
        if tile is None or cy < tile[1]:
            tile = (cx, cy)
    if tile is None:
        return False, "首页找不到「机票」宫格"
    try:
        dev.tap(*tile)
    except Exception:
        return False, "点击机票失败"
    time.sleep(wait_s)
    act = ""
    try:
        act = str(dev.current_activity() or "")
    except Exception:
        pass
    if _SECURITY_MARK in act or "ContainerActivity" in act:
        return False, ("机票模块仍被拦（%s）" % act.split("/")[-1][:40])
    if "Flutter" in act or "Trip" in act:
        return True, "机票表单可达（%s）" % act.split("/")[-1][:40]
    return False, "点机票后落点未知（%s）" % (act.split("/")[-1][:40] or "空")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--relaunch", action="store_true",
                    help="冷启一次再检查（无副作用）")
    ap.add_argument("--reset", action="store_true",
                    help="清 App 数据后冷启（会退出登录，需 --yes）")
    ap.add_argument("--yes", action="store_true", help="确认执行 --reset")
    args = ap.parse_args()

    if args.reset and not args.yes:
        print("拒绝执行：--reset 会清掉飞猪 App 数据（**会退出登录**）。\n"
              "确认请加 --yes：  python scripts/fliggy_app_reset.py "
              "--reset --yes")
        return 2

    dev = _device()
    act, blocked = status(dev)
    print("当前前台: %s" % (act.split("/")[-1][:60] or "(未知)"))
    print("判定: %s" % ("被安全 SDK 拦截（白屏）" if blocked else "未见拦截"))

    if args.reset:
        print("→ 清数据（pm clear %s）…" % PKG)
        dev._sh("shell", "pm", "clear", PKG)
        time.sleep(2)
    elif args.relaunch:
        print("→ 冷启一次…")
    elif not blocked:
        print("无需处理。")
        return 0
    else:
        print("\n可选：\n"
              "  --relaunch  冷启一次看是否已自然解封（无副作用）\n"
              "  --reset --yes  清数据（**会退出登录**，能立刻解除）\n"
              "也可以就等它冷却（通常几小时到一天）。")
        return 1

    dev._sh("shell", "am", "force-stop", PKG)
    time.sleep(2)
    dev._sh("shell", "monkey", "-p", PKG, "-c",
            "android.intent.category.LAUNCHER", "1")
    time.sleep(16)
    act2, blocked2 = status(dev)
    print("冷启后前台: %s" % (act2.split("/")[-1][:60] or "(未知)"))
    if not blocked2:
        ok2, why2 = flight_module_ok(dev)
        print("机票模块探测: %s（%s）" % ("可达" if ok2 else "被拦", why2))
        if ok2:
            print("已恢复：机票表单可达")
            print("下一步可跑验证：python _scratch/probe_fg_lowfare.py")
            return 0
        blocked2 = True
    if blocked2:
        print("仍然被拦。建议：等冷却（几小时~一天）后重试；"
              "或再执行 --reset --yes 并使用更干净的网络出口。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
