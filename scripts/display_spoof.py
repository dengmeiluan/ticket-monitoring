# -*- coding: utf-8 -*-
"""屏幕伪装（分辨率/DPI）+ 坐标换算的**安全**入口。

为什么需要单独的 CLI：改分辨率是**唯一会直接把 App 渠道弄瘫**的操作——
所有写死的坐标都按 900×1600 竖屏。所以它必须满足三个条件才允许执行：

1. **有换算**：改完立刻 `dev.set_design(900, 1600)`，让写死的常量仍指向正确
   位置（``AdbDevice`` 会把设计坐标乘上比例）；
2. **有回滚**：``--restore`` 一条命令回到出厂（``wm size/density reset``），
   并且脚本在异常时也会尽力回滚；
3. **有验证**：改完先 dump 一次，确认「界面还在、不是白屏」，再报成功。

用法：

    python scripts/display_spoof.py                 # 看现状（只读）
    python scripts/display_spoof.py --scale 1.2     # 等比放大到 1080x1920
    python scripts/display_spoof.py --size 1080x1920
    python scripts/display_spoof.py --restore       # 回滚

⚠ 改分辨率**必须挑采集空窗**（日志出现「本轮扫描结束」后）。脚本不会替你
判断空闲，但它会明确打印「当前是否推荐执行」。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DESIGN = (900, 1600)          # App 渠道写死坐标的基准


def _mumu_adb() -> str:
    for base in (r"D:\Program Files\Netease\MuMu",
                 r"C:\Program Files\Netease\MuMu"):
        p = os.path.join(base, "nx_main", "adb.exe")
        if os.path.isfile(p):
            return p
    return "adb"


def _idle_hint(log_path: str = "logs/monitor.log") -> str:
    """看一眼采集是否空闲（只读日志，不做判断）。"""
    try:
        age = time.time() - os.path.getmtime(log_path)
        if age < 120:
            return "⚠ 采集似乎在活动（%.0fs 前刚写日志）——建议等空窗再改" % age
        return "采集已空闲 %.0f 分钟，可以改" % (age / 60.0)
    except OSError:
        return "（读不到日志，自行确认采集是否空闲）"


def _ui_alive(dev) -> tuple:
    """改完之后界面还活着吗：能 dump 出 ≥6 个节点就不算白屏。"""
    try:
        xml = dev.dump() or ""
    except Exception as e:
        return False, "dump 异常：%s" % str(e)[:80]
    n = xml.count("<node")
    if n >= 6:
        return True, "%d 个节点" % n
    return False, "%d 个节点（疑似白屏）" % n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="屏幕伪装（带坐标换算与回滚）")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--adb", default=_mumu_adb())
    ap.add_argument("--size", default="", help="目标分辨率，如 1080x1920")
    ap.add_argument("--scale", type=float, default=0.0,
                    help="等比放大倍数（1.2 = 1080x1920，density 同比）")
    ap.add_argument("--dpi", type=int, default=0, help="显式指定 DPI")
    ap.add_argument("--restore", action="store_true", help="回滚到出厂")
    ap.add_argument("--no-design", action="store_true",
                    help="不开启坐标换算（**危险**：写死坐标会偏）")
    args = ap.parse_args(argv)

    from core.android.device import AdbDevice
    from core.android import display

    dev = AdbDevice(args.adb, args.serial)
    cur = display.actual(dev)

    if args.restore:
        rep = display.reset(dev)
        print("已回滚：", rep.get("after"))
        return 0

    if not args.size and not args.scale:
        print("=" * 70)
        print("当前屏幕")
        print("=" * 70)
        print("  wm size    : %dx%d%s" % (cur["width"], cur["height"],
                                          "（override）" if cur["override"] else ""))
        print("  wm density : %d" % cur["density"])
        print("  坐标基准   : %dx%d（App 渠道写死）" % DESIGN)
        print("  是否需要换算: %s" % ("否（正好相等）"
                                      if (cur["width"], cur["height"]) == DESIGN
                                      else "是"))
        print()
        print("  " + _idle_hint())
        print()
        print("  改：python scripts/display_spoof.py --scale 1.2")
        print("  回滚：python scripts/display_spoof.py --restore")
        return 0

    # 目标
    if args.size:
        try:
            w, h = [int(x) for x in args.size.lower().split("x")]
        except ValueError:
            print("--size 格式应为 1080x1920")
            return 2
        target = display.plan_spoof(dev, width=w, height=h, density=args.dpi)
    else:
        w = int(round(cur["width"] * args.scale))
        h = int(round(cur["height"] * args.scale))
        target = display.plan_spoof(dev, width=w, height=h, density=args.dpi)

    print("=" * 70)
    print("将把屏幕改成 %dx%d @ %d dpi（当前 %dx%d @ %d）"
          % (target["width"], target["height"], target["density"],
             cur["width"], cur["height"], cur["density"]))
    print("  " + _idle_hint())
    print("=" * 70)

    rep = display.spoof(dev, width=target["width"], height=target["height"],
                        density=target["density"])
    if not rep.get("ok"):
        print("❌ 改失败：", rep.get("error") or rep.get("after"))
        print("   正在回滚…")
        display.reset(dev)
        return 1

    dev.set_design(*DESIGN)          # 立刻开换算，避免写死坐标偏掉
    after = rep.get("after") or {}
    print("✅ 已改：%dx%d @ %d（override=%s）"
          % (after.get("width"), after.get("height"), after.get("density"),
             after.get("override")))
    print("   坐标换算：设计 %dx%d → 设备 %dx%d，比例 %.3f x %.3f"
          % (DESIGN[0], DESIGN[1], after.get("width"), after.get("height"),
             (after.get("width") or 0) / float(DESIGN[0]),
             (after.get("height") or 0) / float(DESIGN[1])))
    if args.no_design:
        print("   ⚠ 你选择了 --no-design：写死坐标会按比例偏！")

    ok, why = _ui_alive(dev)
    print(("✅ 界面正常：%s" if ok else "❌ 界面疑似白屏：%s") % why)
    if not ok:
        print("   正在回滚…")
        display.reset(dev)
        return 1
    print()
    print("回滚：python scripts/display_spoof.py --restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
