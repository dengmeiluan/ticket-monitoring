# -*- coding: utf-8 -*-
"""r951：自检报 88 分却不解释"这 12 分永远拿不回来"——噪音会让人不看自检。

2026-11-04 实测：修完所有能修的（`ro.nemu`、`nemud.*`、root 痕迹），
`audit()` 仍稳定报 **88 分**，扣分的两条是：

```
ro.product.cpu.abi     = x86_64                 fix: identity
ro.product.cpu.abilist = x86_64,arm64-v8a,x86   fix: identity
```

两个问题叠在一起：

1. **它们不可清除** —— 这台机器真实架构就是 x86_64。自检分数里
   含一项永远消不掉的扣分，数字就失去了"回到 100 表示干净"的含义；
2. **`fix: identity` 是危险建议** —— 照它去改全局 ABI，linker 会去找
   arm 的库目录，系统直接起不来。今天已经踩过同源一次：
   按"改 SDK 让指纹更自洽"的思路把 `ro.build.version.sdk` 35→33，
   结果 `libdl_android.so is not accessible`，**携程启动失败**。

有效的缓解是**包级 ABI**（`abi-select` 表把每个包的
`primaryCpuAbi=arm64-v8a`），那部分已实现并实测过。

修法（不把风险抹成 0 分，只把事实说清）：

* leaks 仍然计入、分数不变——**不粉饰**；
* 但 `fix` 改指向正确手段（包级 ABI），并标 `unfixable`；
* 返回 `score_ceiling` + `score_note`，明说"上限就在这，为什么"。

这样操作员看见 88 知道**天花板在哪**，而不是反复折腾改不得的键。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r951_audit_ceiling.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402


def _audit_for(props_map):
    class _D:
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.strip() == "shell getprop":
                return "\n".join("[%s]: [%s]" % (k, v)
                                 for k, v in props_map.items())
            if cmd.startswith("shell getprop "):
                return props_map.get(cmd.split(" ", 2)[2], "")
            if "test -e" in cmd:
                return "TM_NO"
            return ""
    return fp.audit(_D())


# ---------------------------------------------------------------------------
# 1. 不可清除项：仍然扣分（不粉饰），但 fix 必须指向安全手段
# ---------------------------------------------------------------------------
def test_unfixable_still_counts_as_leak():
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64,arm64-v8a,x86",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    abi = [x for x in a["leaks"] if "cpu.abi" in str(x.get("key"))]
    assert abi, "全局 ABI 泄漏仍应计入（不能抹成 0 分）"
    assert a["score"] < 100, a["score"]


def test_fix_no_longer_suggests_global_rewrite():
    """`fix: identity` 会引导人去改全局架构 → 系统起不来。"""
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    for x in a["leaks"]:
        if x.get("unfixable"):
            assert x.get("fix") != "identity", x
            assert "abi-select" in x.get("fix", "") or "包级" in x.get("fix", ""), x


def test_ceiling_reported_and_explained():
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    assert a.get("unfixable") == 2, a.get("unfixable")
    # ceiling = 把所有**可修**的清掉之后的分数 = 100 - 6*不可修数
    assert a.get("score_ceiling") == 100 - 6 * a["unfixable"], a.get("score_ceiling")
    # score 永远 <= ceiling；低于它就是"还有能修的没修"
    assert a["score"] <= a["score_ceiling"], (a["score"], a["score_ceiling"])
    note = a.get("score_note") or ""
    assert "上限" in note and "真实架构" in note, note
    if a.get("fixable_left"):
        assert "可修未修" in note, note


def test_clean_device_has_no_ceiling_note():
    a = _audit_for({"ro.product.model": "V2405A", "ro.product.brand": "vivo",
                    "ro.product.cpu.abi": "arm64-v8a",
                    "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a"})
    assert a.get("unfixable") == 0
    assert a.get("score_note") == ""


# ---------------------------------------------------------------------------
# 2. 档案同步：必须复用已读的 props，且在 fast path 之后
# ---------------------------------------------------------------------------
def test_profile_sync_reuses_props():
    """档案同步若在 fast path 之前，每次"本 boot 已应用"都要多一次 getprop。"""
    src = io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                  encoding="utf-8").read()
    i_fast = src.find('marker == "%s %s" % (ident.ident_id, boot)')
    i_sync = src.find("既有身份也要跟官方对齐")
    i_plain = src.find("plain = props_of(dev)")
    assert 0 < i_fast < i_sync, "档案同步必须放在 fast path 判定之后"
    assert i_plain < i_sync, "同步应在 props 读好之后"
    # 同步块里不许再自己读一次 props
    blk = src[i_sync:i_sync + 3500]
    assert "props_of(dev)" not in blk, "同步块重复读 props（多花一条完整 getprop）"
