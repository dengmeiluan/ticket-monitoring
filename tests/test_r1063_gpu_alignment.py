# -*- coding: utf-8 -*-
"""r1063 T84：把设备身份**对齐到 GPU 家族**，消掉最后的结构性矛盾。

真机实测链条：
* MuMu 的 `gpu_model.custom` 只改型号串、**厂商前缀恒为 Qualcomm**，
  所以 `GL_RENDERER` 永远是 `Qualcomm, Adreno (TM) 750`；
* 而身份是 vivo X200 Pro（天玑 9400 / Mali）→ **GPU 与 SoC 不同家**，
  这正是风控判"环境异常"的依据（携程 50003 / 阿里强制滑块）。
* 把 GPU 串改成 Mali 试过：结果 `Qualcomm, Immortalis-G925`——高通不出 Mali，
  反而制造新矛盾（已改回 Adreno）。

**正解是反向对齐**：保持 GPU，把身份换成骁龙 8 Gen 3 机型（Xiaomi 23127PN0CC）。

审计结果：矛盾 **6 → 3 → 1**（最后一条是动不了的 x86 ABI）。
真机效果：**携程 App 不再强制登录**——首页正常、点「机票」直接进搜索页
（单程/往返/多程、上海→北京、11月16日、添加乘机人），`login_suspect=False`。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import align, consistency as C  # noqa: E402


def test_gpu_family_maps_to_models():
    assert "23127PN0CC" in align.GPU_TO_MODELS["Adreno"]
    assert "V2405A" in align.GPU_TO_MODELS["Mali"]


def test_mumu_ids_cover_every_pickable_model():
    for models in align.GPU_TO_MODELS.values():
        for m in models:
            assert m in align.MUMU_IDS, m


def test_plan_is_honest_without_device():
    rep = align.plan(None)
    # 没有设备读不到 GPU：要么给出机型，要么如实说"匹配不到"
    assert "gpu_family" in rep and "pick" in rep
    if rep["pick"] is None:
        assert rep["why"]


def test_apply_dry_run_never_writes():
    rep = align.apply(None, None, write=False)
    assert rep["applied"] is False
    assert rep["next_steps"], "必须告诉调用方：重生成开机模块 + 重启实例"


def test_audit_accepts_qualcomm_platform_codename():
    """高通机型 board=pineapple、hardware=qcom，与 SoC 串不同名是**正常**的。

    第一版审计拿 SoC 串去比 board/hardware，把 Xiaomi 14 误判成 2 处高风险。
    """
    facts = {"brand": "Xiaomi", "model": "23127PN0CC", "board": "pineapple",
             "hardware": "qcom", "soc_model": "SM8650",
             "soc_manufacturer": "Qualcomm", "marketname": "Xiaomi 14",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
             "gl_renderer": "Qualcomm Adreno (TM) 750"}
    rep = C.audit(facts)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" not in keys, rep
    assert "ro.hardware" not in keys, rep
    assert "GL_RENDERER" not in keys, "Qualcomm + Adreno 是自洽的"
    # 只剩 ABI 这条（已知动不了）
    assert keys == {"ro.product.cpu.abilist"}, rep


def test_audit_still_flags_mtk_mismatch():
    facts = {"board": "mt6897", "hardware": "mt6897", "soc_model": "MT6991",
             "cpuinfo_hardware": "MT6991"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.board.platform" in keys and "ro.hardware" in keys
