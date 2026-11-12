# -*- coding: utf-8 -*-
"""r1374：App 登录态要能**自动发现**（幂等），不能只认"有没有导过快照"。

用户原话：「为什么后台不能发现 App 已经登录了，状态自动幂等？浏览器一样」

浏览器卡片的状态是从 profile/快照自动推出来的；App 以前只看「有没有导出快照」，
于是设备上明明登着（账本里明明有 ok 行），卡片却只说「未保存会话」。

本文件钉两件事：
1. 后端 `/api/app-login/state` 必须报出**账本侧证据** `device_state/at/why`；
2. 证据注入失败时**降级为空**，不许把接口打成 500。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import login_api as api  # noqa: E402


class _Reg:
    def get(self, plat):
        return None          # 没有进行中的登录会话


def test_state_reports_device_evidence():
    out, code = api.handle_state(
        _Reg(), "app_fliggy",
        snapshot_info=lambda p: {"exists": False},
        needs_login=lambda p: False,
        device_state=lambda p: {"state": "logged_in", "at": "2026-11-10 21:41:53",
                                "why": "最近一轮出过数"})
    assert code == 200, out
    assert out["device_state"] == "logged_in", out
    assert out["device_at"] == "2026-11-10 21:41:53", out
    assert out["device_why"], out
    # 快照仍然没有 —— 两件事分开表达，不许互相冒充
    assert out["snapshot_saved"] is False, out
    assert out["evidence"] == "无", out


def test_state_reports_login_wall():
    out, _ = api.handle_state(
        _Reg(), "app_ctrip", None, None,
        device_state=lambda p: {"state": "login_wall", "at": "2026-11-10 22:57",
                                "why": "命中登录墙"})
    assert out["device_state"] == "login_wall", out


def test_broken_evidence_degrades_to_empty():
    """负控：证据回调抛异常时，接口必须照常返回（只是没有证据）。"""
    def _boom(plat):
        raise RuntimeError("db locked")

    out, code = api.handle_state(_Reg(), "app_qunar", None, None, device_state=_boom)
    assert code == 200, out
    assert out["device_state"] == "", out
    assert out["device_at"] == "", out


def test_frontend_maps_device_state_to_status():
    """前端必须把账本结论合成为 status，否则各卡片消费者读不到。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'device_state:String((j&&j.device_state)||\'\')' in src, "前端没读 device_state"
    assert "'login_wall'?'login_required'" in src, "登录墙没映射成需登录"
    assert "'logged_in'?'live_unsaved'" in src, "已登录没映射成「设备已登录·未存快照」"
    assert "live_unsaved:'设备已登录 · 未存快照'" in src, "缺 live_unsaved 词面"
    # 卡片消费者统一走 slotStatusCn → 必须能翻译这个新状态
    assert "function slotStatusCn(st){return SLOT_STATUS_CN[st]" in src
