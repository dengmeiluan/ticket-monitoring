#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r1755 看门狗：采集进程死了/卡住了，把它拉起来。

为什么需要：进程一退，监控就无声无息停了。本轮我自己用错的探活方式把
主服务打死，二十多分钟没人发现——"监控程序不监控自己"是它最坏的失败模式。

用法（在仓库根目录）：
    python tools/watchdog.py                 # 前台守护（Ctrl+C 退出）
    python tools/watchdog.py --stale 240     # 心跳超过 240 秒视为卡死
    python tools/watchdog.py --once          # 只检查一次（给计划任务用）

判定（三态）：
  * 心跳新鲜（<= --stale）           → ok，什么都不做
  * 心跳陈旧/缺失，但进程还在         → 卡死：先 taskkill 再重启
  * 心跳陈旧/缺失，且进程不在         → 已退出：直接重启

**不要用 os.kill 探活**：Windows 上它对任意信号都走 TerminateProcess，
探一下就把目标杀了（本项目真实事故）。这里统一用 tasklist / taskkill。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEARTBEAT = os.path.join(ROOT, "data", ".heartbeat")
LOG = os.path.join(ROOT, "logs", "watchdog.log")


def read_heartbeat(path: str = HEARTBEAT) -> dict:
    """读心跳（容忍半截文件/坏 JSON）。返回 {} 表示读不到。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def heartbeat_age(path: str = HEARTBEAT, now: float | None = None):
    """心跳有多旧（秒）；读不到时间戳返回 None。"""
    d = read_heartbeat(path)
    try:
        ts = int(d.get("ts") or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    now = time.time() if now is None else now
    return max(0.0, now - ts)


def pid_alive(pid: int) -> bool:
    """进程是否还活着。**Windows 用 tasklist（只读）**，POSIX 才用 os.kill(pid,0)。"""
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid),
                                  "/NH"], capture_output=True, text=True,
                                 timeout=10)
            return str(int(pid)) in (out.stdout or "")
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def decide(age, alive: bool, stale_s: float) -> str:
    """纯判定：ok / restart（已退出）／kill_restart（还活着但卡住）。

    **先看进程在不在**（r1780）：心跳文件是残留物，进程被强杀后它不会自己变旧。
    旧顺序「心跳新 → ok」会在进程已死时判 ok（实测 08:17 心跳 73s、进程不在、
    判定 ok，服务一直躺着）。所以：不在 → 立刻 restart。
    """
    if not alive:
        return "restart"
    if age is not None and age <= stale_s:
        return "ok"
    return "kill_restart"


def _log(msg: str) -> None:
    line = "[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass


def kill_pid(pid: int) -> bool:
    """结束进程（Windows 用 taskkill /F；POSIX 用 SIGKILL）。"""
    if not pid:
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                           capture_output=True, timeout=15)
        else:
            os.kill(int(pid), 9)
        return True
    except Exception as e:
        _log("结束 pid %s 失败：%s" % (pid, e))
        return False


def port_listening(port: int = 8765) -> bool:
    """8765 是否已在监听（r1781：已有人在跑就别再起一个）。"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
            return True
    except Exception:
        return False


def start_main() -> int:
    """拉起 main.py（同一解释器、同目录），返回子进程 pid（失败 0）。"""
    if port_listening():
        _log("端口 8765 已在监听——已有实例在跑，不再重复拉起")
        return 0
    try:
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")],
                             cwd=ROOT, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return int(p.pid or 0)
    except Exception as e:
        _log("拉起 main.py 失败：%s" % e)
        return 0


def check_once(stale_s: float = 180.0, start: bool = True) -> str:
    hb = read_heartbeat()
    pid = int(hb.get("pid") or 0)
    age = heartbeat_age()
    alive = pid_alive(pid)
    act = decide(age, alive, stale_s)
    _log("心跳 %s · pid %s %s · 判定 %s%s"
         % ("无" if age is None else "%.0fs" % age, pid,
            "存活" if alive else "不在", act,
            "" if alive else "（进程不在→立刻拉起）"))
    if act == "ok" or not start:
        return act
    if act == "kill_restart":
        kill_pid(pid)
        time.sleep(2)
    new = start_main()
    _log("已重启 main.py → pid %s" % (new or "失败"))
    return act


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ticket-monitoring 看门狗")
    ap.add_argument("--stale", type=float, default=180.0,
                    help="心跳超过多少秒视为卡死（默认 180）")
    ap.add_argument("--interval", type=float, default=60.0,
                    help="检查间隔秒（默认 60）")
    ap.add_argument("--once", action="store_true", help="只检查一次")
    ap.add_argument("--dry-run", action="store_true", help="只判定不重启")
    a = ap.parse_args(argv)
    if a.once or a.dry_run:
        act = check_once(a.stale, start=not a.dry_run)
        return 0 if act in ("ok", "restart", "kill_restart") else 1
    _log("看门狗启动（stale=%.0fs interval=%.0fs）" % (a.stale, a.interval))
    while True:
        try:
            check_once(a.stale, start=True)
        except KeyboardInterrupt:
            _log("看门狗退出（Ctrl+C）")
            return 0
        except Exception as e:
            _log("检查异常：%s" % e)
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
