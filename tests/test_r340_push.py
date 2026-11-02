# -*- coding: utf-8 -*-
"""r340 推送审校落地（_scratch/r340_push_review.md P2-1）：

main.py 渠道登录态告警/恢复 desp 手拼绕过行宽守卫链——告警单行
112 半角实发在案（手机 40 半角红线的 2.8 倍）、恢复文案 45/40 同病。
修法（审校修法一：段落律重排 ≤40）：按钉钉双端段落律 \n\n 重排，
每段数学 ≤40 半角（平台名取 REGISTRY 最长 9 字符、连续轮数 3 位数
最坏形态计宽），行为钉以 _dw 真值锁死每段 ≤40 + 无段落内单换行，
语义地板=渠道名/连续轮数/重新登录指引逐项在场。

行为钉隔离纪律：_SENT_LAST/_SENT_CNT/_LOGIN_ALERT_STREAK 一律
monkeypatch 全新 dict、_sent_save 猴补 no-op——生产 sentinel_state.json
字节不动（loginstreak 合成残留事故的隔离面，LESSONS 廿二§4）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r340_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import crawlers
import main
from core.alerter import _dw


class _FakeNf:
    def __init__(self):
        self.sent = []

    def send(self, title, desp, **kw):
        self.sent.append((title, desp))


class _FakeAl:
    def __init__(self, nf):
        self.notifier = nf


@pytest.fixture()
def iso(monkeypatch):
    monkeypatch.setattr(main, "_SENT_LAST", {})
    monkeypatch.setattr(main, "_SENT_CNT", {})
    monkeypatch.setattr(main, "_LOGIN_ALERT_STREAK", {})
    monkeypatch.setattr(main, "_sent_save", lambda: None)
    return monkeypatch


def _run(iso, plat="qunar", suspect=True):
    iso.setitem(crawlers.REGISTRY, plat,
                type("C", (), {"login_suspect": suspect}))
    nf = _FakeNf()
    main._channel_login_alert_sentinel(
        [({"platforms": [plat]}, _FakeAl(nf))],
        logging.getLogger("r340"))
    return nf


def _assert_paragraph_law(desp):
    parts = desp.split("\n\n")
    assert all("\n" not in p for p in parts), \
        f"段落内存在单换行（PC 端粘行律，LESSONS 十§1）: {desp!r}"
    over = [(p, _dw(p)) for p in parts if _dw(p) > 40]
    assert not over, f"超手机 40 半角红线: {over} (desp={desp!r})"


def test_login_alert_desp_paragraph_law(iso):
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"qunar": 1})
    nf = _run(iso, "qunar", suspect=True)
    assert nf.sent, "连续 2 轮应触发告警"
    title, desp = nf.sent[0]
    assert title == "渠道登录态告警", title
    _assert_paragraph_law(desp)
    assert "qunar" in desp, desp
    assert "2" in desp, desp
    assert "登录" in desp, desp


def test_login_alert_desp_worst_platform_width(iso):
    """平台名最长（tongcheng 9 字符）+ 3 位数轮数的最坏计宽形态。"""
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"tongcheng": 998})
    nf = _run(iso, "tongcheng", suspect=True)
    assert nf.sent, "连续 999 轮应触发告警"
    _assert_paragraph_law(nf.sent[0][1])
    assert "tongcheng" in nf.sent[0][1]
    assert "999" in nf.sent[0][1]


def test_login_recover_desp_paragraph_law(iso):
    import datetime as _dt
    today = _dt.date.today().isoformat()
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"qunar": 2})
    iso.setattr(main, "_SENT_LAST", {("qunar", "login"): today})
    nf = _run(iso, "qunar", suspect=False)
    assert nf.sent, "恢复路径应发通知"
    title, desp = nf.sent[0]
    assert title == "渠道登录态恢复", title
    _assert_paragraph_law(desp)
    assert "qunar" in desp and "恢复" in desp, desp
