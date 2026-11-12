# -*- coding: utf-8 -*-
"""`build.id` 的**分阶段实测**脚本：写之前抓旧值，写之后验自洽与健康，出问题自动回滚。

为什么需要这个脚本（而不是"直接开 config 让生产去写"）
----------------------------------------------------
`ro.build.id = V417IR` 是 MuMu 自己的 build 号，还渗在
`ro.build.description` 和六个分区的 `ro.*.build.fingerprint` 里 ——
`Build.ID` / `Build.FINGERPRINT` / `Build.DESCRIPTION` 是任何 SDK 都读的字段，
而且这个号在**所有 MuMu 实例上一模一样**，是一条很强的跨账号相关性键。

`core/android/buildid.py` 已经实现并在 `harden()` 里接好（默认关）。
但"改 `ro.build.*` 这一族"今天**两次让 system_server 重启、adbd 掉线**，
所以开之前必须实测三件事：
1. 写进去之后**设备还活着**（dump/截图/拉 App 都能用）；
2. 改完之后**自洽**（ID、description、各分区 fingerprint 里的 ID 段一致）——
   半改会造成 `Build.ID` 与 `Build.DESCRIPTION` 互相矛盾，
   那比"统一像模拟器"更可疑；
3. **回滚路径真的能回滚**（记旧值、写回、比对）。

只在**采集空档**跑（下一轮开始前至少留 10 分钟），因为它最坏情况要重启实例。

用法：
    python scripts/buildid_stage.py            # 预演（只读，不写）
    python scripts/buildid_stage.py --apply    # 真写 + 健康检查 + 必要时自动回滚
"""
import argparse
import subprocess
import os
import sys
import time

# 让脚本可以从仓库根直接 `python scripts/buildid_stage.py` 跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import buildid as bi            # noqa: E402
from core.android import fingerprint as fp        # noqa: E402
from core.android.device import AdbDevice         # noqa: E402

ADB = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
SERIAL = "127.0.0.1:16384"
# 健康检查用的 App：必须是**采集在用**的包，这样"能不能正常起"才是真信号
CANARY_PKG = "cn.suanya.zhixing"
CFG_ON = {"android": {"build_id": {"enabled": True}}}


def _sh(dev_args, t=90):
    r = subprocess.run([ADB, "-s", SERIAL, "shell"] + list(dev_args),
                       capture_output=True, timeout=t)
    return (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def _sys_server_pid():
    """system_server 的 pid —— 它变了才叫"框架重启"。

    不要用日志里出现 `system_server` 这个词来判：那只是一行
    `W service : ... linkToDeath ...` 警告，内容里**提到了**它，
    跟框架重启毫无关系。按关键词判会把每次健康检查都判成不健康
    （2026-11-04 实测就这么误判过一次）。
    """
    for l in _sh(["ps", "-A", "-o", "PID,NAME"]).splitlines():
        cols = l.split()
        if len(cols) == 2 and cols[1] == "system_server":
            return cols[0]
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真的写；不传则只预演（只读）")
    args = ap.parse_args()

    d = AdbDevice(ADB, SERIAL)
    try:
        d.connect()
    except Exception:
        pass
    props = fp.props_of(d)
    if not props:
        print("设备没读到 props，终止（不做任何写入）")
        return 1

    want = bi.target_for(props)
    print("=== 目标（原地替换旧 build 号，%d 个键）===" % len(want))
    if not want:
        prof = bi._profile_for(props)
        new_id = str((prof or {}).get("build_id") or "")
        if prof is None:
            print("  机型 %s 不在 PHONE_POOL —— 什么都不做。"
                  "这不是失败，但要人工看一眼配置与机型池是否漂移。"
                  % props.get("ro.product.model"))
            return 0
        # **计划为空 ≠ 一定自洽**（今天的事故正是"计划只覆盖九个键"却
        # 全绿通过）。空计划时反而要主动查一遍分区 build.id 是否都等于目标值：
        # 有落后的就说明发现逻辑漏了键 —— 这种情况必须**非零退出**，
        # 不能让它长得像"没什么要做，挺好"。
        stale = sorted(k for k, v in props.items()
                       if k.endswith(".build.id") and str(v or "") != new_id)
        if stale:
            print("  !! 计划为空但仍有分区 build.id 落后于 %s：%s"
                  % (new_id, ", ".join(stale)))
            print("  ==> 发现逻辑漏键，不要用 --apply 硬试，先查 target_for。")
            return 2
        print("  已全部自洽：build_id=%s，无落后的分区 id ⇒ 零写入。" % new_id)
        return 0
    for k, v in want.items():
        print("  %-36s %s -> %s" % (k, str(props.get(k))[:34], v[:44]))

    if not args.apply:
        print("\n（预演模式，未写入。加 --apply 才真写）")
        return 0

    before = {k: _sh(["getprop", k]) for k in want}
    firstboot = _sh(["getprop", "ro.runtime.firstboot"])
    syspid0 = _sys_server_pid()
    # **先把 logcat 清空**再动手：`logcat -d -t 400` 会把今天早些时候
    # 那两次 system_server 崩溃一起读回来，健康检查因此**必然**判不健康、
    # 触发一次不必要的自动回滚（假警报）。清过之后读到的崩溃才属于本次改动。
    _sh(["logcat", "-c"])
    print("\n=== 写入 ===")
    rep = bi.sync(d, CFG_ON)
    print("  ok=%s changed=%s failed=%s verified=%s"
          % (rep.get("ok"), rep.get("changed"), rep.get("failed"),
             rep.get("verified")))

    after = {k: _sh(["getprop", k]) for k in want}
    bad = [k for k in want if after[k] != want[k]]
    print("  读回不符的键:", bad or "无")

    # 自洽：所有含 ID 段的值必须都换成同一个新 ID，且不再含旧 ID
    old_id = str(props.get("ro.build.id") or "")
    new_id = str(want.get("ro.build.id") or "")
    leak = [k for k, v in after.items() if old_id and old_id in v]
    # 取 fingerprint 的 ID 段的正确切法（冒号**只有一个**）：
    #   `brand/device:release/ID/incremental:user/tags`
    #   → 冒号右侧按 `/` 切 → ['release', 'ID', 'incremental...'] → 取 [1]
    # 早先两种写法都错：`split(':')[-1]` 拿到"冒号后整串"（含 release/incremental），
    # 永远不等于裸 ID；`":{new_id}/" not in v` 在 ID 本身含 `/` 时（AP3A.240905.015）
    # 也永远不成立 ⇒ 九个键**全部假不自洽**，把一次完全成功的写入自动回滚掉
    # （2026-11-04 真的就这么错过一次）。**判据失败比没判更坏：它会否决好结果。**
    seg_bad = []
    for k, v in after.items():
        if not k.endswith("build.fingerprint"):
            continue
        parts = v.split(":", 1)
        seg = parts[1].split("/")[1] if len(parts) > 1 and \
            len(parts[1].split("/")) > 1 else ""
        if seg != new_id:
            seg_bad.append("%s(%r)" % (k, seg))
    print("  仍含旧 build 号:", leak or "无",
          "| fingerprint 的 ID 段不对:", seg_bad or "无")

    print("\n=== 健康检查（盯 system_server 有没有重启）===")
    nb = _sh(["getprop", "ro.runtime.firstboot"])
    print("  firstboot 变了(=重启过):", (nb != firstboot), "| %s -> %s"
          % (firstboot[:16], nb[:16]))
    print("  id:", _sh(["id"])[:40])
    _sh(["rm", "-f", "/sdcard/tm_stage.xml"])
    r = subprocess.run([ADB, "-s", SERIAL, "shell", "uiautomator", "dump",
                        "/sdcard/tm_stage.xml"], capture_output=True, timeout=90)
    print("  dump:", (r.stdout + r.stderr).decode("utf-8", "replace")
          .strip()[:56])
    shot = subprocess.run([ADB, "-s", SERIAL, "exec-out", "screencap", "-p"],
                          capture_output=True, timeout=90)
    print("  screencap:", len(shot.stdout), "bytes")
    _sh(["am", "force-stop", CANARY_PKG])
    subprocess.run([ADB, "-s", SERIAL, "shell", "monkey", "-p", CANARY_PKG,
                    "-c", "android.intent.category.LAUNCHER", "1"],
                   capture_output=True, timeout=90)
    time.sleep(9)
    pid = _sh(["pidof", CANARY_PKG])
    print("  %s pid:" % CANARY_PKG, pid or "(没起来 ← 危险信号)")
    log = _sh(["logcat", "-d", "-t", "400"])
    crash = [l for l in log.splitlines()
             if any(x in l for x in ("FATAL EXCEPTION", "Force finishing",
                                     "E AndroidRuntime", "has crashed"))]
    print("  崩溃命中:", len(crash))
    for l in crash[:3]:
        print("    ", l[:118])
    syspid1 = _sys_server_pid()
    print("  system_server pid:", "%s -> %s" % (syspid0, syspid1),
          "| 框架重启 =", bool(syspid0) and syspid1 != syspid0)

    healthy = (not bad) and (not leak) and (not seg_bad) and (not crash) \
        and bool(pid) and nb == firstboot \
        and (not syspid0 or not syspid1 or syspid1 == syspid0)
    # ^ 拿不到 pid（不同 toybox 的 `ps -o` 支持度不一样）时算"未知"，
    # **未知不等于失败** —— 否则一个查询语法问题会把完全健康的改动判死并回滚。
    # 真正致命的信号仍然盯得住：读回不符 / 仍含旧号 / 不自洽 / 崩溃日志 /
    # App 起不来 / firstboot 变了。

    print("\n=== 结论 ===")
    if healthy:
        print("  通过。可以把 config 打开：android.build_id.enabled: true")
        print("  注意：实例重启后 MuMu 注入器会把旧值写回，由 harden() 的"
              " build-id 步重新对齐。")
        return 0

    print("  **不健康，自动回滚**")
    rp = fp._magisk(d)
    for k, v in before.items():
        if _sh(["getprop", k]) == v:
            continue
        if v:
            fp.sh_script(d, "%s %s %s" % (rp, k, fp._q(v)))
        else:
            fp.sh_script(d, "%s --delete %s" % (rp, k))
    still = [k for k in want if _sh(["getprop", k]) != before[k]]
    print("  回滚后仍不一致:", still or "无（已完全还原）")
    if nb != firstboot:
        print("  提示：设备已经重启过，原值由注入器恢复，无需再手动回滚。")
    print("  下一步：把上面的失败项发出来再决定；不要带着未验证的改动开 config。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
