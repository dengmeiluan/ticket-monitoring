# -*- coding: utf-8 -*-
"""r1063 T34：换道前先看 App 通路**就绪**没有——把无效换道挡在门外。

以前只要「有 App 孪生 + 预算够」就换。若 `android.enabled=false` 或 App 渠道
没注册，这次换道**必然 0 条**，还白占一天一次的额度。

判不了的（会话是否已登录）**不猜**：返回就绪，让它去试，失败由 T33 的归因
说清是"未登录"还是"被拦"。核账与就绪度都遵守同一条：只判能证明的。
"""
import io
import os
import tempfile

from core import failover as fo
from core import strategy_params as sp

MAIN = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()


def test_ready_gate_blocks_when_not_ready():
    d = tempfile.mkdtemp()
    app, why = fo.plan_switch(
        "ctrip", "captcha", {}, user_data_dir=d,
        ready=lambda _a: (False, "安卓链路未启用"))
    assert app == "" and "未就绪" in why, why


def test_ready_gate_passes_when_ready():
    d = tempfile.mkdtemp()
    app, _why = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d,
                              ready=lambda _a: (True, ""))
    assert app == "app_ctrip"


def test_ready_gate_is_fail_open_on_errors():
    """就绪检查自己炸了不许挡住换道（否则一个 bug 会让整条兜底失效）。"""
    d = tempfile.mkdtemp()

    def _boom(_a):
        raise RuntimeError("readiness 出问题")

    app, _why = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d,
                              ready=_boom)
    assert app == "app_ctrip"


def test_no_ready_callback_keeps_old_behaviour():
    d = tempfile.mkdtemp()
    assert fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d)[0] == "app_ctrip"


def test_main_wires_the_readiness_checker():
    assert "def _app_ready(" in MAIN
    assert "ready=_app_ready" in MAIN
    # 只判能离线判定的两件事：安卓总开关、App 渠道是否注册
    assert "android.enabled=false" in MAIN
    assert "未注册" in MAIN
    # 被挡住要有归因（否则用户不知道为什么没换）
    assert "换道被挡" in MAIN
