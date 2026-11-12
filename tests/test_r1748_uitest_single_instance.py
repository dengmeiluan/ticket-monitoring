# -*- coding: utf-8 -*-
"""r1748：`docs/uitest.py` 必须单实例跑，且**存活探测不许用 os.kill**。

两条都是实测事故：

1. 并发跑：机器上同时有 5 个 uitest（我先前起的没退干净），都写同一个
   `uitest_result.txt` → 一会 689/690、一会 690/690，还各自起 demo 服务 +
   几十个 chrome 把 CPU 打满。
2. **Windows 上 `os.kill(pid, 0)` 会真的 TerminateProcess**（POSIX 里 sig 0 只是探测）。
   我拿锁文件里的"主服务 PID"做探测，把服务直接打死，8765 随即连接被拒。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "docs", "uitest.py"), encoding="utf-8",
                   newline="").read()


def test_single_instance_lock_exists():
    s = _src()
    assert "def _acquire_single_instance(" in s, "没有单实例锁"
    assert "_acquire_single_instance()" in s.split("def main():")[1][:200], \
        "main() 没调用锁"
    assert ".uitest.lock" in s, "锁文件名不在"


def test_windows_liveness_probe_is_safe():
    s = _src()
    i = s.index("_acquire_single_instance")
    seg = s[i:i + 2000]
    assert 'tasklist' in seg, "Windows 分支没有用 tasklist 探测"
    assert '_os.name == "nt"' in seg, "没有按平台分支"
    # POSIX 分支可以留 os.kill，但**代码行**必须紧跟 else:（注释里的不算）
    lines = seg.splitlines()
    for n, line in enumerate(lines):
        code = line.strip()
        if "os.kill(pid, 0)" not in code or code.startswith("#"):
            continue
        seen = []
        for k in range(n - 1, max(-1, n - 8), -1):
            cand = lines[k].strip()
            if cand and not cand.startswith("#"):
                seen.append(cand)
        assert "else:" in seen, (
            "os.kill(pid, 0) 不在 POSIX 的 else 分支里（往上看 8 行未见 else:，"
            "实际=%r）——Windows 上会杀进程" % seen[:4])


def test_lock_file_is_gitignored():
    gi = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert ".uitest.lock" in gi, "锁文件没进 .gitignore（会被误提交）"
