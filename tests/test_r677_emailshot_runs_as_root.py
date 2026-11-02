# -*- coding: utf-8 -*-
r"""r677：容器（root）里邮件快照必须能真的起浏览器。

issue #10 评论实报「docker 下邮箱通知报错」。可证的一条差异：Chromium
在 root 下不带 `--no-sandbox` 会直接拒绝启动，而 `core/emailshot.py`
的 launch 一直没带（采集侧 `browser()` 一直带）。结果是邮件永远降级成
轻壳、日志每封都刷一条失败。

判据（注入假 playwright，捕获真实 launch 调用）：
① render_console_png 的 launch 带 --no-sandbox 与 --disable-dev-shm-usage；
② 端口探测失败时快速降级、根本不 launch（既有行为不被改坏）；
③ 截图成功路径真的返回 PNG 字节。

负控：去掉 args → ①红。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core.emailshot as emailshot


class _FakePage:
    def __init__(self):
        self.waits = []

    def goto(self, *a, **kw):
        return None

    def wait_for_function(self, *a, **kw):
        return None

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def screenshot(self, **kw):
        return b"\x89PNG\r\n\x1a\nfake"


class _FakeBrowser:
    def __init__(self, sink):
        self.sink = sink

    def new_page(self, **kw):
        self.sink["page_kw"] = kw
        return _FakePage()

    def close(self):
        self.sink["closed"] = True


class _FakeChromium:
    def __init__(self, sink):
        self.sink = sink

    def launch(self, **kw):
        self.sink["launch"] = kw
        return _FakeBrowser(self.sink)


class _FakePW:
    def __init__(self, sink):
        self.sink = sink
        self.chromium = _FakeChromium(sink)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, *a):
        self.lines.append(("info", a))

    def warning(self, *a):
        self.lines.append(("warning", a))


def _run(monkeypatch, reachable=True):
    sink = {}
    monkeypatch.setattr(emailshot, "_port_rejects", lambda url: not reachable)
    import playwright.sync_api as sa
    monkeypatch.setattr(sa, "sync_playwright", lambda: _FakePW(sink))
    log = _Log()
    png = emailshot.render_console_png("http://127.0.0.1:8765", log)
    return png, sink, log


def test_launch_args_allow_root_container(monkeypatch):
    png, sink, _log = _run(monkeypatch)
    assert png and png.startswith(b"\x89PNG")
    args = (sink.get("launch") or {}).get("args") or []
    assert "--no-sandbox" in args, (
        "root 容器里 Chromium 拒绝启动；邮件会永远降级轻壳（issue #10 同类）")
    assert "--disable-dev-shm-usage" in args, "小 /dev/shm 容器里会渲染崩溃"
    assert sink.get("closed") is True, "浏览器没有关闭，推送轮会漏进程"


def test_unreachable_port_degrades_without_launch(monkeypatch):
    png, sink, _log = _run(monkeypatch, reachable=False)
    assert png is None
    assert "launch" not in sink, "端口不通还去起浏览器，硬等超时拖慢推送"
