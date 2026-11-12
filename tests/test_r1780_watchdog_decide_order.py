# -*- coding: utf-8 -*-
"""r1780/r1781：看门狗两处修正的门禁。

r1780：判定顺序——**进程不在就必须立刻重启**。旧顺序先看心跳年龄，
        进程被强杀后心跳文件还"新鲜"（残留），于是判 ok、服务一直躺着
        （实测 08:17:40 心跳 73s、进程不在、判定 ok）。
r1781：启动前先探端口——服务已在跑就别再拉一个（抢不到端口会立刻退出）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import watchdog as wd  # noqa: E402


def test_dead_process_restarts_even_with_fresh_heartbeat():
    # 心跳 10 秒（远小于阈值）但进程不在 → 必须重启
    assert wd.decide(10, False, 180) == "restart"
    assert wd.decide(0, False, 180) == "restart"


def test_alive_and_fresh_is_ok():
    assert wd.decide(10, True, 180) == "ok"


def test_alive_but_stale_is_kill_restart():
    assert wd.decide(999, True, 180) == "kill_restart"
    assert wd.decide(None, True, 180) == "kill_restart"


def test_port_guard_exists():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "watchdog.py"),
        encoding="utf-8").read()
    assert "def port_listening(" in src
    i = src.index("def start_main(")
    assert "port_listening()" in src[i:i + 400], "start_main 没做端口检查"
