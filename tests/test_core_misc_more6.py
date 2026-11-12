# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r954_props_are_rewritten.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import core.android.fingerprint as fpm
import io
import os
import re
import sys

from core.android import stealth as st


# ---- merged from tests/test_r954_props_are_rewritten.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Dev:
    """只读回放 props；写入由被 mock 的 `as_root` 负责（见 `_exec_as_root`）。"""

    def __init__(self, props):
        self.props = dict(props)
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if "magisk" in cmd:
            return "/data/adb/magisk/magisk\n"
        return ""


def _exec_as_root(script_holder):
    """把 `as_root` mock 成**真的执行**批量脚本里的删除语义。

    refresh 发的是一条脚本：
        magisk resetprop --delete K >/dev/null 2>&1;
        test -z "$(getprop K)" && echo 'GONE K'
    我们按键配对，删本地字典里的值，并回显 GONE，
    这样测的是"删光了没有"，而不是"有没有发命令"。
    """
    def _f(dev, script, timeout=None):
        script_holder.append(script)
        out = []
        props = dev.props
        for m in re.finditer(r"--delete\s+(\S+)|setprop\s+(\S+)\s+''",
                             script or ""):
            k = m.group(1) or m.group(2)
            props[k] = ""
            out.append("GONE " + k)
        return "\n".join(out)
    return _f


def _use_resetprop(monkeypatch, path="/data/adb/magisk/magisk resetprop"):
    monkeypatch.setattr(fpm, "_magisk", lambda dev: path)


# ---------------------------------------------------------------------------
# 1. fast path 不许"裸跳过"
# ---------------------------------------------------------------------------
def test_fast_path_still_refreshes_props():
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find('if not force and boot and cur == boot:')
    assert i > 0
    seg = src[i:i + 800]
    assert "refresh(" in seg, \
        "本 boot 已隐藏就整段跳过：nemuinit 会在几分钟内把 props 写回来"
    assert '"refresh"' in seg, "fast path 没把重清结果带回报告"


# ---------------------------------------------------------------------------
# 2. refresh 真正清掉厂商键与运行态 root 键
# ---------------------------------------------------------------------------
def test_refresh_clears_vendor_and_runtime_root(monkeypatch):
    _use_resetprop(monkeypatch)
    scripts = []
    monkeypatch.setattr(fpm, "as_root", _exec_as_root(scripts))
    d = _Dev({"nemud.device.id": "865247046277134",
              "ro.nemu": "1",
              "service.adb.root": "1",
              "ro.product.model": "V2405A"})
    r = st.refresh(d, {}, None)
    assert r["ok"] is True, r
    got = set(r["deleted"])
    assert {"nemud.device.id", "ro.nemu", "service.adb.root"} <= got, got
    # 正常机型键不许动
    assert "ro.product.model" not in got


def test_runtime_root_props_include_adb_root():
    """detect 算它、`_is_vendor_prop` 不认它 —— 必须有人清，否则分数回不来。"""
    assert "service.adb.root" in st._RUNTIME_ROOT_PROPS
    assert st._is_vendor_prop("service.adb.root", "1") is False
    d = _Dev({"service.adb.root": "1", "ro.product.model": "V2405A",
              "ro.product.brand": "vivo"})
    det = st.detect(d)
    assert any("service.adb.root" in str(x) for x in (det.get("root") or [])), \
        "detect 不再报它的话，_RUNTIME_ROOT_PROPS 就该一起删掉"


# ---------------------------------------------------------------------------
# 3. 别把"廉价重清"做成不廉价
# ---------------------------------------------------------------------------
def test_refresh_is_cheap_when_nothing_to_clear(monkeypatch):
    """全空 → 只花一条 getprop，**不许**再探测 magisk（它自带 4~5 条 adb）。"""
    probed = []
    monkeypatch.setattr(fpm, "_magisk",
                        lambda dev: probed.append(1) or "")
    d = _Dev({"ro.nemu": "", "service.adb.root": "",
              "ro.product.model": "V2405A"})
    r = st.refresh(d, {}, None)
    assert r["ok"] is True and r["deleted"] == []
    assert not probed, "干净设备还去探测 magisk（每轮白烧 4~5 条 adb）"
    assert [c for c in d.calls if c.strip() == "shell getprop"], d.calls
    assert len([c for c in d.calls if "shell" in c]) <= 2, d.calls


def test_refresh_batches_into_one_script(monkeypatch):
    """几十个厂商键不许逐条发（每键 2 个往返），要合成一条脚本。"""
    _use_resetprop(monkeypatch)
    scripts = []
    monkeypatch.setattr(fpm, "as_root", _exec_as_root(scripts))
    props = {"nemud.k%d" % i: str(i) for i in range(20)}
    props["service.adb.root"] = "1"
    props["ro.product.model"] = "V2405A"
    d = _Dev(props)
    r = st.refresh(d, {}, None)
    assert len(scripts) == 1, "发了 %d 次 as_root（应批量成一条脚本）" % len(scripts)
    assert len(r["deleted"]) == 21, r
    # 每个键都要"读回为空"才算删掉（命令返回码不可信）
    assert "getprop" in scripts[0] and "GONE" in scripts[0]


def test_refresh_says_unknown_when_offline():
    class _Dead:
        def _sh(self, *a, timeout=None):
            return ""
    r = st.refresh(_Dead(), {}, None)
    assert r["ok"] is False
    assert "没读到" in r["detail"]


def test_refresh_without_resetprop_still_clears_writable(monkeypatch):
    """没有 magisk 时仍走 setprop 清空值（非 ro.* 有效）。"""
    monkeypatch.setattr(fpm, "_magisk", lambda dev: "")
    scripts = []
    monkeypatch.setattr(fpm, "as_root", _exec_as_root(scripts))
    d = _Dev({"service.adb.root": "1"})
    r = st.refresh(d, {}, None)
    assert "service.adb.root" in r["deleted"], r
    assert "setprop" in scripts[0]
