# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1071_device_packages_doc.py
- tests/test_r910_device_identity_stealth.py
- tests/test_r925_device_lock_owner.py
- tests/test_r950_adb_endpoint_recovery.py
- tests/test_r962_adb_root_marker.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import importlib.util
import io
import logging
import os
import pytest
import re
import subprocess
import sys
import threading
import time

from core.android import fingerprint as fp, runtime as rt, stealth as st
from core.android.device import AdbDevice


# ---- merged from tests/test_r1071_device_packages_doc.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DOC = os.path.join(ROOT, "docs", "DEVICE_PACKAGES.md")
PKG_README = os.path.join(ROOT, "packages", "README.md")


def _mod(name, filename):
    p = os.path.join(ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _doc():
    return open(DOC, encoding="utf-8").read()


def test_packages_table_matches_code():
    """每个模块的地址/大小/SHA256 都必须原样出现在文档里。"""
    m = _mod("fetch_packages", "fetch_packages.py")
    doc = _doc()
    for name, meta in m.PACKAGES.items():
        assert meta["url"] in doc, "%s 的下载地址不在文档里" % name
        assert meta["sha256"] in doc, "%s 的 SHA256 不在文档里" % name
        assert str(meta["size"]) in doc, "%s 的大小不在文档里" % name
        assert name in doc, "%s 文件名不在文档里" % name


def test_mumu_url_matches_code():
    """MuMu 官网地址与 bootstrap 里的提示常量同源。"""
    from core.android import bootstrap as bs
    assert bs.MUMU_DOWNLOAD_HINT in _doc()


def test_ndk_url_present_and_plausible():
    doc = _doc()
    assert "android-ndk-r27c-windows.zip" in doc
    assert "dl.google.com" in doc


def test_app_package_names_match_setup_device():
    """文档里列的包名必须与 setup_device.APPS 一致（不多不少）。"""
    m = _mod("setup_device", "setup_device.py")
    doc = _doc()
    for pkg in m.APPS:
        assert pkg in doc, "文档缺少包名 %s" % pkg
    # 反向：文档里出现的 ctrip/android 形态包名也应被覆盖（防漏更新）
    found = set(re.findall(r"`([a-z]+\.[a-z0-9_.]+)`", doc))
    app_like = {f for f in found if f.startswith(
        ("ctrip.", "com.taobao", "com.Qunar", "com.tongcheng", "cn.suanya"))}
    assert app_like <= set(m.APPS), app_like - set(m.APPS)


def test_doc_declares_not_redistributing_apks():
    """必须明确写"仓库不分发 APK"——否则用户会以为能直接拿到。"""
    doc = _doc()
    assert "不分发" in doc


def test_packages_readme_points_to_doc():
    txt = open(PKG_README, encoding="utf-8").read()
    assert "docs/DEVICE_PACKAGES.md" in txt, "packages/README.md 应指向地址清单"


def test_dir_convention_documented():
    """目录约定（packages/、packages/apks/、build/）要写在文档里。"""
    doc = _doc()
    for p in ("packages/", "packages/apks/", "build/"):
        assert p in doc, p


# ---- merged from tests/test_r910_device_identity_stealth.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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
    # 假设备的 `setprop ro.*` 是 no-op，`applied`（命令层报成功）会为空；
    # 真正生效的是走 `settings put` 的 `android_id`（2026-11-04 改语义）。
    assert rep["ok"] is True, rep.get("why")
    assert rep["apply"].get("android_id"), rep["apply"]
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
    # 假设备 ro.* 写不动，真正生效的是 android_id（settings put）
    assert rep["apply"].get("android_id"), rep["apply"]


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


def test_stealth_prepare_marker_short_circuit():
    """本 boot 已全量隐藏过 → 早退，**但廉价重清仍要跑**。

    契约变化（2026-11-04）：以前这里是"两条 adb 就 return"。
    但实测 `nemuinit` 会在几分钟内把 `nemud.*` 写回来
    （19:19 归零 → 19:26 又 57 行），所以早退分支现在仍要跑一次
    `refresh()`（1 条 getprop，必要时一条批量删除）。

    **仍然不许**跑的是贵的动作：denylist 读写 sqlite、抓 logcat 快照、
    magiskpolicy 复核。那才是这个标记存在的意义。
    """
    dev = FakeDev(props=_EMU_PROPS)
    dev._stealth_mark = "boot-abc"
    rep = st.prepare(dev, {"android": {"stealth": {"enabled": True}}}, vm=0)
    assert rep["skipped"] == "done this boot"
    # 廉价重清确实跑了
    assert "refresh" in rep, "早退时没重清：nemuinit 写回后无人负责"
    # 贵的动作一个都不许有
    joined = "\n".join(dev.calls)
    assert "logcat" not in joined, "早退还去抓 logcat 快照（每轮白烧）"
    assert "denylist" not in joined, "早退还在读写 denylist sqlite"
    assert "dumpsys" not in joined, "早退不该做全量复核"


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


# ---- merged from tests/test_r925_device_lock_owner.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r925")


@pytest.fixture(autouse=True)
def _isolated_lock(monkeypatch):
    """换成本文件专用锁：同进程若有别的采集线程持着模块锁，默认
    ``timeout=600`` 会把用例真的拖满 10 分钟（不是产品坏，是抢真锁）。"""
    monkeypatch.setattr(rt, "_DEVICE_LOCK", threading.Lock())
    monkeypatch.setattr(rt, "_LOCK_STATE", {"owner": "", "since": 0.0})
    yield


def _runtime():
    return rt.AndroidRuntime({"enabled": True}, _LOG)


# ---------------------------------------------------------------------------
# 1. 持有者记录
# ---------------------------------------------------------------------------
def test_owner_is_recorded_while_held():
    r = _runtime()
    assert r.lock_state()["owner"] == ""
    with r.device_lock(owner="app_qunar"):
        st = r.lock_state()
        assert st["owner"] == "app_qunar"
        assert st["since"] > 0
    assert r.lock_state()["owner"] == ""


def test_owner_cleared_after_release():
    r = _runtime()
    with r.device_lock(owner="app_ctrip"):
        pass
    st = r.lock_state()
    # lock_state 还会带 budget_left/deadline_hits 等观测字段，这里只钉
    # 「持有者与起始时刻已清空」这一条契约，别把附加上下文当成契约本身。
    assert st["owner"] == "" and st["since"] == 0.0, st


def test_owner_cleared_even_on_exception():
    r = _runtime()
    try:
        with r.device_lock(owner="app_fliggy"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert r.lock_state()["owner"] == ""           # 异常也不能留下持有者


# ---------------------------------------------------------------------------
# 2. 等不到锁时，报出**当前持有者**
# ---------------------------------------------------------------------------
def test_timeout_reports_holder(caplog):
    r = _runtime()
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with r.device_lock(owner="app_qunar"):
            started.set()
            release.wait(5)

    th = threading.Thread(target=_hold, daemon=True)
    th.start()
    started.wait(2)
    try:
        with caplog.at_level(logging.WARNING):
            try:
                with r.device_lock(timeout=0.3, owner="app_ctrip"):
                    pass
                raise AssertionError("应当超时")
            except TimeoutError:
                pass
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "app_qunar" in text, text        # 关键：报出是谁占着
        assert "超时" in text
    finally:
        release.set()
        th.join(3)


def test_timeout_still_raises_timeout_error():
    """既有契约不变：拿不到锁抛 TimeoutError（调用方转 busy）。"""
    r = _runtime()
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with r.device_lock(owner="app_tongcheng"):
            started.set()
            release.wait(5)

    th = threading.Thread(target=_hold, daemon=True)
    th.start()
    started.wait(2)
    try:
        try:
            with r.device_lock(timeout=0.2):
                pass
            raise AssertionError("应当抛 TimeoutError")
        except TimeoutError as e:
            assert "busy" in str(e)
    finally:
        release.set()
        th.join(3)


# ---------------------------------------------------------------------------
# 3. 长持有要留痕（正常 App 采集通常 60s 内）
# ---------------------------------------------------------------------------
def test_long_hold_is_logged(caplog, monkeypatch):
    r = _runtime()
    # 把"偏长"阈值降到 0.2s，避免测试真的等 120s
    real = rt.time
    with caplog.at_level(logging.WARNING):
        with r.device_lock(owner="app_zhixing"):
            # 直接把 since 往前拨，模拟"已经持了很久"
            rt._LOCK_STATE["since"] = time.time() - 300
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "app_zhixing" in text and "偏长" in text, text


# ---------------------------------------------------------------------------
# 4. 渠道侧确实传了 owner（源码钉：9 处调用都要带）
# ---------------------------------------------------------------------------
def test_all_channels_pass_owner():
    import glob
    import io
    files = sorted(glob.glob(os.path.join(ROOT, "crawlers", "app_*.py")))
    bad = []
    for f in files:
        src = io.open(f, encoding="utf-8").read()
        if "rt.device_lock(" not in src:
            continue
        if "rt.device_lock()" in src:
            bad.append(os.path.basename(f))
        if "rt.device_lock(owner=self.name)" not in src:
            bad.append(os.path.basename(f) + "(缺 owner)")
    assert not bad, bad


# ---- merged from tests/test_r950_adb_endpoint_recovery.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ADB = r"D:\fake\adb.exe"
SERIAL = "127.0.0.1:16384"


class R:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def _dev():
    # settle_s 压到 0：测试不真的睡
    return AdbDevice(ADB, SERIAL, timeout=5)


# ---------------------------------------------------------------------------
# 1. state()：必须能区分端点状态（这是"先分辨再处置"的前提）
# ---------------------------------------------------------------------------
def test_state_reads_serial_state(monkeypatch):
    def fake(cmd, **k):
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\toffline\n"
                     + b"emulator-5554\tdevice\n")
        return R()
    monkeypatch.setattr(subprocess, "run", fake)
    assert _dev().state() == "offline"


def test_state_absent_when_not_listed(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **k: R(out=b"List of devices attached\n"))
    assert _dev().state() == "absent"


# ---------------------------------------------------------------------------
# 2. reconnect 逐级升级：第 1 级就好就不要动 server
# ---------------------------------------------------------------------------
def test_reconnect_stops_at_first_success(monkeypatch):
    calls = []

    def fake(cmd, **k):
        calls.append(" ".join(str(x) for x in cmd))
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\tdevice\n")
        return R(out=b"connected")
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res == "device", res
    assert not any("kill-server" in c for c in calls), \
        "一开始就 device 态还去重启 server（会打断别的 adb 使用者）"


# ---------------------------------------------------------------------------
# 3. 核心：connect 修不好时必须升级到 kill-server + start-server
# ---------------------------------------------------------------------------
def test_reconnect_escalates_to_server_restart(monkeypatch):
    """复刻 2026-11-04 的真实故障：connect 说成功，状态仍 offline。"""
    calls = []
    state = {"now": "offline"}

    def fake(cmd, **k):
        c = " ".join(str(x) for x in cmd)
        calls.append(c)
        if "devices" in cmd:
            body = "List of devices attached\n%s\t%s\n" % (SERIAL, state["now"])
            return R(out=body.encode())
        if "kill-server" in c:
            state["now"] = "device"          # 重启 server 之后才好
            return R()
        return R(out=b"already connected")   # ← connect 骗人
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res.startswith("recovered"), res
    assert any("kill-server" in c for c in calls), "没升级到重启 server"
    assert any("start-server" in c for c in calls), "重启后没起 server"


def test_reconnect_reports_final_state_when_unrecoverable(monkeypatch):
    def fake(cmd, **k):
        if "devices" in cmd:
            return R(out=b"List of devices attached\n"
                     + SERIAL.encode() + b"\toffline\n")
        return R(out=b"unable to connect")
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    res = _dev().reconnect()
    assert res == "offline", res        # 如实返回，不许谎报恢复


# ---------------------------------------------------------------------------
# 4. runtime 必须用 reconnect，而不是裸 connect
# ---------------------------------------------------------------------------
def test_runtime_uses_reconnect():
    src = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
                  encoding="utf-8").read()
    assert "dev.reconnect(" in src, "runtime 没走逐级恢复"
    # 不许残留"只 connect 一次就判离线"
    assert "dev.connect()\n            if not dev.online()" not in src, \
        "还在只 connect 一次就判定设备离线"


def test_device_has_recovery_primitives():
    for m in ("state", "disconnect", "restart_server", "reconnect"):
        assert hasattr(AdbDevice, m), m


def test_error_message_names_the_endpoint_distinction():
    """`last_error` 要说清"试过哪些手段 + 当前端点状态"，
    否则下一次还是会被误诊成设备故障。"""
    src = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
                  encoding="utf-8").read()
    assert "端点状态" in src, "错误信息里没区分端点/设备"


# ---- merged from tests/test_r962_adb_root_marker.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Dev:
    """只回放 getprop / 记录 resetprop 脚本。"""

    def __init__(self, props):
        self.props = dict(props)
        self.calls = []
        self.scripts = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd.startswith("shell ls -d"):
            p = cmd.split()[-1]
            return p if p in self.exists else ""
        return ""

    exists = ()

    def push(self, local, remote):
        return True


def _capture_resetprop(monkey, calls):
    """把清 props 的实际动作截下来，看看到底清了什么。"""
    monkey.setattr(fp, "_magisk",
                   lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_as_root(dev, script, timeout=None):
        calls.append(str(script))
        return ""

    monkey.setattr(fp, "as_root", fake_as_root)
    # refresh 内部是 `from .fingerprint import as_root`，函数级 import
    # 每次调用都重新绑定，所以 patch 源模块即可生效。
    return calls


VENDOR_ONLY = {"ro.product.model": "vivo", "ro.nemu": "1"}


def test_runtime_marker_is_included_in_refresh_targets(monkeypatch):
    """`service.adb.root` 必须被清 —— 它是 inclusion，不是 skip。

    `_is_vendor_prop` 对它判 False（不在厂商命名空间），所以没有
    `_RUNTIME_ROOT_PROPS` 它就永远进不了清理目标：
    检测报了个自己不管的洞，实例每次重启都会把它置回 1。
    """
    calls = _capture_resetprop(monkeypatch, [])
    d = _Dev({"ro.debuggable": "0", "service.adb.root": "1"})
    st.refresh(d)
    joined = "\n".join(calls)
    assert "service.adb.root" in joined, \
        "没清 service.adb.root：它被当成 skip 列表了（分数会永久卡住）"


def test_clearing_it_does_not_require_dropping_root(monkeypatch):
    """文档化实测结论：清这条标记和保留 root 通道**不冲突**。

    这条测试不重复做设备实验（CI 上没有设备），它钉的是代码里的
    **表述不许倒退**：一旦有人把它当"取舍"写回去（例如加一句
    "清掉会丢 root 所以别动"），后面的人会因此不敢清、
    把一条本来免费就能消的暴露面长期留着。
    """
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find("_RUNTIME_ROOT_PROPS")
    ctx = src[max(0, i - 1400):i]
    assert "uid=0" in ctx, "注释里必须保留'清它不会掉 root'的实测证据"
    assert "76" in ctx and "84" in ctx, "分数对照是这条结论的来源，不能丢"


def test_vendor_props_still_cleared_together(monkeypatch):
    """同一次重清要一起覆盖厂商键，不能因为特殊列表漏掉常规项。"""
    calls = _capture_resetprop(monkeypatch, [])
    d = _Dev({"ro.nemu": "1", "service.adb.root": "1"})
    st.refresh(d)
    joined = "\n".join(calls)
    assert "ro.nemu" in joined and "service.adb.root" in joined, joined[:400]


def test_no_targets_means_no_magisk_probe(monkeypatch):
    """已干净时不许探 magisk（refresh 每轮都跑，探针一次 4~5 条 adb）。"""
    probed = []
    monkeypatch.setattr(fp, "_magisk",
                        lambda dev: probed.append(1) or "/x/magisk resetprop")
    d = _Dev({"ro.debuggable": "0", "ro.product.model": "vivo"})
    st.refresh(d)
    assert not probed, "没东西要清还去探测 magisk，白烧 adb 往返"


def test_marker_is_counted_by_detect():
    """detect 必须继续把它算作 root 证据（否则清了也没人知道有没有效）。"""

    class _D(_Dev):
        exists = ("/system/bin/sh",)

    a = _D({"ro.product.model": "vivo", "service.adb.root": "1"})
    b = _D({"ro.product.model": "vivo", "service.adb.root": "0"})
    ra, rb = st.detect(a), st.detect(b)
    assert any("service.adb.root" in x for x in ra["root"]), ra["root"]
    assert not any("service.adb.root" in x for x in rb["root"]), rb["root"]
    assert rb["score"] > ra["score"], (ra["score"], rb["score"])
