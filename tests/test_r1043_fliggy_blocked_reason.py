# -*- coding: utf-8 -*-
"""飞猪「被风控拦」与「没进表单」必须分开记账。

两者页面外观一样，但处置完全不同：
- 风控（`ContainerActivity` / 「访问被拒绝」）→ 记 `blocked`，要人工过安全页；
- 没进表单 → 记 `app-form timeout`，才该去查坐标/解析。
此前一律记 timeout，反复把人引到错误方向（2026-11-05 实测踩了多次）。
"""
import logging

import yaml

from crawlers.app_fliggy import AppFliggyCrawler


class _FakeDev:
    def __init__(self, act="", words=None):
        self._act = act
        self._words = words or []

    def current_activity(self):
        return self._act

    def dump(self):
        return ""


def _crawler(tmp_path=None):
    cfg = {"user_data_dir": "user_data", "android": {}}
    c = AppFliggyCrawler(cfg, logging.getLogger("test"))
    return c


def _with_ocr(monkeypatch, words):
    c = _crawler()
    monkeypatch.setattr(c, "_ocr", lambda dev: words)
    return c


def test_security_container_is_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [])
    dev = _FakeDev(act="com.taobao.trip/com.alibaba.wireless.security.open."
                       "middletier.fc.ui.ContainerActivity")
    r = c._blocked_reason(dev)
    assert "安全容器" in r


def test_access_denied_text_is_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [{"t": "访问被拒绝"}, {"t": "请稍后再试"}])
    r = c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity"))
    assert "访问被拒绝" in r


def test_plain_home_is_not_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [{"t": "机票"}, {"t": "酒店"}])
    r = c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity"))
    assert r == ""


def test_ocr_failure_degrades_to_not_blocked(monkeypatch):
    """OCR 挂了不能误判成风控——否则会把"读不到字"记成"被拦"。"""
    c = _crawler()

    def _boom(dev):
        raise RuntimeError("ocr down")

    monkeypatch.setattr(c, "_ocr", _boom)
    assert c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity")) == ""
