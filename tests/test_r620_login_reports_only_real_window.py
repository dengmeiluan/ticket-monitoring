# -*- coding: utf-8 -*-
"""r620（GitHub #10 未修完的一半）：/api/login 不能在线程刚起时就报「已弹出」。

#10 的原修复只补了「无图形环境」这一种已知原因。但「窗口没开成」还有
很多种：缺 Playwright 浏览器内核、profile 被采集占用、显示服务异常、
goto 超时……原实现对这些一律先回报成功：

    threading.Thread(target=_run, daemon=True).start()
    _State.logger.info("[登录] 已弹出 %s 登录窗口", key)
    return {"ok": True, ...}

于是用户看到「登录窗口已弹出」，然后什么也没有发生——正是 issue 描述。
**判据不能是「已知的失败原因」清单，而是「窗口真的开了吗」这个事实。**

修法：`_login_window` 在 goto 成功后置位 `ready_evt`；接口等它（≤45s），
拿到才回报成功；线程先失败或超时就回报 `kind="window_failed"` 与原因，
并清掉 login_sessions（否则用户会被「窗口已打开」永久挡住）。

负控：把等待改回「起线程即返回 ok」→ 第一、二条真红。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from crawlers import base as _base  # noqa: E402


class _BoomCrawler:
    """模拟 Playwright 起不来（缺内核 / 显示不可用）。"""

    name = "ctrip"
    _cooldown_until = 0

    def _login_window(self, done_evt, idx=0, timeout_s=0, ready_evt=None):
        raise RuntimeError("Executable doesn't exist at chromium-1234")


class _OkCrawler:
    """窗口真的开了：置位 ready 后等 done。"""

    name = "ctrip"
    _cooldown_until = 0

    def _login_window(self, done_evt, idx=0, timeout_s=0, ready_evt=None):
        if ready_evt is not None:
            ready_evt.set()
        while not done_evt.is_set():
            time.sleep(0.05)
        return True


def _slot():
    from core.login_slots import LOGIN_SLOTS
    for k, m in LOGIN_SLOTS.items():
        return k, m["plat"]
    raise AssertionError("没有登录槽位")


def _reset(key):
    for d in (webui._State.login_errors, webui._State.login_sessions,
              webui._State.login_pending):
        d.pop(key, None)


def _patch(monkeypatch, factory):
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key_arg, cfg=None, logger=None: factory())


def _drain(key, timeout=8):
    """收尾：让登录线程退出，别把渠道锁留给下一个用例。"""
    sess = webui._State.login_sessions.get(key)
    if sess:
        sess["evt"].set()
        sess["done"].wait(timeout)
    _reset(key)


def test_window_open_failure_is_reported_not_swallowed(monkeypatch):
    key, plat = _slot()
    _patch(monkeypatch, lambda: _BoomCrawler())
    _reset(key)
    t0 = time.time()
    r = webui._start_login(plat, key)
    dt = time.time() - t0
    # 先断言状态，再清理（_drain 会抹掉 login_errors）
    try:
        assert r.get("ok") is False, (
            "窗口根本没开成，接口却回报成功：%r" % (r,))
        assert r.get("kind") == "window_failed", (
            "失败没有归类为 window_failed（前端无法给专属提示）：%r" % (r,))
        assert r.get("err"), "失败没有给出原因"
        assert "chromium-1234" in r["err"], (
            "原因没传到点击者（只给了笼统一句）：%r" % (r,))
        assert dt < 30, "失败应在就绪等待内立刻返回，实际等了 %.1fs" % dt
        assert key not in webui._State.login_sessions, (
            "失败后会话没清掉——用户会被「窗口已打开」永久挡住")
        assert key in webui._State.login_errors, "失败原因没落到状态里"
        assert "chromium-1234" in webui._State.login_errors[key], (
            "落到状态里的原因不具体：%r" % webui._State.login_errors[key])
    finally:
        _drain(key)


def test_log_does_not_claim_window_opened_before_it_did(monkeypatch):
    """日志时序：先失败时不得留下「已弹出」的成功句（#10 的同期症状）。"""
    key, plat = _slot()
    _patch(monkeypatch, lambda: _BoomCrawler())
    _reset(key)
    import logging

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    cap = _Cap()
    webui._State.logger.addHandler(cap)
    try:
        webui._start_login(plat, key)
        time.sleep(0.3)
    finally:
        webui._State.logger.removeHandler(cap)
        _drain(key)
    opened = [m for m in cap.lines if "已弹出" in m]
    assert not opened, "窗口没开成却记下了「已弹出」：%r" % opened
    assert any("未能打开" in m for m in cap.lines), (
        "失败没有留下可查的日志：%r" % cap.lines)


def test_ready_window_still_reports_success(monkeypatch):
    """真开成时行为不变：仍返回 ok + plat/slot（回归护栏）。"""
    key, plat = _slot()
    _patch(monkeypatch, lambda: _OkCrawler())
    _reset(key)
    r = webui._start_login(plat, key)
    try:
        assert r.get("ok") is True, r
        assert r.get("slot") == key and r.get("plat"), r
    finally:
        _drain(key)


def test_busy_channel_waits_but_is_bounded(monkeypatch):
    """采集正占着渠道锁时：用户在排队——仍要能开成，且不无限等。

    这里用「另一个线程先持锁、0.5s 后放开」来模拟采集收尾。
    """
    key, plat = _slot()
    _patch(monkeypatch, lambda: _OkCrawler())
    _reset(key)
    lock = _base.platform_lock(str(plat))
    holder = threading.Thread(target=lambda: (lock.acquire(), time.sleep(0.5),
                                              lock.release()), daemon=True)
    holder.start()
    time.sleep(0.05)
    r = webui._start_login(plat, key)
    holder.join(5)
    _drain(key)
    assert r.get("ok") is True, (
        "等锁后应当照常开窗，实际：%r" % (r,))


def test_no_gui_kind_is_still_returned_on_posix_headless(monkeypatch):
    """原有 no_gui 判据不许被这次改动挤掉（Windows/macOS 不受影响）。"""
    key, plat = _slot()
    # 只替换单源判据：从前 patch 的是进程级 `os.environ.get`，
    # monkeypatch 复原时会把补丁泄漏给同进程其它用例——实测让
    # `_bind_host` 读到被替换的 get，容器监听地址门禁在 CI 上假红。
    monkeypatch.setattr(webui, "_no_graphical_env", lambda: True)
    _reset(key)
    r = webui._start_login(plat, key)
    assert r.get("ok") is False and r.get("kind") == "no_gui", r
