# -*- coding: utf-8 -*-
"""设备伪装探针的解析测试（纯函数，不需要真机）。

为什么重要：这个探针挂在 `--app-status` 和配置页引导上，是用户判断
"我的设备到底准备好了没"的唯一入口。判错两种都坏：
  * 假绿 —— 用户以为就位，采集一跑就失败；
  * 假红 —— 用户被推去重装一遍，浪费时间。
所以每条判据都要有正反例，且"读不到"必须单独成一种状态（ok=None），
不能悄悄当成通过。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _bs():
    # bootstrap 内部用相对导入，必须按包导入（与 test_android_bootstrap 同法）
    from core.android import bootstrap as bs
    return bs


GOOD = (
    "enforce=Enforcing\n"
    "cpu=processor\t: 0 BogoMIPS\t: 38.40 \n"
    "zpid=758\n"
    "zyg=3\n"
    "cloak=arm64-v8a.so\n"
    "cloak_off=\n"
)


def _by_name(res):
    return {c[0]: (c[1], c[2]) for c in res["checks"]}


def test_good_device_is_ok():
    m = _bs()
    res = m.parse_probe(GOOD)
    assert res["ok"] is True, res
    assert res["missing"] == []


def test_permissive_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("enforce=Enforcing", "enforce=Permissive"))
    assert res["ok"] is False
    assert any("SELinux" in x for x in res["missing"])


def test_intel_cpuinfo_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("BogoMIPS\t: 38.40", "vendor_id: GenuineIntel"))
    assert res["ok"] is False
    assert any("cpuinfo" in x for x in res["missing"])


def test_zygisk_not_injected_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("zyg=3", "zyg=0"))
    assert res["ok"] is False
    assert any("Zygisk" in x for x in res["missing"])


def test_cloak_disabled_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("cloak_off=\n",
                                     "cloak_off=/data/adb/modules/mumu_cloak/disable\n"))
    assert res["ok"] is False
    assert any("mumu_cloak" in x for x in res["missing"])


def test_cloak_missing_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("cloak=arm64-v8a.so\n", "cloak=\n"))
    assert res["ok"] is False
    assert any("mumu_cloak" in x for x in res["missing"])


def test_no_output_is_unknown_not_pass():
    """读不到 ≠ 通过。这是最容易写成假绿的地方。"""
    m = _bs()
    res = m.parse_probe("")
    assert res["ok"] is None
    assert res["checks"] == []


def test_garbage_output_is_unknown():
    m = _bs()
    res = m.parse_probe("error: device offline\n")
    assert res["ok"] is None


def test_missing_items_carry_actionable_next():
    """缺项时必须给出可执行命令，而不是只说"未就位"。"""
    m = _bs()
    res = m.parse_probe(GOOD.replace("enforce=Enforcing", "enforce=Permissive"))
    assert "setup_device.py" in res["next"]
    assert "apply" in res["next"]


def test_crlf_output_parses():
    """adb 输出常带 CRLF，不能被 \\r 干扰。"""
    m = _bs()
    res = m.parse_probe(GOOD.replace("\n", "\r\n"))
    assert res["ok"] is True


def test_probe_hardening_never_raises():
    """dev 抛异常时必须降级为 None，不能把状态查询打挂。"""
    m = _bs()

    class Boom:
        def run_script(self, *a, **k):
            raise RuntimeError("adb died")

    res = m.probe_hardening(Boom())
    assert res["ok"] is None


def test_status_includes_hardening_key(monkeypatch):
    """status() 必须带上 hardening 字段（UI/CLI 靠它显示伪装状态）。"""
    m = _bs()

    class _Mgr:
        def __init__(self, *a, **k):
            pass

        def available(self):
            return True

        def info(self):
            return {"is_android_started": True, "adb_port": 16384,
                    "adb_host_ip": "127.0.0.1"}

    monkeypatch.setattr(m, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(m, "MuMuManager", _Mgr)
    st = m.status({"android": {"enabled": True}})
    assert "hardening" in st
    assert st["state"] == "ready"
