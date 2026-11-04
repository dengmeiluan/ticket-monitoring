# -*- coding: utf-8 -*-
"""r821：App 的前台准备必须在设备锁内，不能和其它 App 渠道并发抢前台。

2026-11-02 21:23 线上实测（同一轮两个 App 渠道）：
  app_qunar 刚 `已启动 com.Qunar`，前台却已经是 `cn.suanya.zhixing`；
  app_qunar 记「已启动但前台仍是别人」，随后 app_zhixing 也失败。

根因：app_zhixing.fetch 在 `with rt.device_lock()` **之前**调用
`prepare_device()`（它会 app_start/切前台），而 app_qunar/tongcheng/ctrip/
fliggy 都在锁内调用。锁外的启动与锁内的采集并发，谁最后启动谁抢前台。
"""
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing import AppZhixingCrawler  # noqa: E402

_LOG = logging.getLogger("t_r821")


class _Lock:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("lock-enter")
        return self

    def __exit__(self, *a):
        self.events.append("lock-exit")
        return False


class _Runtime:
    def __init__(self, events):
        self.events = events

    def ensure_ready(self):
        return True, "ready"

    def device(self):
        return object()

    def device_lock(self, timeout=600.0, owner=""):
        # 与真实 AndroidRuntime.device_lock 同签名（2026-11-04 起多了 owner，
        # 用于「谁占着锁」的观测）——假实现要跟上，否则渠道侧传参会 TypeError。
        return _Lock(self.events)


def test_zhixing_prepare_device_happens_inside_device_lock(monkeypatch):
    events = []
    c = AppZhixingCrawler({}, _LOG)
    monkeypatch.setattr(c, "runtime", lambda: _Runtime(events))
    monkeypatch.setattr(c, "prepare_device",
                        lambda dev: events.append("prepare"))
    monkeypatch.setattr(c, "_fetch_locked",
                        lambda *a, **k: events.append("fetch") or [])
    monkeypatch.setattr(c, "_fetch_round_trip_locked",
                        lambda *a, **k: events.append("rt") or [])

    c.fetch("SHA", "BKK", ["2026-11-16"])
    assert events == ["lock-enter", "prepare", "fetch", "lock-exit"], events


def test_all_app_crawlers_prepare_inside_device_lock():
    """所有 App 渠道的前台准备都必须在锁内（新增渠道也别再踩）。"""
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in sorted(glob.glob(os.path.join(root, "crawlers", "app_*.py"))):
        if os.path.basename(path) in ("app_base.py", "app_blockers.py",
                                      "app_zhixing_nav.py",
                                      "app_zhixing_roundtrip.py",
                                      "app_qunar_roundtrip.py"):
            continue
        src = open(path, encoding="utf-8").read()
        for i, line in enumerate(src.splitlines(), 1):
            if line.strip() == "self.prepare_device(dev)":
                assert line.startswith("            "), (
                    "%s:%d prepare_device 不在设备锁内（缩进 %d）"
                    % (os.path.basename(path), i, len(line) - len(line.lstrip())))


def test_zhixing_source_keeps_prepare_inside_lock():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "crawlers", "app_zhixing.py"),
               encoding="utf-8").read()
    start = src.index("    def fetch(self, from_city")
    end = src.index("    # ---------- 往返 ----------", start)
    body = src[start:end]
    # 允许带参数（`device_lock(owner=self.name)`，2026-11-04 起）；不变量不变
    assert re.search(r"with\s+rt\.device_lock\([^)]*\)\s*:", body)
    # 锁外不得再出现 prepare_device（缩进 8 空格的顶层调用）
    assert "\n        self.prepare_device(dev)" not in body
