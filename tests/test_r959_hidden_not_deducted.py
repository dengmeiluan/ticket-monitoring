# -*- coding: utf-8 -*-
"""r959：「存在但 App 摸不到」的条目必须**可见但不扣分**。

来龙去脉（2026-11-04，同一天）：
1. 探针原本用 `sh -c "test -e X && echo A || echo B"`，被 adb 拆参数后
   **恒判"不存在"**（见 §6.38），于是 root 痕迹长期 `[]`、自检"满分"是假的；
2. 探针修好后立刻报出 `/data/adb/magisk`。但我差点据此把它删掉——
   而 `/data/adb` 是 `drwx------ 0700`，App 连 traverse 都做不到，
   那条路径**对 App 等于不存在**；它之所以看得见，是因为自检跑在
   `adb root`（uid=0）下。**判暴露面要按攻击者的权限判。**
3. 所以定下的契约是两半，缺一不可：
   * **不扣分**（否则操作员会被迫去消掉一个 App 看不见的东西，
     而消掉它的代价是失去 resetprop 能力）；
   * **要可见**（否则"探针到底有没有在工作"这件事不可证伪，
     就会退回第 1 步那种假清白而无人察觉）。
   本测试把这两半各自钉住：分数可比、文案存在且不说"0 条"。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r959_hidden_not_deducted.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import stealth as st  # noqa: E402


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
