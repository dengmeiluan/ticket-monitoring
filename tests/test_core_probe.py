# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r813i_probe_app_channels.py
- tests/test_r957_probe_not_vacuous.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request

from core.android import fingerprint as fp


# ---- merged from tests/test_r813i_probe_app_channels.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port










# ---- merged from tests/test_r957_probe_not_vacuous.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Dev:
    """假设备：`ls -ld <path>` 按字典回放；其它命令返回空。"""

    def __init__(self, existing, modes=None):
        self.existing = set(existing)
        self.modes = dict(modes or {})
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        if toks[:3] == ["shell", "ls", "-ld"]:
            out = []
            for p in toks[3:]:
                if p in self.existing:
                    mode = self.modes.get(p, "drwxr-xr-x")
                    out.append("%s 2 root root 4096 2026-11-04 12:00 %s"
                               % (mode, p))
            return "\n".join(out)
        if toks[:3] == ["shell", "ls", "-d"]:
            p = toks[3] if len(toks) > 3 else ""
            return p if p in self.existing else ""
        if cmd.strip() == "shell getprop":
            return "[ro.product.model]: [V2405A]"
        if cmd.startswith("shell getprop "):
            return ""
        return ""


# ---------------------------------------------------------------------------
# 1. 探针不许恒假：存在的路径必须返回 True
# ---------------------------------------------------------------------------
def test_probe_true_for_existing_path():
    d = _Dev({"/system/bin/sh"})
    assert fp._exact_path_exists(d, "/system/bin/sh") is True, \
        "存在的文件判 False = 恒假探针（曾错 55 轮，见 docstring）"


def test_probe_false_for_missing_path():
    d = _Dev({"/system/bin/sh"})
    assert fp._exact_path_exists(d, "/system/bin/su") is False


def test_probe_requires_exact_match_not_non_empty():
    """存在性必须**精确等于路径**，不能"有输出就算存在"。

    为什么单独钉这条（2026-11-04 我自己踩的）：实验脚本里我用了
    `stdout+stderr` 合并的读法去判"文件删了没"，
    `ls` 对**不存在**的文件会往 stderr 打
    `ls: /x: No such file or directory` —— 非空 → 被我读成"还在"，
    于是"已清理"这件事被判成"未清理"（方向是保守的，但同一写法反过来
    也能把"还在"判成"已删"，那就危险了）。
    共享探针只取 stdout 且**整行比对路径**，所以不受污染。
    """
    class _Err:
        def _sh(self, *a, timeout=None):
            # 模拟把错误信息当输出回流（stderr 污染）
            return "ls: /system/bin/su: No such file or directory"

    assert fp._exact_path_exists(_Err(), "/system/bin/su") is False, \
        "非空即算存在 → 报错文本会被当成文件存在"

    class _Ok:
        def _sh(self, *a, timeout=None):
            return "/system/bin/sh"

    assert fp._exact_path_exists(_Ok(), "/system/bin/sh") is True


def test_probe_uses_no_shell_metacharacters():
    """探测命令必须是独立 argv，不能包 `sh -c`。

    adb 会把命令行按空格拆开送进设备 shell，`sh -c "a && b"` 会被拆成
    `sh -c a` + 外层 `&& b`，内层永远拿不到参数 → 结果恒假。
    """
    src = io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                  encoding="utf-8").read()
    i = src.find("def _exact_path_exists")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    # 只看函数体（切掉 docstring），否则注释里的反面示例会误报
    code = body.split('"""')[2] if body.count('"""') >= 2 else body
    assert '"sh", "-c"' not in code, "探针还在用 sh -c（会被拆参数 → 恒假）"
    assert "test -e" not in code, "探针还在用 test -e（同样会被拆参数）"
    assert '"ls", "-d"' in code or '"ls", "-ld"' in code, \
        "探针应改用 ls -d 单条路径"


# ---------------------------------------------------------------------------
# 2. 存在 ≠ App 看得见
# ---------------------------------------------------------------------------
def test_app_cannot_see_under_0700_parent():
    """`/data/adb` 是 0700 → App 无法 traverse → 里面的东西不算暴露面。"""
    d = _Dev({"/data", "/data/adb", "/data/adb/magisk"},
             modes={"/data": "drwxrwx--x", "/data/adb": "drwx------"})
    assert fp._exact_path_exists(d, "/data/adb/magisk") is True
    assert fp.app_can_see(d, "/data/adb/magisk") is False, \
        "父目录 0700 时不该算 App 可见（按 root 权限判会造成假警报）"


def test_app_can_see_under_world_traversable_parent():
    d = _Dev({"/data", "/data/local", "/data/local/tmp",
              "/data/local/tmp/magisk_bin"},
             modes={"/data": "drwxrwx--x", "/data/local": "drwxr-x--x",
                    "/data/local/tmp": "drwxrwx--x"})
    assert fp.app_can_see(d, "/data/local/tmp/magisk_bin") is True


def test_app_can_see_is_conservative_when_unknown():
    """拿不到权限位时宁可判"看得见"，不能把真泄漏判没。"""
    d = _Dev({"/x/y"})          # 没有父目录 /x 的信息
    assert fp.app_can_see(d, "/x/y") is True


def test_visibility_cache_avoids_repeat_adb():
    """同一次 detect 里多条路径共享权限位缓存（每轮都跑，不能白烧 adb）。"""
    d = _Dev({"/data", "/data/adb", "/data/adb/magisk", "/data/adb/ksu"},
             modes={"/data": "drwxrwx--x", "/data/adb": "drwx------"})
    cache = {}
    fp.app_can_see(d, "/data/adb/magisk", cache)
    n1 = len([c for c in d.calls if "ls -ld" in c])
    fp.app_can_see(d, "/data/adb/ksu", cache)
    n2 = len([c for c in d.calls if "ls -ld" in c])
    assert n2 == n1, "父目录权限位没复用，每条路径都重查一次 adb"


# ---------------------------------------------------------------------------
# 3. 两处必须同一判据（否则报告自相矛盾）
# ---------------------------------------------------------------------------
def test_both_detectors_use_app_visibility():
    base = os.path.join(ROOT, "core", "android")
    st = io.open(os.path.join(base, "stealth.py"), encoding="utf-8").read()
    fpr = io.open(os.path.join(base, "fingerprint.py"), encoding="utf-8").read()
    assert "app_can_see(dev, p" in st, "stealth 没按 App 权限判"
    assert "app_can_see(dev, p" in fpr, "audit 没按 App 权限判"
    assert '"hidden_from_app"' in st
