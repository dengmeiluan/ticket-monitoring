# -*- coding: utf-8 -*-
"""r1063 T104：审计补上**电池软特征**——把"改不掉的铁证"如实并列出来。

用户反馈："错误一直都一样，一直都是 50003 和滑块点完就直接堵住"（App 渠道）。

这一轮把 App 侧还能查的东西查完了，结论是**证据面已经闭环**：

| 项 | 实测 | 能否改 |
|---|---|---|
| 设备脸（机型/平台/SoC/GPU/市场名） | 已自洽（`ro.board.platform=mt6991↔qcom`…） | ✅ 已改好 |
| **ABI** `arm64-v8a,…,x86_64,x86` | 含 x86 | ⛔ 改必崩（`abi_canary` 实测携程 **SIGSEGV**） |
| **电池电压** | `dumpsys` 读 0/3，`sysfs` 读 3300 mV（真机 3700–4400） | ⛔ `dumpsys battery set` 不支持 voltage；`su` 写 sysfs 也无效（内核只读） |
| 传感器 | 8 个硬件 + 8 个虚拟（真机量级） | ✅ 不是问题点 |

以前审计只报 ABI 一条，读者会以为"只差一点"；现在把电池这条也并列报出，
**面板上的「设备环境」会同时说清两条**——这才是诚实的读数。

`collect()` 现在多采：`battery_voltage / battery_temp / battery_level / battery_ac`；
`audit()` 多一条规则：电压 <3500 mV（含 0）→ mid + 说明"改不掉"。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import consistency as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_battery_voltage_low_is_flagged_as_unfixable():
    facts = {"soc_model": "SM8650", "cpuinfo_hardware":
             "Qualcomm Technologies, Inc SM8650",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi",
             "battery_voltage": "0"}
    rep = C.audit(facts)
    bat = [i for i in rep["items"] if i["key"].startswith("battery.")]
    assert bat, rep
    assert bat[0]["level"] == "mid"
    assert "改不掉" in bat[0]["hint"], bat[0]


def test_normal_battery_is_silent():
    facts = {"soc_model": "SM8650", "battery_voltage": "4185"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert not any(k.startswith("battery.") for k in keys), keys


def test_collect_has_battery_fields_in_source():
    src = io.open(os.path.join(ROOT, "core", "android", "consistency.py"),
                  encoding="utf-8").read()
    for k in ("battery_voltage", "battery_temp", "battery_level", "battery_ac"):
        assert k in src, k
