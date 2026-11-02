# -*- coding: utf-8 -*-
"""r726 空 dump 不得当成「页面不是这样」。

真机实证（2026-10-31，智行 App 冷启动）：`app_start` 之后**头 4 帧
`dev.dump()` 全是空串**，第 5 帧才出现首页。而 `is_intl_form("")` 为
False，`select_mode` 据此判「已是国内档」→ 跳过切档 → 在还没渲染的
首页上找城市行 → 整轮记成「设出发地失败：找不到城市行」。

这条账本把「没取到页面」写成了「控件不存在」，用户按提示去查选择器，
实际只要等两秒。所以判据必须是：**先拿到页面，再谈页面长什么样**。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import app_zhixing_nav as nav  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_clock(monkeypatch):
    """这些用例只测判据，不该真等 30s。

    只 patch `sleep` 不够：`_await_home` 的 deadline 用 `time.time()` 算，
    真时钟不动就仍然会空转满 30 秒（实测本文件跑了 30.5s）。所以换成
    一个「sleep 即前进」的假时钟。
    """
    class _Clock:
        def __init__(self):
            self.now = 1000.0

        def time(self):
            return self.now

        def sleep(self, s=0):
            self.now += float(s or 0)

        def __getattr__(self, name):
            import time as _t
            return getattr(_t, name)

    clock = _Clock()
    monkeypatch.setattr(nav, "time", clock)
    return clock


class FakeDev:
    """按帧序列返回 dump；`tap` 之后切到另一组帧（模拟页面变化）。"""

    def __init__(self, frames, after_tap=None):
        self.frames = list(frames)
        self.after_tap = list(after_tap or [])
        self.taps = []

    def dump(self, *a, **k):
        if self.frames:
            return self.frames.pop(0)
        return ""

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.after_tap:
            self.frames = list(self.after_tap)
            self.after_tap = []
        return True

    def keyevent(self, *a, **k):
        return True


def _home_xml(intl=False, from_city="上海", to_city="北京"):
    """最小可用的智行首页 dump（含「机票查询」；国际档带舱位行）。"""
    parts = [
        '<node text="机票查询" bounds="[400,700][500,800]" />',
        '<node text="%s" bounds="[60,460][90,484]" />' % from_city,
        '<node text="%s" bounds="[810,460][850,484]" />' % to_city,
        '<node text="国内" bounds="[100,330][150,360]" />',
        '<node text="国际" bounds="[260,330][310,360]" />',
    ]
    if intl:
        parts.append(
            '<node text="经济/超级经济舱" bounds="[700,600][860,630]" />')
    return "<hierarchy>" + "".join(parts) + "</hierarchy>"


def test_empty_dump_is_not_treated_as_domestic():
    """空帧之后才是国际档：必须切到国内，而不是跳过切档。

    负控：修复前 `select_mode` 拿第一帧空串算出 `is_intl_form("")==False`
    → 判「已是国内档」直接返回 ok，`taps` 为空，本用例红。
    """
    dev = FakeDev(["", "", "", _home_xml(intl=True), _home_xml(intl=True)],
                  after_tap=[_home_xml(intl=False)])
    ok, detail = nav.select_mode(dev, intl=False)
    assert ok, detail
    assert dev.taps, "没点「国内」标签，说明把空帧判成了「已是国内档」"
    assert "已是" not in detail, detail


def test_await_home_reports_failure_when_never_ready():
    """一直拿不到页面要如实返回未就绪，不能当成「页面里没有该控件」。"""
    dev = FakeDev(["", "", ""])
    xml, ready = nav._await_home(dev, timeout_s=0.2)
    assert ready is False
    assert xml == ""


def test_select_mode_fails_loudly_on_no_page():
    dev = FakeDev([])
    ok, detail = nav.select_mode(dev, intl=False)
    assert ok is False
    assert "没取到首页" in detail, detail


def test_await_home_ignores_calendar_overlay():
    """停在「选择日期」弹层上不算首页（否则会在弹层上找城市行）。"""
    cal = ('<hierarchy><node text="Search_Calendar_Dialog_Title" />'
           '<node text="机票查询" bounds="[0,0][10,10]" /></hierarchy>')
    dev = FakeDev([cal, cal, _home_xml()])
    xml, ready = nav._await_home(dev, timeout_s=5)
    assert ready is True
    assert "Search_Calendar_Dialog_Title" not in xml


def test_route_setup_never_decides_on_a_bare_dump():
    """守卫：设航线路径上「dump → 立刻下找不到的结论」的写法不许再出现。

    不是样式检查——上面几条测行为，这条防后来者在新加的分支里重新引入
    同一个坑：`xml = dev.dump()` 紧跟 `ns = nodes(xml)` 就等于「空帧 ⇒
    找不到控件」。一律走 `_await_home`（它会区分没取到和真没有）。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    start = src.index("def set_flight_route")
    end = src.index("def _city_row", start)
    body = src[start:end]
    lines = body.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if line.strip() != "xml = dev.dump()":
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("ns = nodes(xml)"):
            bad.append(i + 1)
    assert not bad, (
        "set_flight_route 第 %s 行还是裸 dump→nodes：空帧会被读成「页面没有"
        "该控件」，应改用 _await_home" % bad)
