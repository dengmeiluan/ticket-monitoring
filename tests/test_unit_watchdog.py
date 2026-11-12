# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1755_watchdog.py
- tests/test_r1780_watchdog_decide_order.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import time

# W1：watchdog.py 已迁 tools/（避免与 pip 的 watchdog 包名冲突，按路径加载）
_wd_spec = importlib.util.spec_from_file_location(
    "watchdog_tool",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "tools", "watchdog.py"))
wd = importlib.util.module_from_spec(_wd_spec)
_wd_spec.loader.exec_module(wd)


# ---- merged from tests/test_r1755_watchdog.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

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


# ---- merged from tests/test_r1780_watchdog_decide_order.py ----

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

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
