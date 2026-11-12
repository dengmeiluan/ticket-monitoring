# -*- coding: utf-8 -*-
"""r1063 T71/T72：登录入口全渠道统一 + macOS 开窗兜底 + 设备身份轮换。

三件事对应三条实测反馈：
1. 「上渠道地址跳转 / 弹窗登录」不对 —— 登录入口必须指向**能登录的那一页**，
   而不是"查看详情"深链（途牛 PC 曾弹成 `m.tuniu.com`）；
2. GitHub #14：macOS 发行包点「渠道登录」报 no_gui，而同一台机 `--login` 能弹
   —— 进程内开不成时**退回命令行那条路**；
3. 设备被标记 —— 提供"身份轮换"（从便宜到贵：换身份 → 清 App 本地 ID → 重启）。
"""
import io
import os

import pytest

from core.channel_links import login_entry_url
from core.login_slots import LOGIN_SLOTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_channel_has_a_login_entry():
    """五家浏览器渠道都必须给得出登录入口（否则弹窗只能退到"查看详情"深链）。"""
    for plat in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        got = login_entry_url(plat, "pc")
        assert got.startswith("https://"), (plat, got)


def test_pc_entry_is_never_a_mobile_host():
    """PC 登录不能弹移动域（用户实测途牛被弹成 m.tuniu.com）。"""
    for plat in ("ctrip", "qunar", "tongcheng", "tuniu"):
        got = login_entry_url(plat, "pc")
        assert "://m." not in got, (plat, got)
        assert "://touch." not in got, (plat, got)


def test_tuniu_and_fliggy_split_by_surface():
    assert login_entry_url("tuniu", "pc") == "https://flight.tuniu.com/"
    assert login_entry_url("tuniu", "h5").startswith("https://m.tuniu.com/")
    assert "m.taobao.com" in login_entry_url("fliggy", "h5")
    assert "m.taobao.com" not in login_entry_url("fliggy", "pc")


def test_login_entry_matches_the_login_slots():
    """入口与登录槽位同源：槽位登记的 URL 必须能被入口取到（不许两套口径）。"""
    for key, meta in LOGIN_SLOTS.items():
        plat = meta.get("plat")
        got = login_entry_url(plat, meta.get("surface") or "pc")
        assert got, key
        if not meta.get("surface"):
            assert got == meta["login_url"], (key, got)


def test_no_graphical_env_is_honest_per_platform(monkeypatch):
    import sys

    import webui

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("TM_FORCE_GUI", raising=False)
    # conftest 的 autouse 桩默认按「有图形环境」跑；本用例验真实平台判据。
    monkeypatch.setattr(webui, "_no_graphical_env",
                        webui._real_no_graphical_env)
    if sys.platform.startswith("linux"):
        assert webui._no_graphical_env() is True
    else:
        # macOS/Windows：没有 DISPLAY 也是**有**图形环境（#14 的根因）
        assert webui._no_graphical_env() is False
    monkeypatch.setenv("TM_FORCE_GUI", "1")
    assert webui._no_graphical_env() is False


def test_cli_login_fallback_spawns_the_documented_command(monkeypatch):
    """进程内开不出窗口时，必须退回 `--login <plat>`（终端里那条命令）。"""
    import webui

    seen = {}

    class _P:
        def __init__(self, *a, **kw):
            seen["cmd"] = a[0] if a else (kw.get("args") or [])

    monkeypatch.setattr("subprocess.Popen", _P)
    ok, detail = webui._spawn_cli_login("ctrip")
    assert ok is True, detail
    cmd = " ".join(str(x) for x in seen["cmd"])
    assert "--login" in cmd and "ctrip" in cmd, cmd


def test_cli_login_fallback_reports_failure(monkeypatch):
    import webui

    def _boom(*a, **kw):
        raise OSError("nope")

    monkeypatch.setattr("subprocess.Popen", _boom)
    ok, detail = webui._spawn_cli_login("ctrip")
    assert ok is False and "nope" in detail


def test_rotate_plan_is_honest_and_apply_is_opt_in():
    from core.android import rotate

    plan = rotate.plan("user_data")
    assert "identity_file" in plan and plan["steps"]
    assert any("登录态" in x for x in plan["keeps"]), plan
    rep = rotate.rotate("user_data", ["app_ctrip"], apply=False)
    assert rep["ok"] and rep["applied"] is False


def test_rotate_backs_up_and_drops_identity(monkeypatch, tmp_path):
    from core.android import rotate

    ident = tmp_path / "device" / "device_identity.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text('{"brand": "X"}', encoding="utf-8")

    class _Store:
        path = str(ident)

        def drop(self, vm=0):
            # 真实签名 `drop(vm: int)`：身份按实例索引分槽存
            os.remove(self.path)
            return True

    monkeypatch.setattr(rotate, "_store", lambda *a, **k: _Store())
    monkeypatch.setattr(rotate, "_pkg_of", lambda p: "")
    monkeypatch.setattr(rotate, "_append_log", lambda *a, **k: None)
    rep = rotate.rotate(str(tmp_path), [], apply=True)
    assert rep["ok"] and rep["applied"] is True
    assert rep["identity_backup"] and os.path.exists(rep["identity_backup"]), rep
    assert not ident.exists(), "身份文件应当被 drop（下次采集重建）"


def test_rotate_can_restore_the_backup(monkeypatch, tmp_path):
    from core.android import rotate

    ident = tmp_path / "device" / "device_identity.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text('{"brand": "X"}', encoding="utf-8")

    class _Store:
        path = str(ident)

        def drop(self, vm=0):
            # 真实签名 `drop(vm: int)`：身份按实例索引分槽存
            os.remove(self.path)
            return True

    monkeypatch.setattr(rotate, "_store", lambda *a, **k: _Store())
    monkeypatch.setattr(rotate, "_pkg_of", lambda p: "")
    monkeypatch.setattr(rotate, "_append_log", lambda *a, **k: None)
    rotate.rotate(str(tmp_path), [], apply=True)
    got = rotate.restore(str(tmp_path))
    assert got["ok"], got
    assert ident.exists() and "X" in ident.read_text(encoding="utf-8")
