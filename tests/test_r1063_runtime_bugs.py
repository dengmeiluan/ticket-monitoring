# -*- coding: utf-8 -*-
"""r1063 T59：两个「只在运行时炸」的真 bug 的回归门禁。

1. `QunarCrawler._open_wait_backoff()` 与 `_WAIT_BACKOFF_*` 之前**都没定义**，
   而"本轮等待预算用尽"这条高频分支一走到就 AttributeError；
2. `core/android/geo.py` 调的是 `dev.sh(...)`，真实设备是 `AdbDevice._sh` /
   `run_script` —— 于是**定位固定从来没生效过**，还被 fail-soft 静默吞掉。
"""
import logging
import time

import pytest

from core.android import geo
from crawlers.qunar import QunarCrawler


@pytest.fixture(autouse=True)
def _reset():
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK = 0
    yield
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK = 0


def test_wait_backoff_escalates_and_caps():
    c = QunarCrawler({}, logging.getLogger("t59"))
    seen = [c._open_wait_backoff() for _ in range(8)]
    # r952 起窗口按 1x/2x/3x 增长（默认 1200s 起步、3600s 封顶）；
    # 旧的 15/30/60/600 固定梯已被 `docs/YIELD_AND_SESSION_STRATEGY.md` 取代。
    assert seen[:4] == [1200, 2400, 3600, 3600], seen
    assert max(seen) <= QunarCrawler.WAIT_BACKOFF_MAX_S
    assert QunarCrawler._WAIT_BACKOFF_UNTIL > time.time()


def test_wait_backoff_resets_when_data_returns():
    c = QunarCrawler({}, logging.getLogger("t59"))
    c._open_wait_backoff()
    c._reset_wait_backoff()
    assert QunarCrawler._WAIT_BACKOFF_STREAK == 0
    assert QunarCrawler._WAIT_BACKOFF_UNTIL == 0.0


class _ShDevice:
    """真实 `AdbDevice` 的形状：只有 `_sh(*args)`。"""

    def __init__(self):
        self.calls = []

    def _sh(self, *args, timeout=None):
        self.calls.append(" ".join(str(a) for a in args))
        return "OK"


class _ScriptDevice:
    """只有 `run_script(script)` 的瘦设备。"""

    def __init__(self):
        self.calls = []

    def run_script(self, script, timeout=None):
        self.calls.append(str(script))
        return "OK"


def test_geo_uses_the_real_device_api():
    dev = _ShDevice()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": True}}})
    assert rep["ok"] is True, rep
    joined = " | ".join(dev.calls)
    # 经度在前（写反就钉到海里）
    assert "emu geo fix 121.4921 31.1874" in joined, joined
    assert "location_mode 3" in joined, joined


def test_geo_falls_back_to_run_script_for_shell_commands():
    dev = _ScriptDevice()
    rep = geo.fix(dev, None)
    # emu 命令走不了 run_script（不是 shell 形式），但定位开关应该尽力打开
    assert any("location_mode 3" in c for c in dev.calls), dev.calls
    assert rep.get("providers") is True, rep


def test_geo_reports_a_clear_error_when_the_device_has_no_adb():
    class Bad:
        pass

    rep = geo.fix(Bad(), None)
    assert rep["ok"] is False
    assert "adb" in str(rep.get("detail") or ""), rep
