# -*- coding: utf-8 -*-
"""r1755：心跳 + 看门狗——进程死了要能被发现并拉起。

事故背景：我用错的探活方式把主服务打死，**没有任何机制发现或拉起它**，
二十多分钟后我才自己发现。对监控程序来说，最坏的失败模式就是
"进程没了却没人知道"。
"""
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import watchdog as wd  # noqa: E402


def _hb(tmp_path, ts=None, pid=1):
    p = tmp_path / ".heartbeat"
    d = {"pid": pid, "ts": int(time.time() if ts is None else ts),
         "at": "x"}
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def test_decide_matrix():
    assert wd.decide(10, True, 180) == "ok"
    assert wd.decide(None, True, 180) == "kill_restart"      # 无心跳但活着=卡住
    assert wd.decide(None, False, 180) == "restart"          # 无心跳且不在=已退
    assert wd.decide(999, True, 180) == "kill_restart"
    assert wd.decide(999, False, 180) == "restart"


def test_heartbeat_age_roundtrip(tmp_path):
    p = _hb(tmp_path, ts=time.time() - 42)
    age = wd.heartbeat_age(p)
    assert age is not None and 40 <= age <= 45, age


def test_heartbeat_missing_or_broken(tmp_path):
    assert wd.heartbeat_age(str(tmp_path / "nope")) is None
    bad = tmp_path / "bad"
    bad.write_text("{not json", encoding="utf-8")
    assert wd.heartbeat_age(str(bad)) is None


def test_pid_alive_self_and_bogus():
    """注意：POSIX 上僵尸进程仍会被 os.kill(pid,0) 判成"在"——调用方要先回收。"""
    assert wd.pid_alive(os.getpid()) is True
    assert wd.pid_alive(999999) is False


def test_kill_pid_really_kills_a_dummy():
    """真杀一个**替身进程**（绝不动主服务）。"""
    dummy = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(120)"])
    try:
        time.sleep(0.5)
        assert wd.pid_alive(dummy.pid) is True
        assert wd.kill_pid(dummy.pid) is True
        # POSIX 上被杀的子进程要先被回收，否则是僵尸：os.kill(pid,0) 仍成功，
        # pid_alive 会误报"存活"（CI Linux 实测）。
        try:
            dummy.wait(timeout=8)
        except Exception:
            pass
        time.sleep(0.5)
        assert wd.pid_alive(dummy.pid) is False, "替身进程没被杀掉"
    finally:
        try:
            dummy.kill()
        except Exception:
            pass


def test_main_writes_heartbeat():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "def _start_heartbeat(" in src, "main.py 没有心跳函数"
    assert "_start_heartbeat(logger)" in src, "心跳没被启动"
    assert 'data", ".heartbeat"' in src or "data/.heartbeat" in src, \
        "心跳路径不是 data/.heartbeat"


def test_watchdog_never_uses_os_kill_on_windows():
    src = io.open(os.path.join(ROOT, "tools", "watchdog.py"),
                  encoding="utf-8").read()
    i = src.index("def pid_alive(")
    seg = src[i:i + 1200]
    assert "tasklist" in seg, "Windows 分支没用 tasklist"
    if "os.kill(int(pid), 0)" in seg:
        j = seg.index("os.kill(int(pid), 0)")
        assert seg[:j].rstrip().endswith("try:"), "os.kill 不在 POSIX 分支"
