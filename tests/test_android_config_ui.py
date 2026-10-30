# -*- coding: utf-8 -*-
"""android.* 配置键必须可配：控件渲染 + 写回 + 回读，且范围与后端钳制一致。

背景：`config.example.yaml` 的 android: 段一旦加了键，配置页就必须有
对应控件——否则用户只能改文件，违背「配置页不允许存在无法配置的项」。
本文件把这条约束钉在门禁里，与 test_r523 同套路（按控件 id 判定，
因为只查 `GLB.android=` 赋值会在删掉 glcell 后假绿）。

同时校验**界面取值范围 == 后端钳制范围**：两边不一致时，用户能填出
一个后端会悄悄改掉的值，界面显示与实际生效值不符。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.config import normalize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 控件 id ↔ 后端字段
_CONTROLS = {
    "glbAndEn": "enabled",
    "glbAndPv": "provider",
    "glbAndDir": "install_dir",
    "glbAndVm": "vm_index",
    "glbAndBoot": "boot_timeout_s",
    "glbAndAct": "action_timeout_s",
    "glbAndSnap": "snapshot",
}


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_every_android_key_has_a_rendered_control():
    w = _w()
    for cid, key in _CONTROLS.items():
        assert "'%s'" % cid in w, f"android.{key} 没有渲染控件（id={cid}）"
        assert f"{key}:" in w, f"android.{key} 没有写回表达式"


def test_config_page_reads_android_section():
    """GET /api/config 必须把 android 段吐给前端，否则控件永远显示默认值。"""
    w = _w()
    assert re.search(r'"android"\s*:\s*dict\(cfg\.get\("android"\)', w), \
        "配置读回缺少 android 段"


def test_config_page_writes_android_section():
    """POST /api/config 必须落盘 android 段。"""
    w = _w()
    assert re.search(r'cfg\["android"\]\s*=', w), "配置写回缺少 android 段"


def test_ui_ranges_match_backend_clamps():
    """界面 min/max 必须与后端钳制一致（否则显示值与生效值不符）。"""
    w = _w()
    checks = [
        ("glbAndVm", 0, 64),
        ("glbAndBoot", 10, 600),
        ("glbAndAct", 5, 900),
    ]
    for cid, lo, hi in checks:
        idx = w.find("'%s'" % cid)
        assert idx > 0, cid
        seg = w[idx:idx + 400]
        assert f"Math.max({lo}" in seg, f"{cid} 下限应为 {lo}"
        assert f"Math.min({hi}" in seg, f"{cid} 上限应为 {hi}"


def test_backend_clamps_match_ui():
    """反方向：后端钳制的边界值与界面写的一致。"""
    assert normalize({"enabled": True, "vm_index": -5}).vm_index == 0
    assert normalize({"enabled": True, "vm_index": 999}).vm_index == 64
    assert normalize({"enabled": True, "boot_timeout_s": 1}).boot_timeout_s == 10
    assert normalize({"enabled": True,
                      "boot_timeout_s": 9999}).boot_timeout_s == 600
    assert normalize({"enabled": True,
                      "action_timeout_s": 1}).action_timeout_s == 5
    assert normalize({"enabled": True,
                      "action_timeout_s": 9999}).action_timeout_s == 900


def test_disabled_by_default_in_example_config():
    """示例配置必须 enabled: false——新用户不该被默认拉起 7GB 模拟器。"""
    p = os.path.join(ROOT, "config.example.yaml")
    text = io.open(p, encoding="utf-8", newline="").read()
    m = re.search(r"^android:\s*$", text, re.M)
    assert m, "config.example.yaml 缺少 android: 段"
    block = text[m.end():m.end() + 400]
    assert re.search(r"^\s+enabled:\s*false", block, re.M), \
        "android.enabled 在示例配置里必须是 false"
