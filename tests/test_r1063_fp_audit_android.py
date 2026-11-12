# -*- coding: utf-8 -*-
"""r1063 T32：App 侧身份核账（PC 与 App 同表才算"全链路"）。

PC 侧核的是「UA / UA-CH / TLS 之间」；App 侧要核的是「机型 / 指纹 / SoC / 构建之间」。
**当场抓到一个真矛盾**：realme RMX3350 的 `fingerprint` 写 `realme/RMX3350/RMX3350`
而 `device` 声明 `RE5C7D` —— 真机上这两个字段恒等，这一条就够判定。已按指纹对齐修正。
"""
import io
import os

from core import fp_audit as fa


def _good():
    return {"brand": "Redmi", "model": "Redmi K50", "device": "rubens",
            "product": "rubens", "release": "12",
            "soc": "MediaTek Dimensity 8100", "hardware": "mt6895",
            "fingerprint": "Redmi/rubens/rubens:12/SP1A.210812.016/V13:user/release-keys"}


def test_good_entry_is_clean():
    assert fa.check_android_identity(_good(), {}) == []


def test_device_must_match_fingerprint_segment():
    bad = dict(_good(), device="RE5C7D")     # 真机上 device 与指纹第三段恒等
    hits = fa.check_android_identity(bad, {})
    assert any(h["id"] == "android_fp_shape" for h in hits), hits


def test_brand_must_match_fingerprint():
    bad = dict(_good(), brand="realme")
    assert any(h["id"] == "android_fp_shape"
               for h in fa.check_android_identity(bad, {}))


def test_release_must_match_fingerprint():
    bad = dict(_good(), release="13")
    assert any(h["id"] == "android_fp_shape"
               for h in fa.check_android_identity(bad, {}))


def test_emulator_codenames_are_flagged():
    for mark in ("missi_", "mumu_", "sdk_gphone", "vbox", "emulator"):
        bad = dict(_good(), fingerprint="Redmi/%s/rubens:12/x/y:user" % mark)
        hits = fa.check_android_identity(bad, {})
        assert any(h["id"] == "android_emulator" for h in hits), (mark, hits)


def test_soc_must_be_mapped_and_match_hardware():
    # 传显式映射表，让这条判定在"映射表是否可用"之外仍然可测
    smap = {"MediaTek Dimensity 8100": "MT6895"}
    # 未知 SoC → ro.soc.model 会缺，而真机必报
    bad = dict(_good(), soc="MediaTek Dimensity 9999")
    assert any(h["id"] == "android_soc"
               for h in fa.check_android_identity(bad, {}, soc_map=smap))
    # 厂商与 hardware 不一致
    bad2 = dict(_good(), hardware="qcom")
    assert any(h["id"] == "android_soc"
               for h in fa.check_android_identity(bad2, {}, soc_map=smap))
    # 读不到映射表时**不判**（不许产生假警报）
    assert fa.check_android_identity(bad, {}, soc_map={}) == []


def test_debug_build_is_flagged():
    props = {"ro.build.tags": "test-keys", "ro.build.type": "userdebug"}
    hits = fa.check_android_identity(_good(), props)
    assert any(h["id"] == "android_build" for h in hits), hits


def test_repo_pool_is_self_consistent():
    """仓库自带的机型池必须 0 矛盾——这条会在有人改池子时立刻失败。"""
    n, hits = fa.audit_pool()
    assert n >= 5, n
    assert hits == [], fa.summary(hits)


def test_payload_has_three_cases_including_app_pool():
    import webui

    fp = (webui._strategy_payload() or {}).get("fingerprint") or []
    names = [x["name"] for x in fp]
    assert names == ["桌面档", "移动档", "App 机型池"], names
    assert all(x["count"] == 0 for x in fp), fp
