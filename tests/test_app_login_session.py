# -*- coding: utf-8 -*-
"""App 登录会话状态机：帧去重、坐标校验、过期、并发互斥。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.android.login_session import (ST_DONE, ST_ERROR, ST_EXPIRED,
                                        ST_PENDING, AppLoginRegistry,
                                        AppLoginSession)


class FakeDevice:
    def __init__(self, pngs=None, size=(900, 1600), tap_ok=True):
        self.pngs = list(pngs or [b"\x89PNG-a"])
        self.size = size
        self.tap_ok = tap_ok
        self.taps = []
        self.texts = []

    def screencap(self):
        if len(self.pngs) > 1:
            return self.pngs.pop(0)
        return self.pngs[0] if self.pngs else b""

    def window_size(self):
        return self.size

    def tap(self, x, y):
        self.taps.append((x, y))
        return self.tap_ok

    def input_text(self, t):
        self.texts.append(t)
        return True

    def keyevent(self, k):
        return True


class FakeRuntime:
    def __init__(self, device):
        self._d = device

    def device(self):
        return self._d


def _session(dev=None, **kw):
    dev = dev or FakeDevice()
    return AppLoginSession("app_zhixing", FakeRuntime(dev),
                           "cn.suanya.zhixing", **kw), dev


def test_frame_first_call_returns_png():
    s, _ = _session()
    png, changed = s.frame()
    assert png.startswith(b"\x89PNG") and changed is True


def test_frame_identical_content_is_deduplicated():
    """同一画面不重复传全图——否则每 250ms 白传 200KB。"""
    dev = FakeDevice(pngs=[b"\x89PNG-same", b"\x89PNG-same"])
    s, _ = _session(dev)
    s.frame()              # 第一帧
    png, changed = s.frame()
    assert png == b"" and changed is False


def test_frame_changed_content_is_returned():
    dev = FakeDevice(pngs=[b"\x89PNG-a", b"\x89PNG-b"])
    s, _ = _session(dev)
    s.frame()
    png, changed = s.frame()
    assert png == b"\x89PNG-b" and changed is True


def test_tap_rejects_out_of_screen():
    dev = FakeDevice(size=(900, 1600))
    s, _ = _session(dev)
    assert s.tap(5000, 10) is False
    assert dev.taps == []
    assert "超出屏幕" in s.detail


def test_tap_rejects_negative():
    dev = FakeDevice()
    s, _ = _session(dev)
    assert s.tap(-1, 10) is False
    assert dev.taps == []


def test_tap_accepts_valid_and_counts():
    dev = FakeDevice(size=(900, 1600))
    s, _ = _session(dev)
    assert s.tap(450, 800) is True
    assert dev.taps == [(450, 800)]
    assert s.taps == 1


def test_tap_refused_after_finish():
    dev = FakeDevice()
    s, _ = _session(dev)
    s.finish(True, "done")
    assert s.tap(10, 10) is False
    assert dev.taps == []


def test_input_text_forwarded():
    dev = FakeDevice()
    s, _ = _session(dev)
    assert s.input_text("13800138000") is True
    assert dev.texts == ["13800138000"]


def test_expiry_marks_expired_and_blocks_interaction():
    dev = FakeDevice()
    s, _ = _session(dev, timeout_s=1)
    time.sleep(1.05)
    assert s.expired() is True
    assert s.alive() is False


def test_registry_marks_expired_on_get():
    dev = FakeDevice()
    s, _ = _session(dev, timeout_s=1)
    reg = AppLoginRegistry()
    reg.put(s)
    time.sleep(1.05)
    got = reg.get("app_zhixing")
    assert got.status == ST_EXPIRED
    assert got.view()["can_interact"] is False


def test_registry_rejects_second_concurrent_session():
    reg = AppLoginRegistry()
    reg.put(_session()[0])
    with pytest.raises(ValueError):
        reg.put(_session()[0])


def test_registry_allows_restart_after_error():
    reg = AppLoginRegistry()
    s1 = _session()[0]
    s1.finish(False, "boom")
    reg.put(s1)
    s2 = _session()[0]
    reg.put(s2)          # 上一个已结束，允许重新发起
    assert reg.get("app_zhixing") is s2


def test_view_shape():
    s, _ = _session()
    v = s.view()
    assert v["plat"] == "app_zhixing"
    assert v["status"] == ST_PENDING
    assert v["can_interact"] is True


def test_finish_sets_status():
    s, _ = _session()
    s.finish(True, "ok")
    assert s.status == ST_DONE
