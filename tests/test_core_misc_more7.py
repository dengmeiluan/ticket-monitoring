# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r959_hidden_not_deducted.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys

from core.android import stealth as st


# ---- merged from tests/test_r959_hidden_not_deducted.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Dev:
    """按 `ls -d`/`ls -ld` 回放存在性与权限位的最小假设备。"""

    def __init__(self, exists, modes=None):
        self.exists = set(exists)
        self.modes = dict(modes or {})
        # detect() 拿不到任何 props 会提前返回（device offline），
        # 所以至少给一条，让文件探测真的被执行到
        self.props = {"ro.product.model": "V2405A"}
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        if toks[:3] == ["shell", "ls", "-ld"]:
            out = []
            for p in toks[3:]:
                if p in self.exists:
                    out.append("%s 2 root root 4096 2026-11-04 12:00 %s"
                               % (self.modes.get(p, "drwxr-xr-x"), p))
            return "\n".join(out)
        if toks[:3] == ["shell", "ls", "-d"]:
            p = toks[3] if len(toks) > 3 else ""
            return p if p in self.exists else ""
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        return ""


# 除 /data/adb/magisk 之外完全相同的两台"设备"
_PARENT = {"/data": "drwxrwx--x", "/data/adb": "drwx------"}
A = _Dev({"/system/bin/sh", "/data", "/data/adb", "/data/adb/magisk"},
         modes=_PARENT)
B = _Dev({"/system/bin/sh", "/data", "/data/adb"}, modes=_PARENT)


def test_hidden_items_do_not_change_score():
    """**不扣分**这一半：有没有这条 App 摸不到的路径，分数必须一样。"""
    ra, rb = st.detect(A), st.detect(B)
    assert isinstance(ra.get("score"), int) and isinstance(rb.get("score"), int)
    assert ra["score"] == rb["score"], (
        "存在但 App 摸不到的条目被算进风险分了：这会把操作员推向"
        "『去删掉一个看不见的东西』，而删它的代价是失去 resetprop 能力。"
        "A=%s B=%s" % (ra["score"], rb["score"]))


def test_hidden_items_are_listed_not_in_root():
    """**可见**这一半：要出现在 hidden_from_app，而不是 root 里。"""
    ra = st.detect(A)
    assert not any("adb/magisk" in x for x in (ra.get("root") or [])), \
        "App 摸不到的路径被当成 root 证据（应按攻击者权限判）"
    assert any("adb/magisk" in x for x in (ra.get("hidden_from_app") or [])), \
        "探针查到的东西没被列出来 → 又变成不可证伪的假清白"


def test_app_visible_path_still_counted():
    """对照：App **能**看见的路径（父目录 others 有 x）仍要计入 root。

    注意用 `_FS_ROOTS` 里真实存在的探测项（`/system/bin/su`）——
    拿一个根本不被探测的路径来断言"应该报出来"，测的是我的想象而不是代码。
    """
    v = _Dev({"/system/bin/sh", "/system", "/system/bin", "/system/bin/su"},
             modes={"/system": "drwxr-xr-x", "/system/bin": "drwxr-xr-x"})
    r = st.detect(v)
    assert any("/system/bin/su" in x for x in (r.get("root") or [])), \
        "真能被 App stat 到的 su 却不算 root 证据（漏报）：\n%s" % r.get("root")


def test_note_silent_when_nothing_hidden():
    """没有隐藏项时不许印「另有 0 条」这种噪音。"""
    assert st._fmt_hidden_note(None) == ""
    assert st._fmt_hidden_note([]) == ""


def test_note_states_not_counted_and_warns():
    s = st._fmt_hidden_note(["fs:/data/adb/magisk"])
    assert "1 条" in s, s
    assert "未计入" in s, "必须说清不扣分，否则操作员会去消它"
    assert "别去动" in s, "要给出明确处置指引"


def test_prepare_uses_the_pure_helper():
    """日志尾巴必须由纯函数产出（内联文案没法被测试钉住）。"""
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find("def prepare(")
    assert i > 0
    body = src[i:src.find("\ndef ", i + 10)]
    assert "_fmt_hidden_note(" in body, "prepare 又回到内联拼文案"
    assert "另有 %d 条" not in body, "内联文案残留（会与纯函数漂移）"
