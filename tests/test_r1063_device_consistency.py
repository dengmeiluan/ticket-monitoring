# -*- coding: utf-8 -*-
"""r1063 T83：设备环境自洽性审计 + props 自洽修复（携程 50003 的取证与处置）。

用户长期问题：**携程 App 登录固定 50003**；飞猪点「机票」弹阿里 NC 滑块、一滑就
`请点我重试(error:xxxx)`；而同一台机的智行/去哪儿 App 正常出数。

真机审计（`core/android/consistency.py`）取到的**硬矛盾**：

| 项 | 修前 | 真机应有 | 现在 |
|---|---|---|---|
| `ro.board.platform` | mt6897（天玑9300）| mt6991 | ✅ mt6991 |
| `ro.hardware` | mt6897 | mt6991 | ✅ mt6991 |
| `ro.soc.manufacturer` | 空 | MediaTek | ✅ MediaTek |
| `ro.product.marketname` | 空 | vivo X200 Pro | ✅ vivo X200 Pro |
| `GL_RENDERER` | Qualcomm Adreno 750 | MT6991 应为 Mali | ⚠️ 见下 |
| `cpu.abilist` | 含 x86_64,x86 | 只有 ARM | ⛔ 动不得（会 SIGSEGV）|

修完重启实例后：**6 处矛盾 → 1 处**（只剩 ABI）。

关于 GPU 那条：MuMu 的 `gpu_model.custom` 只改型号串、**厂商前缀仍是 Qualcomm**，
把它改成 Mali 会得到 `Qualcomm, Immortalis-G925`——本身又是新矛盾（高通不出 Mali）。
正确做法是**反向对齐**：保持 `Adreno 750`，把设备身份换成骁龙 8 Gen 3 机型
（池里第 10 项 Xiaomi 23127PN0CC 就是），这才 1:1 自洽。

关于 ABI：`abi_canary` 已实测把 ABI 改成 arm64 会让**携程 SIGSEGV**
（加固 so 与 ABI 绑定），落盘判定 `ok=false`，所以 `spoof_allowed('ctrip.android.view')`
为 False —— 这条路目前是关的。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import consistency as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REAL = {
    "brand": "vivo", "model": "V2405A", "board": "mt6897",
    "hardware": "mt6897", "soc_model": "MT6991", "soc_manufacturer": "",
    "marketname": "", "abilist": "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
    "cpuinfo_hardware": "MT6991", "gl_renderer": "Qualcomm Adreno (TM) 750",
}

FIXED = dict(REAL, board="mt6991", hardware="mt6991",
             soc_manufacturer="MediaTek", marketname="vivo X200 Pro")


def test_audit_flags_the_real_contradictions():
    rep = C.audit(REAL)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" in keys
    assert "ro.hardware" in keys
    assert "GL_RENDERER" in keys
    assert "ro.product.cpu.abilist" in keys
    assert rep["ok"] is False
    assert rep["high"] >= 4


def test_audit_is_clean_after_alignment_except_abi():
    rep = C.audit(FIXED)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" not in keys
    assert "ro.hardware" not in keys
    assert "ro.soc.manufacturer" not in keys
    # ABI 是已知"动不得"的那条，仍然会被点出来（如实）
    assert "ro.product.cpu.abilist" in keys


def test_gpu_family_mapping():
    fam, marks = C._soc_family("MT6991")
    assert fam == "ARM Mali" and "Immortalis" in marks
    fam2, marks2 = C._soc_family("SM8650")
    assert fam2 == "Qualcomm" and "Adreno" in marks2
    assert C._soc_family("") == (None, ())


def test_abi_item_explains_why_it_cannot_be_changed():
    rep = C.audit(REAL)
    abi = next(i for i in rep["items"] if i["key"] == "ro.product.cpu.abilist")
    assert "abi_canary" in abi["hint"] and "SIGSEGV" in abi["hint"]


def test_pool_platform_matches_soc_for_v2405a():
    """池里 V2405A 曾填 mt6897（天玑9300），而它是天玑 9400 —— 矛盾的源头。"""
    from core.android import fingerprint as fp
    for p in fp.PHONE_POOL:
        if p.get("model") == "V2405A":
            assert "9400" in str(p.get("soc")), p
            assert str(p.get("platform")).lower() == "mt6991", p
            assert str(p.get("hardware")).lower() == "mt6991", p
            break
    else:
        raise AssertionError("池里没有 V2405A")


def test_props_are_self_consistent():
    """props 里 SoC/平台/厂商/市场名必须同一套（用池里 V2405A 直接构造）。"""
    from core.android import fingerprint as fp

    entry = [p for p in fp.PHONE_POOL if p.get("model") == "V2405A"]
    assert entry, "池里必须有 V2405A"
    ident = fp.Identity({"vm": 0, "profile": entry[0], "android_id": "a1",
                         "serial": "SN1", "imei": "865247046277134"})
    props = ident.props()
    assert props["ro.hardware"] == props["ro.board.platform"], props
    assert props["ro.soc.model"] == "MT6991", props
    assert props["ro.soc.manufacturer"] == "MediaTek", props
    assert props["ro.product.marketname"] == "vivo X200 Pro", props

def test_collect_never_raises_on_dumb_device():
    class _Dumb:
        pass

    facts = C.collect(_Dumb())
    assert isinstance(facts, dict)
