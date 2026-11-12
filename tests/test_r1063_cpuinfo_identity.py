# -*- coding: utf-8 -*-
"""r1063 T89：`/proc/cpuinfo` 按身份渲染 + `consistency` CLI。

真机踩到的新矛盾：把身份换成 Xiaomi 14（骁龙 8 Gen 3 / SM8650）之后，
`/proc/cpuinfo` 的 `Hardware` 仍是 `MT6991`（联发科）——因为
`render_fake_cpuinfo()` 把机型写死了。审计立刻报出来：

```
[high] ro.soc.model vs cpuinfo   现=SM8650   应=MT6991
```

修成按 `ro.soc.model` 渲染后：

```
[high] ro.product.cpu.abilist    现=…,x86_64,x86      ← 只剩这一条（改不了）
```

顺带给 `core.android.consistency` 加了 CLI（文档里已经引用它）：

    python -m core.android.consistency          # 人读表格
    python -m core.android.consistency --json   # 机器可读；0=自洽，1=有高风险
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import consistency as C  # noqa: E402

BOOT = os.path.join(ROOT, "scripts", "identity_boot_module.py")


def _boot_module():
    """加载开机器生成脚本。仓库忽略 `scripts/`，缺失时 skip（不是红）。"""
    import importlib.util
    if not os.path.exists(BOOT):
        import pytest
        pytest.skip("scripts/identity_boot_module.py 不在仓库（gitignored）")
    spec = importlib.util.spec_from_file_location("ibm_t89", BOOT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _hw(txt):
    return [ln for ln in txt.splitlines() if ln.startswith("Hardware")][0]


def test_cpuinfo_follows_the_identity_soc():
    m = _boot_module()
    assert "SM8650" in _hw(m.render_fake_cpuinfo({"ro.soc.model": "SM8650"}))
    assert "MT6991" in _hw(m.render_fake_cpuinfo({"ro.soc.model": "MT6991"}))
    diff = _hw(m.render_fake_cpuinfo({"ro.soc.model": "SM8650"})) != \
        _hw(m.render_fake_cpuinfo({"ro.soc.model": "MT6991"}))
    assert diff, "不同 SoC 必须渲染出不同的 Hardware 行"


def test_cpuinfo_unknown_soc_still_arm_and_honest():
    m = _boot_module()
    txt = m.render_fake_cpuinfo({"ro.soc.model": "ZZ9999"})
    assert "CPU implementer\t: 0x41" in txt, "必须是 ARM 视图（隐藏宿主 Intel）"
    assert "ZZ9999" in _hw(txt), "认不出也要如实写当前 SoC，别编"


def test_cpuinfo_never_leaks_host_cpu():
    m = _boot_module()
    for soc in ("SM8650", "MT6991", "ZZ9999"):
        txt = m.render_fake_cpuinfo({"ro.soc.model": soc})
        assert "Intel" not in txt and "GenuineIntel" not in txt


def test_consistency_cli_exists():
    src = io.open(os.path.join(ROOT, "core", "android", "consistency.py"),
                  encoding="utf-8").read()
    assert "def _main" in src and "__main__" in src
    assert "--json" in src


def test_audit_flags_cpuinfo_vs_soc_mismatch():
    """这条正是本轮真机撞到的：身份换骁龙、cpuinfo 还写联发科。"""
    facts = {"soc_model": "SM8650", "cpuinfo_hardware": "MT6991",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.soc.model vs cpuinfo" in keys
