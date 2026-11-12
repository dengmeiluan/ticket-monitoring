# -*- coding: utf-8 -*-
"""r942：`ro.*` 清不动却报"已清空 42 条"——假成功比失败更坏。

2026-11-04 实机复核发现的完整事实链：

1. 携程 App 登录提交验证码时报 **`存在风险，限制登录 50003`**；
2. 排查设备指纹，`detect()` 报出 `ro.nemu=1`、`ro.build.version.nemux=true`；
3. 跑 `hide()`，它报 **「props:8 set / 0 deleted / 42 cleared」**；
4. 复核 `getprop | grep nemud` → **40 条键仍在**（但**值全为空 `[]`**，
   说明可写键的清空是有效的）；
5. `ro.nemu` 复核 → **仍是 `1`**，一条都没清。

第 5 条就是假成功：`setprop ro.nemu ''` 返回 0（成功）但值不变
——和第 3 轮"setprop 返回 0 但值不变"完全同源。

修法：`ro.*` **在没有 resetprop 时不放进清理脚本**，而是单独列进
`props-readonly`，`why` 里点名具体键并说明"需 Magisk resetprop"。
这样操作员看到的是"这 2 条改不动，该装 Magisk"，而不是"已经清干净了"。

顺带说明两件事（都已实测确认）：

* `nemud.*` 40 条**值全为空**，Ctrip SDK 读值，空值无信息量 → 这部分有效；
* `ro.nemu` 硬编码在 `/system/bin/nemuinit`（5.19MB 二进制），
  **不在任何 `.config` 文本里** → 改 config 不可行（方向 2 判定失败）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r942_readonly_props.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import stealth as st  # noqa: E402


class FakeDev:
    """够 hide() 跑起来的假设备：root 可用、无 Magisk、给定 props。"""

    def __init__(self, props):
        self.props = dict(props)
        self.scripts = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if "pm list packages" in cmd:
            return ""
        if "magisk" in cmd:
            return ""
        if "input keyevent" in cmd:
            return ""
        if "test -e" in cmd:
            return "TM_NO"
        return ""


def _run_hide(monkeypatch, props):
    d = FakeDev(props)
    monkeypatch.setattr(st, "_root", lambda dev: True)
    monkeypatch.setattr(st, "_magisk", lambda dev: "")
    captured = {}

    def _as_root(dev, script, timeout=None):
        captured["script"] = script
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)
    rep = st.hide(d, packages=["ctrip"], config={})
    return rep, captured.get("script", "")


# ---------------------------------------------------------------------------
# 1. 核心：ro.* 不进清理脚本（别再假成功）
# ---------------------------------------------------------------------------
def test_ro_props_not_put_in_clear_script(monkeypatch):
    rep, script = _run_hide(monkeypatch, {
        "ro.nemu": "1",
        "ro.build.version.nemux": "true",
        "nemud.fps_limit": "60",
    })
    assert "ro.nemu" not in script, "ro.nemu 仍在清理脚本里（会假成功）"
    assert "ro.build.version.nemux" not in script, "nemux 仍在清理脚本里"
    # 可写键仍然要清
    assert "nemud.fps_limit" in script, "可写键 nemed.* 没被清"


def test_readonly_props_reported_explicitly(monkeypatch):
    rep, _ = _run_hide(monkeypatch, {
        "ro.nemu": "1",
        "ro.build.version.nemux": "true",
    })
    acts = rep.get("actions") or []
    ro_act = [a for a in acts if str(a.get("cmd", "")).startswith(
        "props-readonly:")]
    assert ro_act, "没有 props-readonly 这一条（会让人以为清干净了）"
    why = str(ro_act[0].get("why") or "")
    assert "ro.nemu" in why, "why 里没点名 ro.nemu"
    assert "Magisk" in why, "why 里没说明根治手段"


def test_no_false_cleared_count(monkeypatch):
    """`cleared` 数字不许把 ro.* 算进去。"""
    rep, _ = _run_hide(monkeypatch, {"ro.nemu": "1", "nemud.x": "1"})
    acts = rep.get("actions") or []
    for a in acts:
        c = str(a.get("cmd") or "")
        if c.startswith("props:"):
            # 只应有 1 条 cleared（nemud.x），不是 2
            assert "2 cleared" not in c, "cleared 计数把 ro.* 也算进去了：%s" % c
            break
    else:
        raise AssertionError("没找到 props 动作")


# ---------------------------------------------------------------------------
# 2. 有 Magisk 时走 resetprop --delete（re 键一起消掉）
# ---------------------------------------------------------------------------
def test_with_magisk_uses_resetprop(monkeypatch):
    """有 Magisk 时 ro.nemu 必须走 resetprop --delete（而不是 setprop 空串）。

    `as_root` 会被调用多次（denylist 探测、magisk sqlite 探测、清理脚本…），
    所以要**收集全部调用**再找清理那一条。
    """
    d = FakeDev({"ro.nemu": "1"})
    monkeypatch.setattr(st, "_root", lambda dev: True)
    monkeypatch.setattr(st, "_magisk", lambda dev: "resetprop")
    scripts = []

    def _as_root(dev, script, timeout=None):
        scripts.append(script)
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)
    st.hide(d, packages=["ctrip"], config={})
    joined = chr(10).join(scripts)
    assert "ro.nemu" in joined, "有 Magisk 时 ro.nemu 没进任何脚本"
    # 找到含 ro.nemu 的那一段，确认是 --delete 而不是 setprop ''
    seg = [x for x in scripts if "ro.nemu" in x][0]
    assert "--delete" in seg, "ro.nemu 没用 resetprop --delete：%s" % seg[:120]


# ---------------------------------------------------------------------------
# 3. 源码钉
# ---------------------------------------------------------------------------
def test_source_handles_readonly_branch():
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    assert "props-readonly" in src, "没有 readonly 分支"
    assert 'key.startswith("ro.")' in src, "没有 ro.* 判定"
    assert "假成功" in src or ("返回 0" in src and "值不变" in src), \
        "没记录这个坑（下次又会写成假成功）"
