# -*- coding: utf-8 -*-
"""r920：身份的唯一来源是 **MuMu 官方设置**，机型池只兜底。

2026-11-03 实测本机：

    MuMu  phone_brand=Samsung / phone_miit=SM-A5260
    设备  ro.product.brand=Samsung / ro.product.model=SM-A5260
    我们  setprop ro.product.model <池里的机型>  → 静默无效（系统盘只读）

结论：**官方注入是唯一真正生效的来源**。如果身份档案仍按池写 Redmi K50，
就会"档案说 Redmi、设备是 Samsung"——报告骗自己，风控读到的却是另一套。
所以身份生成顺序改为 官方 > 池，本文件钉住这件事。

另外钉一个踩过的细节：MuMu 的 ``resolution_width=1600 / height=900`` 是
**窗口**尺寸，Android 侧 ``wm size`` 报 ``900x1600``（竖屏）——两者转置，
档案要折算成「短边×长边」，否则会声明一个设备没有的横屏分辨率。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r920_identity_from_vendor.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402

_LOG = logging.getLogger("test_r920")

_VENDOR = {
    "phone_brand": "Samsung",
    "phone_model": "Galaxy A52 5G",
    "phone_miit": "SM-A5260",
    "phone_imei": "865247046277134",
    "resolution_width": "1600.000000",
    "resolution_height": "900.000000",
    "resolution_dpi": "240.000000",
}


# ---------------------------------------------------------------------------
# 1. 官方优先
# ---------------------------------------------------------------------------
def test_build_from_vendor_uses_official_values():
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    p = ident.profile
    assert ident.data["source"] == "vendor"
    assert p["brand"] == "Samsung"
    assert p["manufacturer"] == "Samsung"
    assert p["model"] == "SM-A5260"          # ro.product.model 由 miit 注入
    assert p["marketing_model"] == "Galaxy A52 5G"
    assert ident.data["imei"] == "865247046277134"


def test_props_reflect_official_not_pool():
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    props = ident.props()
    assert props["ro.product.brand"] == "Samsung"
    assert props["ro.product.model"] == "SM-A5260"
    assert props["ro.product.manufacturer"] == "Samsung"


def test_display_is_folded_to_portrait():
    """窗口 1600x900 → 设备 900x1600（竖屏），档案必须折算。"""
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    assert ident.profile["display"] == [900, 1600]
    assert ident.profile["density"] == 240


def test_fingerprint_is_coherent_with_official():
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    f = ident.profile["fingerprint"]
    assert f.startswith("Samsung/SM-A5260/SM-A5260")
    assert "release-keys" in f


# ---------------------------------------------------------------------------
# 2. 官方没值 → 退回池（行为不变）
# ---------------------------------------------------------------------------
def test_empty_vendor_falls_back_to_pool():
    a = fp.build_from_vendor({}, 7, vm=0)
    b = fp.build(7, vm=0)
    assert a.profile == b.profile
    assert a.data.get("source") is None


def test_partial_vendor_keeps_derived_ids():
    """官方只给品牌时，android_id / 序列号仍由 seed 派生且稳定。"""
    vend = {"phone_brand": "Redmi"}
    a = fp.build_from_vendor(vend, 7, vm=0)
    b = fp.build_from_vendor(vend, 7, vm=0)
    assert a.android_id == b.android_id and len(a.android_id) == 16
    assert a.serial == b.serial
    assert a.profile["brand"] == "Redmi"


# ---------------------------------------------------------------------------
# 3. ensure() 接线：新身份走官方
# ---------------------------------------------------------------------------
class _Dev:
    """假设备：不是模拟器也能走完 ensure 的前半段判断。"""

    def __init__(self):
        self.props = {"ro.product.model": "SM-A5260",
                      "ro.product.brand": "Samsung",
                      "ro.kernel.qemu": ""}

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if "boot_id" in cmd:
            return "boot-x"
        return ""


def test_ensure_prefers_vendor_when_creating(tmp_path, monkeypatch):
    from core.android import vendor as vendor_mod
    monkeypatch.setattr(vendor_mod, "read", lambda *a, **k: dict(_VENDOR))
    dev = _Dev()
    rep = fp.ensure(dev, {"android": {"identity": {"enabled": True}}},
                    _LOG, user_data_dir=str(tmp_path), profile="device", vm=0)
    assert rep["ok"] is True
    # 非模拟器 → 不写 props，但身份已按官方值生成并落盘
    saved = fp.default_store(str(tmp_path), "device").get(0)
    assert saved.ident_id
    assert saved.profile["brand"] == "Samsung"
    assert saved.profile["model"] == "SM-A5260"


def test_ensure_can_disable_vendor_preference(tmp_path, monkeypatch):
    from core.android import vendor as vendor_mod
    calls = []
    monkeypatch.setattr(vendor_mod, "read",
                        lambda *a, **k: calls.append(1) or dict(_VENDOR))
    dev = _Dev()
    cfg = {"android": {"identity": {"enabled": True,
                                    "prefer_vendor": False}}}
    fp.ensure(dev, cfg, _LOG, user_data_dir=str(tmp_path),
              profile="device", vm=0)
    assert calls == []          # 关掉就完全不查官方


# ---------------------------------------------------------------------------
# 4. 写 props 只有一份实现，且必须读回校验
# ---------------------------------------------------------------------------
class _NoWriteDev:
    """模拟只读系统盘：setprop 全部"返回 0"但值不变。"""

    def __init__(self):
        self.props = {"ro.product.brand": "MuMu",
                      "ro.product.model": "MuMu"}
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if "command -v su" in cmd:
            return "/system/bin/su"
        if "command -v resetprop" in cmd:
            return ""
        if "setprop" in cmd or "-n " in cmd:
            # 命令都"成功"，但 props 一个都不变 —— 这就是只读系统盘的真实行为
            import re as _re
            return "\n".join("OK " + m.group(1) for m in _re.finditer(
                r"(?:setprop|-n)\s+'([^']+)'\s+'[^']*'", cmd))
        return ""


def test_apply_reports_zero_verified_when_disk_readonly(tmp_path):
    """命令报成功但读回没变 → verified 必须为 0（不许假阳性）。"""
    dev = _NoWriteDev()
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    rep = fp.apply(dev, ident, uid=False)
    assert rep["applied"], rep          # 命令层确实"报成功"了
    assert rep["verified"] == [], rep   # 但读回一条都没生效
    assert rep["mismatch"], rep         # 差异被如实记下来


def test_apply_uses_shared_implementation(tmp_path, monkeypatch):
    """apply 必须委托给 abi_canary.apply_props（唯一实现）。"""
    from core.android import abi_canary
    seen = {}

    def _fake(dev, mapping, use_root=True):
        seen["keys"] = sorted(mapping)
        return {"applied": [], "verified": [], "failed": [], "mismatch": {},
                "unchanged": [], "resetprop": ""}
    monkeypatch.setattr(abi_canary, "apply_props", _fake)
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    rep = fp.apply(_NoWriteDev(), ident, uid=False)
    assert seen["keys"] == sorted(ident.props())   # 整份 props 交给共享实现
    assert rep["verified"] == []
