# -*- coding: utf-8 -*-
"""r959：设备锁持有者必须上健康页，而不是只躺在日志里。

r925 事故（见 test_r925_device_lock_owner.py）里，worker 永久占锁，
日志只写「路由级超时/skipped」，连续 10 小时查不出是谁。r925 补了
模块级 owner 记录；本文件把「谁占着、多久、预算耗尽几次」接到
/api/health 与健康诊断卡标题行，避免观测只对会翻日志的人可用。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from entry_mon_harness import page, srv, _goto  # noqa: F401,E402


def test_view_reports_owner_and_budget(monkeypatch):
    import webui
    from core.android import runtime as rt_mod

    class FakeRT:
        def lock_state(self):
            return {"owner": "app_qunar",
                    "since": time.time() - 187,
                    "budget_left": 12.5, "deadline_hits": 3}

    monkeypatch.setattr(rt_mod, "get_runtime",
                        lambda cfg, logger=None: FakeRT())
    v = webui._device_lock_view({"android": {"enabled": True}})
    assert v["enabled"] is True
    assert v["owner"] == "app_qunar"
    assert 186 <= v["held_s"] <= 190, v
    assert v["budget_left"] == 12.5 and v["deadline_hits"] == 3


def test_view_is_silent_when_android_disabled():
    import webui
    v = webui._device_lock_view({"android": {"enabled": False}})
    assert v == {"enabled": False, "owner": "", "held_s": 0,
                 "budget_left": 0.0, "deadline_hits": 0,
                 "unavailable": ""}


def test_health_payload_carries_lock_view():
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    assert '_hp["device_lock"] = _device_lock_view(' in w
    assert 'out["device_lock"] = _device_lock_view({})' in w


def test_diag_meta_renders_holder(page):
    _goto(page)
    got = page.evaluate("""()=>{
      HL=JSON.stringify({diag_at:'2026-11-04 10:00',diag:[],
        device_lock:{enabled:true,owner:'app_qunar',held_s:187,
                     deadline_hits:2}});
      renderHealthDiag();
      return document.getElementById('healthDiagMeta').textContent;}""")
    assert "app_qunar" in got and "187s" in got and "预算耗尽 2 次" in got, got
    idle = page.evaluate(
        "()=>healthLockMeta({device_lock:{enabled:true,owner:''}})")
    assert "空闲" in idle
    off = page.evaluate(
        "()=>healthLockMeta({device_lock:{enabled:false}})")
    assert off == ""
