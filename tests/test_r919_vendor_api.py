# -*- coding: utf-8 -*-
"""r919：MuMu 官方接口（机型/屏幕/系统盘只读）——比改 props 更该优先用。

2026-11-03 实测枚举到这些官方键（``MuMuManager.exe setting -v 0 --all``）：

    phone_brand Samsung / phone_model Galaxy A52 5G / phone_miit SM-A5260
    phone_imei 865247046277134
    resolution_width 1600 / resolution_height 900 / resolution_dpi 240
    root_permission true / system_disk_readonly true

钉住四件事：
  1. **白名单**：只允许写设备外观与系统盘可写，性能/网络类键必须被拒；
  2. **读回校验**：写成功要有读回证据（数值型按数值比，容 6 位小数）；
  3. **需要重启的键**要标 ``restart_required``，不替操作员擅自重启；
  4. 默认**只读**：``android.vendor`` 没配 ``apply: true`` 时一个键都不写。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r919_vendor_api.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import vendor  # noqa: E402
from core.android import hardening  # noqa: E402

_LOG = logging.getLogger("test_r919")


class FakeMgr:
    """假 MuMuManager：``setting`` 读写内存字典，可选拒绝某些键。"""

    def __init__(self, values=None, available=True, reject=()):
        self.values = dict(values or {})
        self._available = available
        self.reject = set(reject)
        self.writes = []

    def available(self):
        return self._available

    def _vm(self, vm):
        return 0

    def setting(self, key, value=None, vm=None):
        if value is None:
            return self.values.get(key)
        self.writes.append((key, value))
        if key in self.reject:
            return None
        self.values[key] = str(value)
        return "{}"

    def _call_json(self, args, timeout=None):
        return dict(self.values)


_BASE = {
    "phone_brand": "Samsung",
    "phone_model": "Galaxy A52 5G",
    "phone_miit": "SM-A5260",
    "resolution_width": "1600.000000",
    "resolution_height": "900.000000",
    "resolution_dpi": "240.000000",
    "system_disk_readonly": "true",
    "root_permission": "true",
    "performance_cpu": "4",
    "net_bridge.enabled": "false",
}


# ---------------------------------------------------------------------------
# 1. 读
# ---------------------------------------------------------------------------
def test_read_returns_all_settings():
    got = vendor.read(FakeMgr(_BASE))
    assert got["phone_miit"] == "SM-A5260"
    assert got["system_disk_readonly"] == "true"


def test_read_unavailable_is_empty():
    assert vendor.read(FakeMgr(_BASE, available=False)) == {}


def test_get_returns_value():
    assert vendor.get("phone_brand", FakeMgr(_BASE)) == "Samsung"


# ---------------------------------------------------------------------------
# 2. 写 + 白名单 + 读回校验
# ---------------------------------------------------------------------------
def test_apply_writes_whitelisted_keys_and_verifies():
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, phone_brand="Xiaomi", phone_miit="2201123C")
    assert rep["ok"] is True
    assert rep["applied"] == {"phone_brand": "Xiaomi", "phone_miit": "2201123C"}
    assert all(v["ok"] for v in rep["verify"].values())
    assert rep["restart_required"] is False


def test_apply_rejects_performance_and_network_keys():
    """性能/网络键改错会让采集变慢或断网——必须拒。"""
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, performance_cpu=16, **{"net_bridge.enabled": "true"})
    assert rep["applied"] == {}
    assert set(rep["rejected"]) == {"performance_cpu", "net_bridge.enabled"}
    assert mgr.writes == []           # 一个都没真写


def test_apply_numeric_readback_tolerates_decimals():
    """读回是 1600.000000，写的是 1600 —— 要按数值判等。"""
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, resolution_width=1080, resolution_height=1920)
    assert rep["verify"]["resolution_width"]["ok"] is True
    assert rep["verify"]["resolution_height"]["ok"] is True
    assert rep["ok"] is True


def test_apply_marks_restart_required_for_system_disk():
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, system_disk_readonly="false")
    assert rep["applied"]["system_disk_readonly"] == "false"
    assert rep["restart_required"] is True


def test_apply_reports_write_failure():
    mgr = FakeMgr(_BASE, reject={"phone_model"})
    rep = vendor.apply(mgr, phone_model="X99")
    assert rep["ok"] is False
    assert rep["verify"]["phone_model"]["ok"] is False


def test_apply_unavailable_manager():
    rep = vendor.apply(FakeMgr(_BASE, available=False), phone_brand="X")
    assert rep["ok"] is False and "不可用" in rep["error"]


# ---------------------------------------------------------------------------
# 3. 组合入口
# ---------------------------------------------------------------------------
def test_spoof_device_sets_three_coherent_keys():
    mgr = FakeMgr(_BASE)
    rep = vendor.spoof_device(mgr, brand="Redmi", model="Redmi K50",
                              miit="2201123C", imei="860000000000001")
    assert rep["ok"] is True
    assert mgr.values["phone_brand"] == "Redmi"
    assert mgr.values["phone_model"] == "Redmi K50"
    assert mgr.values["phone_miit"] == "2201123C"


def test_spoof_screen_sets_resolution_and_dpi():
    mgr = FakeMgr(_BASE)
    rep = vendor.spoof_screen(mgr, width=1080, height=1920, dpi=440)
    assert rep["ok"] is True
    assert float(mgr.values["resolution_width"]) == 1080.0
    assert float(mgr.values["resolution_dpi"]) == 440.0


def test_unlock_system_disk_never_restarts_by_default():
    mgr = FakeMgr(_BASE)
    rep = vendor.unlock_system_disk(mgr)
    assert rep["applied"]["system_disk_readonly"] == "false"
    assert rep["restarted"] is False      # 默认绝不替你重启


# ---------------------------------------------------------------------------
# 4. hardening 的 vendor 段：默认只读
# ---------------------------------------------------------------------------
def test_harden_vendor_step_is_read_only_by_default(monkeypatch):
    mgr = FakeMgr(_BASE)
    monkeypatch.setattr(hardening, "vendor_mod", vendor, raising=False)
    import core.android.config as cfgmod
    import core.android.mumu as mumumod
    monkeypatch.setattr(cfgmod, "resolve_install_dir", lambda c: "X")
    monkeypatch.setattr(cfgmod, "normalize", lambda raw: cfgmod.AndroidConfig())
    monkeypatch.setattr(mumumod, "MuMuManager",
                        lambda **kw: mgr)
    rep = hardening._vendor_step({"android": {}}, _LOG, vm=0)
    assert rep["available"] is True
    assert "只读" in rep.get("skipped", "")
    assert mgr.writes == []               # 一个键都没写
    assert rep["current"]["phone_miit"] == "SM-A5260"


def test_harden_vendor_step_writes_when_configured(monkeypatch):
    mgr = FakeMgr(_BASE)
    monkeypatch.setattr(hardening, "vendor_mod", vendor, raising=False)
    import core.android.config as cfgmod
    import core.android.mumu as mumumod
    monkeypatch.setattr(cfgmod, "resolve_install_dir", lambda c: "X")
    monkeypatch.setattr(cfgmod, "normalize", lambda raw: cfgmod.AndroidConfig())
    monkeypatch.setattr(mumumod, "MuMuManager", lambda **kw: mgr)
    cfg = {"android": {"vendor": {"apply": True, "brand": "Redmi",
                                  "model": "Redmi K50"}}}
    rep = hardening._vendor_step(cfg, _LOG, vm=0)
    assert rep["apply"]["ok"] is True
    assert mgr.values["phone_brand"] == "Redmi"
