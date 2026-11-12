# -*- coding: utf-8 -*-
"""画中画工作台：近全屏 / 专注 / 可拖动浮窗，且不污染浏览器登录弹窗。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def test_app_modal_is_a_large_workspace_not_the_520_dialog():
    src = _src()
    assert '#lgModal[data-kind="app"]' in src
    assert "min(1180px" in src, "App 画面没有放大成工作台"
    assert ".appworkspace" in src and ".apprail" in src
    # 浏览器登录弹窗仍保留原来的窄窗，不能被 App 规则连带放大
    assert "width:min(520px,calc(100vw - 24px))" in src


def test_modes_focus_minimize_restore_exist():
    src = _src()
    for token in ("function appLoginFocus(", "function appLoginMinimize(",
                  "function appLoginRestore(", ".appfloat",
                  "appfocus", "APP_LOGIN.mode", "appheadic"):
        assert token in src, token
    # App 图标走独立 squircle 质感层；浏览器方标保持原 .bic-ota
    assert ".bic-app{" in src and "bic bic-ota " in src
    assert "bic-app " in src
    assert "srxPlatIcon(plat)" in src


def test_shared_close_stops_app_polling():
    """遮罩/Esc 走 lgCloseModal 时，App 会话必须停，不能只藏窗继续轮询。"""
    src = _src()
    i = src.index("function lgCloseModal(")
    seg = src[i:src.index("\nfunction ", i + 10)]
    assert "appLoginClose" in seg, "共享关闭没有停掉 App 帧轮询"
    assert "dataset.kind" in seg, "共享关闭没有按弹窗归属分流"


def test_inline_text_and_device_info_are_wired():
    src = _src()
    for token in ('id="appTextInput"', "appLoginTextSend(",
                  "api/app-login/info", "appLoginMeta("):
        assert token in src, token


def test_floating_panel_unlocks_page_scroll_and_clamps():
    src = _src()
    for token in ("appLoginLock(", "appFloatDragStart(",
                  "appFloatClamp(", "localStorage"):
        assert token in src, token
