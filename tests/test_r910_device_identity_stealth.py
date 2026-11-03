# -*- coding: utf-8 -*-
"""设备身份 / root 隐藏：身份自洽、持久化、只在模拟器上动手、自检如实。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r910_device_identity_stealth.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402
from core.android import stealth as st  # noqa: E402

_MARKER = "/data/local/tmp/tm_ident_0.ok"
_STEALTH_MARK = "/data/local/tmp/tm_stealth_0.ok"


# ---------------------------------------------------------------------------
# 假设备：按命令子串路由，记录调用
# ---------------------------------------------------------------------------
class FakeDev:
    """最小 adb 替身：只实现本模块用到的那几条命令。"""

    def __init__(self, props=None, root=True, su=True, denylist=""):
        self.props = dict(props or {})
        self.is_root = root
        self.has_su = su
        self.denylist = denylist
        self.calls = []
        self._marker = ""
        self._stealth_mark = ""
        self._settings = {}

    # 与 AdbDevice 同签名（*args, timeout=None）
    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        return self._route(cmd)

    def _route(self, cmd):
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell id":
            return "uid=0(root) gid=0(root)" if self.is_root else "uid=2000(shell)"
        if "command -v su" in cmd:
            return "/system/bin/su" if self.has_su else ""
        if "command -v resetprop" in cmd:
            return ""
        if "boot_id" in cmd:
            return "boot-abc"
        if cmd.startswith("shell cat " + _MARKER) or cmd.startswith(
                "shell cat " + _STEALTH_MARK):
            return (self._marker if _MARKER in cmd else self._stealth_mark)
        if "> " + _MARKER in cmd:
            # echo '<id> <boot>' > /data/local/tmp/tm_ident_0.ok
            self._marker = cmd.split("echo ")[1].split(" >")[0].strip("'")
            return ""
        if "> " + _STEALTH_MARK in cmd:
            self._stealth_mark = cmd.split("echo ")[1].split(" >")[0].strip("'")
            return ""
        if "magisk" in cmd:
            if "denylist ls" in cmd:
                return self.denylist
            if "denylist add" in cmd:
                self.denylist += "\n" + cmd.split("denylist add ")[1].strip("'")
                return ""
            return ""
        if "setprop" in cmd or "-n " in cmd:
            # 每个 "OK <key>" / "FAIL <key>" 都按脚本里出现的键回放
            out = []
            for key in fp.PROP_KEYS:
                if key in cmd:
                    out.append("OK " + key)
            return "\n".join(out)
        if cmd.startswith("shell settings put secure android_id"):
            self._settings["android_id"] = cmd.rsplit(" ", 1)[-1]
            return ""
        if cmd.startswith("shell settings get secure android_id"):
            return self._settings.get("android_id", "")
        if cmd.startswith("shell settings put"):
            return ""
        if cmd.startswith("shell pm list packages"):
            return ""
        if cmd.startswith("shell am force-stop"):
            return ""
        if "ls /system/bin/su" in cmd:
            return ""
        if "grep -rlE" in cmd:
            return ""
        return ""

    # fingerprint.restart_framework 会等 boot_completed
    def sh(self, *args, timeout=None):
        return self._sh(*args, timeout=timeout)


_EMU_PROPS = {
    "ro.product.model": "MuMu",
    "ro.product.brand": "MuMu",
    "ro.product.manufacturer": "NetEase",
    "ro.hardware": "goldfish",
    "ro.kernel.qemu": "1",
    "ro.build.tags": "test-keys",
    "ro.build.type": "userdebug",
    "ro.debuggable": "1",
    "ro.secure": "0",
    "ro.product.cpu.abi": "x86_64",
    "ro.product.cpu.abilist": "x86_64,x86",
    "gsm.sim.state": "ABSENT",
    "gsm.sim.operator.numeric": "",
}

_REAL_PROPS = {
    "ro.product.model": "Redmi K50",
    "ro.product.brand": "Redmi",
    "ro.product.manufacturer": "Xiaomi",
    "ro.hardware": "mt6895",
    "ro.kernel.qemu": "",
    "ro.build.tags": "release-keys",
    "ro.build.type": "user",
    "ro.debuggable": "0",
    "ro.secure": "1",
    "ro.product.cpu.abi": "x86_64",      # 改不动的那条，必须仍被报出来
    "ro.product.cpu.abilist": "x86_64,x86",
    "gsm.sim.state": "READY",
    "gsm.sim.operator.numeric": "46000",
}


# ---------------------------------------------------------------------------
# 1. 身份池自洽
# ---------------------------------------------------------------------------
def test_build_is_deterministic_and_coherent():
    a, b = fp.build(7, vm=0), fp.build(7, vm=0)
    assert a.ident_id == b.ident_id
    assert a.profile == b.profile
    assert a.android_id == b.android_id and len(a.android_id) == 16
    p = a.profile
    # 自洽：指纹里必须真的含 brand/device/release，不能拼缝
    assert p["brand"] in p["fingerprint"]
    assert p["device"] in p["fingerprint"]
    assert ":%s/" % p["release"] in p["fingerprint"]
    assert p["fingerprint"].endswith("release-keys")


def test_build_differs_by_seed_and_vm():
    assert fp.build(1).profile != fp.build(2).profile
    a, b = fp.build(3, vm=0), fp.build(3, vm=1)
    assert a.android_id != b.android_id
    assert a.serial != b.serial


def test_identity_props_cover_required_keys():
    ident = fp.build(5, vm=0)
    props = ident.props()
    for k in fp.PROP_KEYS:
        assert k in props, k
        assert isinstance(props[k], str)
    # root / 可调试 这几条必须被写成「干净值」
    assert props["ro.debuggable"] == "0"
    assert props["ro.secure"] == "1"
    assert props["ro.build.tags"] == "release-keys"
    # ABI 不许撒谎（写 arm64 会让加固 so 崩）
    assert "ro.product.cpu.abi" not in props


def test_no_duplicate_keys_in_pool():
    for prof in fp.PHONE_POOL:
        assert prof["brand"] and prof["model"] and prof["fingerprint"]


# ---------------------------------------------------------------------------
# 2. 持久化
# ---------------------------------------------------------------------------
def test_store_roundtrip_and_bad_file(tmp_path):
    store = fp.IdentityStore(str(tmp_path / "device_identity.json"))
    assert store.get(0).ident_id == ""
    ident = fp.build(9, vm=0)
    assert store.put(ident) is True
    got = store.get(0)
    assert got.ident_id == ident.ident_id
    assert got.profile["model"] == ident.profile["model"]
    # 坏文件不抛异常、按「没有身份」处理
    (tmp_path / "device_identity.json").write_text("{not json", encoding="utf-8")
    assert store.get(0).ident_id == ""
    assert store.load() == {}


def test_default_store_path_follows_profile(tmp_path):
    store = fp.default_store(str(tmp_path), "device")
    assert store.path == os.path.join(str(tmp_path), "device",
                                      fp.IDENTITY_FILE)


# ---------------------------------------------------------------------------
# 3. ensure：只在模拟器上动手 + 按 boot 只应用一次
# ---------------------------------------------------------------------------
def test_ensure_skips_real_device(tmp_path, monkeypatch):
    # 关掉官方来源：这条钉的是「非模拟器 + 只有机型池 → 不许写 props、不许落盘」。
    # 开着 prefer_vendor 时 ensure 会去读真实 MuMu（本机有值），那是另一条
    # 路径，由 test_r920 覆盖。
    monkeypatch.setattr(fp, "_cfg", lambda raw: {"enabled": True,
                                                "prefer_vendor": False})
    dev = FakeDev(props=_REAL_PROPS)
    rep = fp.ensure(dev, {"android": {"identity": {"enabled": True}}},
                    user_data_dir=str(tmp_path), profile="device", vm=0)
    assert rep["ok"] is True
    assert rep["skipped"] == "not an emulator"
    # 一个 props 都不许写
    assert not [c for c in dev.calls if "setprop" in c]
    # 也**不许**在真机/假设备上落身份文件：否则跑一次单测就把机型定了
    assert not os.path.isfile(str(tmp_path / "device" / fp.IDENTITY_FILE))


def test_ensure_offline_device_does_not_persist_identity(tmp_path):
    dev = FakeDev(props={})
    rep = fp.ensure(dev, {"android": {"identity": {"enabled": True}}},
                    user_data_dir=str(tmp_path), profile="device", vm=0)
    assert rep["ok"] is False
    assert not os.path.isfile(str(tmp_path / "device" / fp.IDENTITY_FILE))


def test_ensure_applies_then_skips_this_boot(tmp_path):
    dev = FakeDev(props=_EMU_PROPS)
    cfg = {"android": {"identity": {"enabled": True, "reboot": "none"}},
           "user_data_dir": str(tmp_path)}
    rep = fp.ensure(dev, cfg, user_data_dir=str(tmp_path),
                    profile="device", vm=0)
    assert rep["ok"] is True
    assert rep["apply"]["applied"], rep
    assert rep["audit"]["identity_id"]
    # android_id 真的写进去了
    assert rep["apply"]["android_id"] == fp.IdentityStore(
        str(tmp_path / "device" / fp.IDENTITY_FILE)).get(0).android_id
    n = len(dev.calls)
    rep2 = fp.ensure(dev, cfg, user_data_dir=str(tmp_path),
                     profile="device", vm=0)
    assert rep2["skipped"] == "applied this boot"
    # 快路径：boot_id + 标记，两条 adb（不许再多）
    assert len(dev.calls) - n == 2, dev.calls[n:]


def test_ensure_reapplies_after_reboot(tmp_path):
    """重启后 props 回厂（内存态），标记还在磁盘上——必须重写身份。

    这是「刚登录又被踢」的典型形态：只比 identity_id 会把过期标记当证据。
    """
    dev = FakeDev(props=_EMU_PROPS)
    cfg = {"android": {"identity": {"enabled": True, "reboot": "none"}}}
    fp.ensure(dev, cfg, user_data_dir=str(tmp_path), profile="device", vm=0)
    assert dev._marker.endswith("boot-abc")
    # 模拟重启：boot_id 变了，props 回到出厂（内存态丢失）
    dev._route_orig = dev._route
    dev._route = lambda cmd: ("boot-xyz" if "boot_id" in cmd
                              else dev._route_orig(cmd))
    rep = fp.ensure(dev, cfg, user_data_dir=str(tmp_path),
                    profile="device", vm=0)
    assert rep.get("skipped") != "applied this boot"
    assert rep["apply"]["applied"], rep


def test_ensure_disabled_is_noop(tmp_path):
    dev = FakeDev(props=_EMU_PROPS)
    rep = fp.ensure(dev, {"android": {"identity": {"enabled": False}}},
                    user_data_dir=str(tmp_path), profile="device", vm=0)
    assert rep["ok"] is True and rep["skipped"] == "identity disabled"
    assert dev.calls == []


def test_ensure_is_fail_soft_on_offline_device(tmp_path):
    dev = FakeDev(props={})
    rep = fp.ensure(dev, {"android": {"identity": {"enabled": True}}},
                    user_data_dir=str(tmp_path), profile="device", vm=0)
    assert rep["ok"] is False and rep["error"] == "device offline"


# ---------------------------------------------------------------------------
# 4. audit：如实报残留
# ---------------------------------------------------------------------------
def test_audit_flags_emulator_and_root_evidence():
    got = fp.audit(FakeDev(props=_EMU_PROPS))
    keys = {x["key"] for x in got["leaks"]}
    assert "ro.kernel.qemu" in keys
    assert "ro.build.tags" in keys
    assert "ro.debuggable" in keys
    assert got["score"] < 60


def test_audit_keeps_abi_as_known_residue():
    got = fp.audit(FakeDev(props=_REAL_PROPS))
    keys = {x["key"] for x in got["leaks"]}
    # ABI 是「要先验证才能改」的一类：干净的机型 props 也要把 x86 报出来
    assert "ro.product.cpu.abi" in keys
    assert got["score"] > 60
    # 说明文字必须指向验证装置，而不是一句「改不动」
    assert "abi_canary" in fp.ABI_NOTE
    assert "abi_canary" in got["abi_note"]


# ---------------------------------------------------------------------------
# 5. stealth：无 root 时不假装成功；有 boot 标记时早退
# ---------------------------------------------------------------------------
def test_stealth_hide_without_root_reports_failure():
    dev = FakeDev(props=_EMU_PROPS, root=False)
    rep = st.hide(dev, packages=["ctrip"])
    assert rep["root"] is False
    assert rep["actions"] and rep["actions"][0]["ok"] is False


def test_stealth_prepare_marker_short_circuit(tmp_path):
    dev = FakeDev(props=_EMU_PROPS)
    dev._stealth_mark = "boot-abc"
    rep = st.prepare(dev, {"android": {"stealth": {"enabled": True}}}, vm=0)
    assert rep["skipped"] == "done this boot"
    assert len(dev.calls) <= 2      # 只读了 boot_id 与标记


def test_stealth_detect_lists_unfixable():
    got = st.detect(FakeDev(props=_EMU_PROPS))
    ids = {x["key"] for x in got["unfixable"]}
    assert {"play_integrity", "abi", "sensors", "kernel"} <= ids
    assert got["root"] and got["emulator"]


def test_clear_app_identity_is_dry_run_by_default():
    dev = FakeDev(props=_EMU_PROPS)
    rep = st.clear_app_identity(dev, packages=["ctrip"])
    assert rep["dry_run"] is True
    assert rep["packages"]["ctrip.android.view"]["removed"] == 0
    # 演练模式不许删任何东西
    assert not [c for c in dev.calls if c.startswith("shell rm")]


# ---------------------------------------------------------------------------
# 6. 工具函数
# ---------------------------------------------------------------------------
def test_parse_getprop():
    raw = "[ro.a]: [1]\n[ro.b]: [with space]\nnoise\n[ro.c]: []"
    got = fp.parse_getprop(raw)
    assert got == {"ro.a": "1", "ro.b": "with space", "ro.c": ""}


def test_is_emulator_by_evidence_only():
    assert fp._is_emulator({"ro.product.model": "MuMu"}) is True
    assert fp._is_emulator({"ro.kernel.qemu": "1"}) is True
    assert fp._is_emulator({"ro.product.model": "Redmi K50",
                            "ro.kernel.qemu": ""}) is False
    assert fp._is_emulator({}) is False
