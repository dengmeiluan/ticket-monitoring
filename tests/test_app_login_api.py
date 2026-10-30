# -*- coding: utf-8 -*-
"""App 登录 HTTP 层：鉴权边界、未知渠道、帧 304、坐标校验、完成后清理。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import login_api
from core.android.login_session import (ST_DONE, AppLoginRegistry,
                                        AppLoginSession)

PACKAGES = {"app_zhixing": "cn.suanya.zhixing"}


class FakeDevice:
    def __init__(self):
        self.taps = []
        self.texts = []

    def screencap(self):
        return b"\x89PNG-1"

    def window_size(self):
        return (900, 1600)

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def input_text(self, t):
        self.texts.append(t)
        return True

    def keyevent(self, k):
        return True

    def app_start(self, pkg):
        return True


class FakeRuntime:
    def __init__(self, ready=True):
        self.ready = ready
        self.d = FakeDevice()

    def ensure_ready(self):
        return (True, "ready") if self.ready else (False, "not_installed")

    def device(self):
        return self.d


def _ctx(rt=None, verify=None, snapshot=None):
    rt = rt or FakeRuntime()
    return {
        "packages": PACKAGES,
        "runtime_factory": lambda: rt,
        "verify": verify,
        "snapshot": snapshot,
    }, rt


def test_create_rejects_unknown_plat():
    reg = AppLoginRegistry()
    ctx, _ = _ctx()
    out, code = login_api.handle_create(reg, "nope", PACKAGES,
                                        ctx["runtime_factory"])
    assert code == 400 and out["ok"] is False


def test_create_reports_runtime_not_ready():
    reg = AppLoginRegistry()
    rt = FakeRuntime(ready=False)
    out, code = login_api.handle_create(
        reg, "app_zhixing", PACKAGES, lambda: rt)
    assert code == 409
    assert "未就绪" in out["err"]


def test_create_reports_disabled_when_no_runtime():
    reg = AppLoginRegistry()
    out, code = login_api.handle_create(
        reg, "app_zhixing", PACKAGES, lambda: None)
    assert code == 409
    assert "未启用" in out["err"]


def test_create_starts_app_and_registers():
    reg = AppLoginRegistry()
    ctx, rt = _ctx()
    out, code = login_api.handle_create(
        reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    assert code == 200 and out["ok"] is True
    assert log_ok(reg)


def log_ok(reg):
    s = reg.get("app_zhixing")
    return s is not None and s.package == "cn.suanya.zhixing"


def test_create_is_idempotent_for_live_session():
    reg = AppLoginRegistry()
    ctx, _ = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_create(
        reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    assert code == 200 and out.get("already") is True


def test_frame_returns_png_then_304():
    reg = AppLoginRegistry()
    ctx, _ = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    png, code, hdr = login_api.handle_frame(reg, "app_zhixing")
    assert code == 200 and png.startswith(b"\x89PNG")
    assert hdr["Content-Type"] == "image/png"
    _, code2, _ = login_api.handle_frame(reg, "app_zhixing")
    assert code2 == 304, "同一画面应返回 304，避免重复传全图"


def test_frame_404_without_session():
    reg = AppLoginRegistry()
    _, code, _ = login_api.handle_frame(reg, "app_zhixing")
    assert code == 404


def test_tap_validates_integers():
    reg = AppLoginRegistry()
    ctx, _ = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_tap(reg, "app_zhixing", {"x": "abc", "y": 1})
    assert code == 400 and out["ok"] is False


def test_tap_forwards_to_device():
    reg = AppLoginRegistry()
    ctx, rt = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_tap(reg, "app_zhixing", {"x": 10, "y": 20})
    assert code == 200 and rt.d.taps == [(10, 20)]


def test_tap_rejected_when_out_of_screen():
    reg = AppLoginRegistry()
    ctx, rt = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_tap(reg, "app_zhixing",
                                     {"x": 9999, "y": 20})
    assert code == 409 and rt.d.taps == []


def test_input_rejects_too_long_text():
    reg = AppLoginRegistry()
    ctx, rt = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_input(
        reg, "app_zhixing", {"text": "x" * (login_api.MAX_TEXT + 1)})
    assert code == 400
    assert rt.d.texts == []


def test_input_forwards_normal_text():
    reg = AppLoginRegistry()
    ctx, rt = _ctx()
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_input(
        reg, "app_zhixing", {"text": "13800138000"})
    assert code == 200 and rt.d.texts == ["13800138000"]


def test_finish_cleans_up_and_reports_detail():
    reg = AppLoginRegistry()
    ctx, _ = _ctx(verify=lambda: (True, "已登录"),
                  snapshot=lambda: (True, "快照已存"))
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_finish(reg, "app_zhixing",
                                       ctx["verify"], ctx["snapshot"])
    assert code == 200 and out["ok"] is True
    assert "已登录" in out["detail"] and "快照已存" in out["detail"]
    # 完成后会话被移除，避免"已完成"状态一直挂着
    assert reg.get("app_zhixing") is None


def test_finish_fails_when_verify_says_not_logged_in():
    reg = AppLoginRegistry()
    ctx, _ = _ctx(verify=lambda: (False, "页面仍是登录墙"))
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_finish(reg, "app_zhixing", ctx["verify"])
    assert code == 409 and out["ok"] is False
    assert "登录墙" in out["err"]


def test_finish_tolerates_verify_exception():
    """校验函数自己崩了，不能把用户已完成的登录判成失败。"""
    def boom():
        raise RuntimeError("dump failed")

    reg = AppLoginRegistry()
    ctx, _ = _ctx(verify=boom)
    login_api.handle_create(reg, "app_zhixing", PACKAGES, ctx["runtime_factory"])
    out, code = login_api.handle_finish(reg, "app_zhixing", ctx["verify"])
    assert code == 200 and out["ok"] is True


def test_parse_body_limits_size():
    assert login_api.parse_body(b'{"plat":"x"}') == {"plat": "x"}
    try:
        login_api.parse_body(b"{" + b"0" * 40000)
        assert False, "超长 body 应拒绝"
    except ValueError:
        pass


def test_parse_body_bad_json_is_empty_dict():
    assert login_api.parse_body(b"not json") == {}


def test_dispatch_routes_state_and_unknown():
    reg = AppLoginRegistry()
    out, code = login_api.dispatch(reg, "GET", "/api/app-login/state",
                                   {"plat": ["app_zhixing"]}, None, {})
    assert code == 200 and out["session"] is None
    _, code2 = login_api.dispatch(reg, "GET", "/api/app-login/bogus", {}, None, {})
    assert code2 == 404


# ---- r647：没有活动会话时也要报「快照已保存」 ----
def test_state_reports_snapshot_when_no_session():
    """会话结束后卡片仍要能显示「已保存」，否则用户以为登录白做。

    实测：用户在真机画面里登录完、快照存了 3.6MB，但会话结束后
    /api/app-login/state 返回 session:null，前端于是画「未保存会话」。
    """
    from core.android import login_api as la
    from core.android.login_session import AppLoginRegistry

    reg = AppLoginRegistry()
    body, code = la.handle_state(
        reg, "app_zhixing",
        lambda p: {"exists": True, "mtime": 1793325795.0})
    assert code == 200 and body["session"] is None
    assert body["saved"] is True, body
    assert body["saved_at"] == 1793325795.0, body


def test_state_without_snapshot_is_honest():
    """没有快照时必须报 saved=False——不能为了好看而谎称已保存。"""
    from core.android import login_api as la
    from core.android.login_session import AppLoginRegistry

    body, _ = la.handle_state(AppLoginRegistry(), "app_zhixing",
                              lambda p: {"exists": False})
    assert body["saved"] is False
    assert body["saved_at"] == 0


def test_state_survives_snapshot_info_error():
    """快照探测抛异常不能把整个状态接口打 500。"""
    from core.android import login_api as la
    from core.android.login_session import AppLoginRegistry

    def boom(_p):
        raise OSError("disk")

    body, code = la.handle_state(AppLoginRegistry(), "app_zhixing", boom)
    assert code == 200 and body["saved"] is False
