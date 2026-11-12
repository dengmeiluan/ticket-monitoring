# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1226_design_coords.py
- tests/test_r626_warmup_off_leaves_no_sticky_flag.py
- tests/test_r920_identity_from_vendor.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import logging
import os
import re
import sys

from core.android import fingerprint as fp
from core.android.device import AdbDevice
from core.pacing import Pacing


# ---- merged from tests/test_r1226_design_coords.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP_FILES = ["crawlers/app_qunar.py", "crawlers/app_tongcheng.py",
             "crawlers/app_ctrip.py", "crawlers/app_zhixing_nav.py"]


class FakeDev(AdbDevice):
    """只记录 input 命令，不碰真设备。"""

    def __init__(self, size):
        self._size = size
        self.calls = []
        self.design = None
        self._size_cache = None

    def window_size(self):
        return self._size

    def _sh(self, *args):
        self.calls.append(args)
        return "ok"


def test_tap_design_scales_from_basis():
    d = FakeDev((1260, 2800))
    assert d.tap_design(450, 420) is True
    assert d.calls[-1] == ("shell", "input", "tap", "630", "735"), d.calls[-1]


def test_swipe_design_scales_both_points_and_keeps_duration():
    d = FakeDev((1260, 2800))
    assert d.swipe_design(800, 700, 800, 300, 400) is True
    assert d.calls[-1] == ("shell", "input", "swipe", "1120", "1225",
                           "1120", "525", "400"), d.calls[-1]


def test_same_scale_when_device_matches_basis():
    """基准分辨率下必须逐位相等——否则老设备上的行为会被改坏。"""
    d = FakeDev((900, 1600))
    d.tap_design(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), d.calls[-1]


def test_unknown_size_is_safe():
    d = FakeDev((0, 0))
    d.tap_design(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), "读不到尺寸时应原样下发"


def test_plain_tap_still_unscaled_when_design_off():
    """负控：普通 `tap()`（设备坐标，UI 树路径）不许被换算。"""
    d = FakeDev((1260, 2800))
    d.tap(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), d.calls[-1]


def test_no_bare_hardcoded_coordinates_left():
    """门禁：这 4 个文件里不许再有 `dev.tap(<int>,<int>)` / `dev.swipe(<int>,…)`。"""
    pat_tap = re.compile(r"\.tap\(\s*\d+\s*,\s*\d+\s*\)")
    pat_swipe = re.compile(r"\.swipe\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+")
    bad = []
    for f in APP_FILES:
        s = io.open(os.path.join(ROOT, f), encoding="utf-8").read()
        for m in pat_tap.finditer(s):
            bad.append((f, m.group(0)))
        for m in pat_swipe.finditer(s):
            bad.append((f, m.group(0)))
    assert not bad, "还有写死坐标没换算：%s" % bad[:5]


# ---- merged from tests/test_r626_warmup_off_leaves_no_sticky_flag.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _p(warmup=True):
    return Pacing({"crawler": {"warmup": {"enabled": warmup}}})


def test_warmup_off_does_not_leave_a_sticky_flag():
    pac = _p(False)
    assert pac.cfg["warmup_enabled"] is False
    kind, cd = pac.observe("qunar", ["soft_reject"], "444")
    assert kind == "soft" and cd == 0, (kind, cd)
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is False, (
        "预热已关闭，却仍要求「下一轮先预热」——这个标志永远没人清：%s" % ch)


def test_warmup_off_still_keeps_the_soft_reject_visible():
    """事实要留痕：面板还得能说「这轮是软拒」。"""
    pac = _p(False)
    pac.observe("qunar", ["soft_reject"], "444")
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("reason") == "soft", (
        "关掉预热后连「软拒」这个归因也丢了：%s" % ch)


def test_warmup_on_behaviour_is_unchanged():
    """开启时一字不变（回归护栏）：软拒必须要求预热。"""
    pac = _p(True)
    kind, cd = pac.observe("qunar", ["soft_reject"], "444")
    assert kind == "soft" and cd == 0, (kind, cd)
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is True, (
        "开启预热时软拒没有要求预热（会把会话问题当 IP 问题）：%s" % ch)


def test_reopening_warmup_does_not_fire_a_stale_force():
    """软拒发生在预热关闭期间，重开预热后不该被当成「现在就要强制预热」。"""
    pac = _p(False)
    pac.observe("qunar", ["soft_reject"], "444")
    # 用户重开预热（热更新配置）
    pac.refresh({"crawler": {"warmup": {"enabled": True}}})
    ch = (pac.snapshot()["channels"].get("qunar") or {})
    assert ch.get("needs_warmup") is False, (
        "几小时前的软拒在重开预热后被当成当前状态，会立刻触发一次强制预热：%s"
        % ch)


def test_warmup_off_does_not_affect_login_wall():
    """登录墙不是软拒，不受预热开关影响（要引导去重登）。"""
    pac = _p(False)
    kind, cd = pac.observe("ctrip", ["login"], "请登录")
    assert kind == "login" and cd > 0, (kind, cd)


# ---- merged from tests/test_r920_identity_from_vendor.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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
    # 假设备上 `setprop ro.*` 无效，`ok` 由 `android_id`（settings put）决定；
    # 这里关心的是"身份来源选了 vendor"，不是"props 写进去了"。
    # 关心的是"身份选了 vendor 来源"，不是"props 写进去了"
    # （假设备上 ro.* 写不动，`ok` 现在如实为 False）。
    assert rep.get("identity") is not None
    assert rep.get("created") is True
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
    # 假设备的 `setprop` 是 no-op：命令层不报成功、也不该报成功。
    # 关键不变量是 **verified 为空**（没有任何一条被真改写）。
    assert not rep["verified"], rep
    assert rep["verified"] == [], rep   # 但读回一条都没生效
    # **不许假阳性有三种正确形态**：
    #   * 试了但没写进去 → `mismatch` 记下差异；
    #   * 机型/构建字段**根本不许运行中试** → `hot_write_skipped` 点名；
    #   * `ro.*` 差异**留给开机模块**（2026-11-05：运行期不再 `adb root`，
    #     因为那会把 adbd 打到握手卡死）→ `deferred_ro` 点名。
    # 三者都没有才说明"静默糊过去了"，那才是回归。
    assert (rep["mismatch"] or rep.get("hot_write_skipped")
            or rep.get("deferred_ro")), rep
    if rep.get("hot_write_skipped"):
        assert "官方键" in (rep.get("note") or ""), rep.get("note")


def test_apply_uses_shared_implementation(tmp_path, monkeypatch):
    """apply 必须委托给 abi_canary.apply_props（唯一实现）。"""
    from core.android import abi_canary
    seen = {}

    def _fake(dev, mapping, use_root=True, **kw):
        seen["keys"] = sorted(mapping)
        seen["allow"] = kw.get("allow_build_props")
        return {"applied": [], "verified": [], "failed": [], "mismatch": {},
                "unchanged": [], "resetprop": ""}
    monkeypatch.setattr(abi_canary, "apply_props", _fake)
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    rep = fp.apply(_NoWriteDev(), ident, uid=False)
    # 只把**非 ro 键**交给共享实现（`ro.*` 差异留给开机模块，运行期不写：
    # 写它们要 `adb root`，而本机 `adb root` 会把 adbd 打到握手卡死）。
    assert seen["keys"], "一条都没交给共享实现"
    assert set(seen["keys"]) <= set(ident.props()), seen["keys"]
    assert not [k for k in seen["keys"] if k.startswith("ro.")], seen["keys"]
    assert rep["verified"] == []
    # 不显式要求时不写机型/构建字段（保守默认保留）
    assert seen["allow"] is False


def test_apply_can_request_build_props(monkeypatch):
    """`allow_build_props=True` 必须透传到共享实现（50003 的硬判据在这批字段）。"""
    from core.android import abi_canary
    seen = {}

    def _fake(dev, mapping, use_root=True, **kw):
        seen["allow"] = kw.get("allow_build_props")
        return {"applied": [], "verified": [], "failed": [], "mismatch": {},
                "unchanged": [], "resetprop": ""}
    monkeypatch.setattr(abi_canary, "apply_props", _fake)
    ident = fp.build_from_vendor(_VENDOR, 7, vm=0)
    fp.apply(_NoWriteDev(), ident, uid=False, allow_build_props=True)
    assert seen["allow"] is True
