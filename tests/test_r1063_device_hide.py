# -*- coding: utf-8 -*-
"""r1063 T106：设备隐藏层体检（`python -m core.android.hide`）。

这一轮把"携程 50003 / 阿里滑块点完就堵"查到底了，过程是手工的，所以要变成命令：

真机实测（飞猪进程 `/proc/<pid>/maps`）：

| 时间点 | 泄漏 |
|---|---|
| 模块三个被禁用、DenyList 强制未开 | `magisk` ×6、`nemu` ×1、`houdini` ×5 |
| 启用 HMA + hide_my_goldfish、开 `denylist_enforce=1`、重启 | **`nemu` ×1、`houdini` ×5** |

* `magisk` 消失 → **root 隐藏生效了**（这就是"Magisk 隐藏模块很强大"的正确用法）；
* `houdini` = `/system/lib64/libhoudini.so`（`r-xp`，正在执行）——**ARM→x86 翻译层**，
  真机绝无此物。这是"这是模拟器"最硬的证据，改 abilist 消不掉（改了携程还 SIGSEGV）；
* `nemu` = `/dev/__properties__/…vendor_nemu_default_prop:s0`，SELinux 属性上下文**文件名**，
  `mumu_cloak` 只 hook 属性名与 `/system/bin` 路径，盖不到它。

另外修了一个**误报**：裸子串 `ksu` 会命中文 `/system/lib64/libvndksupport.so`
（`vndKSUpport`），所以细词一律按具体路径匹配。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import hide  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_markers_are_path_specific_not_bare_substrings():
    assert isinstance(hide.MARKERS, dict)
    # 裸 "ksu" 会误命中 libvndKSUpport.so —— 必须用具体路径
    assert hide.MARKERS["kernelsu"] == "/data/adb/ksu"
    assert "ksu" not in hide.MARKERS.values()


def test_status_parses_settings_and_modules(monkeypatch):
    def fake(cmd, timeout=60):
        if "SELECT * FROM settings" in cmd:
            return "key=zygisk|value=1\n\nkey=denylist_enforce|value=1\n"
        if "denylist ls" in cmd:
            return "com.taobao.trip|com.taobao.trip\n"
        if "/data/adb/modules/" in cmd:
            return "on\n" if "shamiko" in cmd else "disabled\n"
        return ""

    monkeypatch.setattr(hide, "run", fake)
    st = hide.status()
    assert st["enforce"] is True
    assert st["settings"]["zygisk"] == "1"
    assert st["denylist"] == ["com.taobao.trip|com.taobao.trip"]
    assert st["modules"]["zygisk_shamiko"] == "on"
    assert st["modules"]["zygisk_vector"] == "disabled"


def test_fix_turns_on_enforce_and_enables_hidden_modules(monkeypatch):
    calls = []

    def fake(cmd, timeout=60):
        calls.append(cmd)
        if "SELECT * FROM settings" in cmd:
            return ""                      # enforce 未开、模块全 disabled
        if "/data/adb/modules/" in cmd:
            return "disabled\n"
        return ""

    monkeypatch.setattr(hide, "run", fake)
    rep = hide.fix()
    assert rep["ok"] is True
    assert rep["need_reboot"] is True
    assert any("denylist_enforce" in c for c in calls)
    assert any("rm -f /data/adb/modules/hma_oss_zygisk/disable" in c
               for c in calls), calls


def test_tells_reports_only_real_leaks(monkeypatch):
    def fake(cmd, timeout=60):
        if cmd.startswith("pidof"):
            return "4242\n"
        if "houdini" in cmd:
            return "5\n"
        if "nemu" in cmd:
            return "1\n"
        if "magisk" in cmd:
            return "0\n"
        return "0\n"

    monkeypatch.setattr(hide, "run", fake)
    rep = hide.tells("com.taobao.trip")
    assert rep["ok"] is False
    assert rep["leaks"] == {"houdini": 5, "nemu": 1}, rep


def test_tells_when_app_not_running(monkeypatch):
    monkeypatch.setattr(hide, "run", lambda cmd, timeout=60: "")
    rep = hide.tells("com.taobao.trip")
    assert rep["ok"] is False and "未运行" in rep["why"]


def test_cli_is_documented_in_module_docstring():
    src = io.open(os.path.join(ROOT, "core", "android", "hide.py"),
                  encoding="utf-8").read()
    for cmd in ("hide status", "hide fix", "hide tells"):
        assert cmd in src, cmd
    assert "houdini" in src and "denylist_enforce" in src
