# -*- coding: utf-8 -*-
"""r1107 / GitHub #14：macOS 原生包点「渠道登录」被误判无图形环境。

用户实报：macOS ARM64 发行版里，网页控制台点「渠道登录」提示
「这台服务没有图形界面」，但同一台 Mac 上 `./TicketMonitor --login ctrip`
能正常弹出 Chromium 登录窗。

根因：`_no_graphical_env()` 用 `os.name == "posix"` 判断，macOS 也是
posix，但窗口系统走 Quartz/Cocoa，没有 DISPLAY / WAYLAND_DISPLAY，
于是整台 Mac 被判成 Docker 式无头环境。无头判定只对 Linux 成立。

本测试直接驱动产品函数 `_no_graphical_env`（不是复制实现），并用
`_start_login` 的 no_gui 分支证明守卫真的接在登录入口上。
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# conftest 的 autouse `_pretend_graphical` 会把 `_no_graphical_env` 换成
# `lambda: False`（CI 是 Linux 无 DISPLAY，不换登录类用例全会被 no_gui 拦）。
# 在 collection 阶段（fixture 生效前）留一份真身，测试里显式装回去。
sys.path.insert(0, ROOT)
import webui  # noqa: E402

_REAL_NO_GUI = webui._no_graphical_env


def _w():
    return importlib.import_module("webui")


def _use_real_guard(w, monkeypatch):
    monkeypatch.setattr(w, "_no_graphical_env", _REAL_NO_GUI, raising=True)


def _clear_gui_env(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_macos_without_display_is_not_headless(monkeypatch):
    """#14 回归：darwin 没有 DISPLAY 仍然是图形环境。"""
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(w.sys, "platform", "darwin")
    assert w._no_graphical_env() is False, (
        "macOS 没有 DISPLAY 不算无头——旧 os.name=='posix' 判据会让"
        "原生包点渠道登录永远得到 no_gui")


def test_linux_without_display_is_headless(monkeypatch):
    """真无头（Docker/无 X 的 Linux）仍须拦住，并给出可执行原因。"""
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(w.sys, "platform", "linux")
    assert w._no_graphical_env() is True


def test_linux_with_display_is_not_headless(monkeypatch):
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(w.sys, "platform", "linux")
    assert w._no_graphical_env() is False


def test_linux_with_wayland_is_not_headless(monkeypatch):
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(w.sys, "platform", "linux")
    assert w._no_graphical_env() is False


def test_windows_is_not_headless(monkeypatch):
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    monkeypatch.setattr(w.sys, "platform", "win32")
    assert w._no_graphical_env() is False


def test_login_entry_returns_no_gui_only_on_headless_linux(monkeypatch):
    """产品入口实测：Linux 无头 → no_gui；macOS → 不在这里被拒。"""
    w = _w()
    _use_real_guard(w, monkeypatch)
    _clear_gui_env(monkeypatch)
    key = next(iter(w.LOGIN_SLOTS))
    monkeypatch.setattr(w._State, "login_pending", {})
    monkeypatch.setattr(w._State, "login_sessions", {})
    monkeypatch.setattr(w.sys, "platform", "linux")
    r = w._start_login(key)
    assert r["ok"] is False and r.get("kind") == "no_gui", r

    # macOS 分支：守卫必须放行。这里不触发真开窗（没有浏览器），
    # 只用判据函数证明同一入口不会再被 no_gui 拦住。
    monkeypatch.setattr(w.sys, "platform", "darwin")
    assert w._no_graphical_env() is False
