# -*- coding: utf-8 -*-
"""首次引导：状态分级正确，未启用时零外部访问。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.android.bootstrap as bs


def test_disabled_returns_immediately(monkeypatch):
    """未启用时不能探测磁盘、不能跑子进程。"""
    def boom(*a, **k):
        raise AssertionError("must not touch filesystem/external")

    monkeypatch.setattr(bs, "resolve_install_dir", boom, raising=False)
    monkeypatch.setattr(bs, "resolve_install_dir", boom)
    st = bs.status({"android": {"enabled": False}})
    assert st["state"] == "disabled"
    assert st["steps"] == []


def test_missing_config_is_disabled():
    assert bs.status({})["state"] == "disabled"
    assert bs.status(None)["state"] == "disabled"


def test_not_installed_gives_actionable_next(monkeypatch):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: "")
    st = bs.status({"android": {"enabled": True}})
    assert st["state"] == "not_installed"
    assert "mumu.163.com" in st["next"]
    # 引导必须给出可执行的一步
    assert "下载" in st["next"] and "重新检测" in st["next"]


def test_stopped_reports_instance_not_started(monkeypatch):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _FakeMgr(started=False))
    st = bs.status({"android": {"enabled": True}})
    assert st["state"] == "stopped"
    done = [s["key"] for s in st["steps"] if s["done"]]
    assert done == ["check", "install"]


def test_ready_reports_adb(monkeypatch):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _FakeMgr(started=True))
    st = bs.status({"android": {"enabled": True}})
    assert st["state"] == "ready"
    assert "16384" in st["detail"]


def test_incomplete_install_is_error(monkeypatch):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _FakeMgr(started=True, avail=False))
    assert bs.status({"android": {"enabled": True}})["state"] == "error"


def test_ensure_skips_when_no_app_channel():
    """没勾 App 渠道时，启动完全不检查安卓运行时。"""
    assert bs.ensure_android_runtime(["qunar", "ctrip"], {}) == ""
    assert bs.ensure_android_runtime([], {}) == ""


def test_ensure_warns_when_checked_but_disabled():
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": False}})
    assert "Android 真机通道" in msg and "未启用" in msg


def test_ensure_reports_ready(monkeypatch):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _FakeMgr(started=True))
    msg = bs.ensure_android_runtime(
        ["app_zhixing"], {"android": {"enabled": True}})
    assert "就绪" in msg


class _FakeMgr:
    def __init__(self, started=True, avail=True):
        self.started, self.avail = started, avail

    def __call__(self, *a, **k):
        return self

    def available(self):
        return self.avail

    def info(self, vm=None):
        return {"is_android_started": self.started, "adb_port": 16384,
                "adb_host_ip": "127.0.0.1"}


# ---- r650：引导清单的后两步必须真的检查，不能永远不勾 ----
def test_status_checks_apk_installed(monkeypatch):
    """模拟器起来 ≠ 能采。App 装好了就该点亮「安装智行 App」。

    实测：App 早装好且在采数，--app-status 却一直显示未完成——
    用户照引导走完发现清单没变，会以为没装成功。
    """
    from core.android import bootstrap as bs

    class Mgr:
        def available(self):
            return True

        def info(self):
            return {"is_android_started": True, "adb_port": 16384,
                    "adb_host_ip": "127.0.0.1"}

        adb_path = "adb"

        def adb_serial(self):
            return "127.0.0.1:16384"

    class Dev:
        def __init__(self, *a, **k):
            pass

        def app_installed(self, pkg):
            return True

    monkeypatch.setattr(bs, "resolve_install_dir", lambda ac: "C:/MuMu")
    monkeypatch.setattr(bs, "MuMuManager", lambda **k: Mgr())
    import core.android.device as devmod
    monkeypatch.setattr(devmod, "AdbDevice", Dev)
    st = bs.status({"android": {"enabled": True}}, evidence=lambda: True)
    done = {s["key"]: s["done"] for s in st["steps"]}
    assert done["apk"] is True, "App 已安装却没点亮：%s" % done
    assert done["verify"] is True, "有采集证据却没点亮：%s" % done


def test_status_keeps_verify_unchecked_without_evidence(monkeypatch):
    """没有「真的采到过数」的证据时，验证步骤必须保持未勾选（不猜）。"""
    from core.android import bootstrap as bs

    class Mgr:
        def available(self):
            return True

        def info(self):
            return {"is_android_started": True, "adb_port": 16384}

        adb_path = "adb"

        def adb_serial(self):
            return "x"

    class Dev:
        def __init__(self, *a, **k):
            pass

        def app_installed(self, pkg):
            return True

    monkeypatch.setattr(bs, "resolve_install_dir", lambda ac: "C:/MuMu")
    monkeypatch.setattr(bs, "MuMuManager", lambda **k: Mgr())
    import core.android.device as devmod
    monkeypatch.setattr(devmod, "AdbDevice", Dev)
    st = bs.status({"android": {"enabled": True}}, evidence=lambda: False)
    done = {s["key"]: s["done"] for s in st["steps"]}
    assert done["apk"] is True
    assert done["verify"] is False, "没有采集证据却点亮了验证：%s" % done


def test_status_does_not_crash_without_packages(monkeypatch):
    """拿不到渠道包名/读不到设备时，只能保守判「未安装」，不能抛。"""
    from core.android import bootstrap as bs

    class Mgr:
        def available(self):
            return True

        def info(self):
            return {"is_android_started": True, "adb_port": 16384}

        adb_path = "adb"

        def adb_serial(self):
            return "x"

    class Dev:
        def __init__(self, *a, **k):
            pass

        def app_installed(self, pkg):
            raise RuntimeError("adb 断了")

    monkeypatch.setattr(bs, "resolve_install_dir", lambda ac: "C:/MuMu")
    monkeypatch.setattr(bs, "MuMuManager", lambda **k: Mgr())
    import core.android.device as devmod
    monkeypatch.setattr(devmod, "AdbDevice", Dev)
    st = bs.status({"android": {"enabled": True}})
    assert st["state"] == "ready"
    assert "未检测到智行 App" in (st.get("next") or "")
