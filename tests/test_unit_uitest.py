# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1748_uitest_single_instance.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import re


# ---- merged from tests/test_r1748_uitest_single_instance.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "tools", "uitest.py"), encoding="utf-8",
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
