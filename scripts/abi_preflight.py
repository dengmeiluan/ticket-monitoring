# -*- coding: utf-8 -*-
"""ABI 可行性预检（只读）：不动设备，判断「改 arm64 会不会炸」。

用法：
    python scripts/abi_preflight.py                 # 预检（只读，安全，随时可跑）
    python scripts/abi_preflight.py --json          # 机读
    python scripts/abi_preflight.py --canary        # 真跑一次实验（会重启框架！）

为什么默认只做预检：``--canary`` 要重启 zygote 两次（约 30–60s），会打断正在
进行的采集轮。预检只用 ``dumpsys package``，不碰任何开关，采集期间也能跑。

判据（全部来自实测事实）见 ``core/android/abi_canary.py::preflight``。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mumu_adb() -> str:
    for base in (r"D:\Program Files\Netease\MuMu", r"C:\Program Files\Netease\MuMu"):
        p = os.path.join(base, "nx_main", "adb.exe")
        if os.path.isfile(p):
            return p
    return "adb"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ABI 可行性预检（默认只读）")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--adb", default=_mumu_adb())
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--canary", action="store_true",
                    help="真跑实验（重启框架两次，别在采集轮里用）")
    ap.add_argument("--pkg", default="ctrip.android.view")
    ap.add_argument("--wait", type=int, default=60)
    args = ap.parse_args(argv)

    from core.android.device import AdbDevice
    from core.android import abi_canary

    dev = AdbDevice(args.adb, args.serial)

    if args.canary:
        rep = abi_canary.run(dev, args.pkg, {}, None,
                            restart_wait_s=args.wait, wait_s=args.wait)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        else:
            print("canary ok      :", rep.get("ok"))
            print("restored       :", rep.get("restored"))
            print("preflight risk :", (rep.get("preflight") or {}).get("risk"))
            print("errors         :", (rep.get("probe") or {}).get("errors"))
            if rep.get("error"):
                print("error          :", rep["error"])
        return 0

    rep = abi_canary.preflight(dev)
    # 宿主侧官方能力（MuMu setting --all）只在这里查：它是 GUI 进程，
    # 采集进行中可能阻塞几十秒，绝不能进 preflight 的热路径。
    host = {}
    try:
        host = abi_canary.mumu_capabilities()
    except Exception as e:
        host = {"available": False, "note": str(e)[:120]}

    if args.json:
        print(json.dumps(dict(rep, host=host), ensure_ascii=False, indent=2))
        return 0

    p = rep.get("props") or {}
    print("=" * 72)
    print("ABI 预检（只读，未改动任何设置）")
    print("=" * 72)
    print("  ro.product.cpu.abi      :", p.get("abi"))
    print("  abilist64               :", p.get("abilist64"))
    print("  abilist32               :", p.get("abilist32"))
    print("  native.bridge           :", p.get("native_bridge") or "（无）")
    print("-" * 72)
    print("  %-26s %-16s %s" % ("包", "primaryCpuAbi", "secondary"))
    for pkg, r in (rep.get("packages") or {}).items():
        print("  %-26s %-16s %s" % (pkg, r.get("primary") or "（未装）",
                                    r.get("secondary") or "-"))
    print("-" * 72)
    print("  风险等级 :", rep.get("risk"))
    print("  判断依据 :", rep.get("why"))
    print("  可以实验 :", "是" if rep.get("ok") else "否")
    if host.get("available"):
        k = host.get("keys") or {}
        print("-" * 72)
        print("  MuMu 官方设置（宿主机侧）：")
        print("    system_disk_readonly :", k.get("system_disk_readonly"),
              "（false + 重启实例 → 系统盘可写，ABI 才可能）")
        print("    root_permission      :", k.get("root_permission"))
        print("    phone_brand/model    :", k.get("phone_brand"), "/",
              k.get("phone_model"), "（", k.get("phone_miit"), "）")
        print("    resolution           : %sx%s @ %s dpi"
              % (str(k.get("resolution_width", "")).split(".")[0],
                 str(k.get("resolution_height", "")).split(".")[0],
                 str(k.get("resolution_dpi", "")).split(".")[0]))
        if rep.get("risk") == "blocked" and host.get("system_writable"):
            print()
            print("  ⚠ 宿主机已设 system_disk_readonly=false，但设备侧仍不可写：")
            print("    需要**重启实例**让它生效。")
    if rep.get("ok"):
        print()
        print("  下一步（挑空闲窗口跑，会重启框架 ~30–60s）：")
        print("    python scripts/abi_preflight.py --canary")
        print("  判定 ok 后，把 config.yaml 的 android.identity.spoof_abi 改成 auto")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
