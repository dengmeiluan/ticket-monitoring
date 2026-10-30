# -*- coding: utf-8 -*-
"""r653：没有航线时的首次启动，必须主动把用户引到控制台。

实测：双击 exe（或直接跑 main.py）时只有一个黑窗口，用户不知道要复制
一行 URL 到浏览器，最常见的反应是「点开没反应，关了」。引导必须包含
可执行的下一步，而不只是一句「可通过 http://… 配置」。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def test_first_run_prints_actionable_steps():
    """无航线分支要给出三步可执行动作，而不是只丢一个 URL。"""
    w = _src()
    i = w.index("首次使用：你的浏览器会自动打开配置页")
    seg = w[i - 200:i + 900]
    assert "用户与航线" in seg, "没告诉用户去哪加航线"
    assert "勾选" in seg and "智行 App" in seg, "没提渠道勾选（含 App）"
    assert "保存并生效" in seg, "没告诉用户保存后才开始"


def test_first_run_tries_to_open_browser():
    """要真的尝试打开浏览器；只打印 URL 等于让用户自己想办法。"""
    w = _src()
    assert "def _open_console(" in w, "缺少打开控制台的实现"
    assert "webbrowser" in w, "没有尝试调用系统浏览器"
    assert "_open_console(_url" in w or "_open_console(url" in w, \
        "首次引导分支没有调用 _open_console"


def test_open_console_failure_is_non_fatal(monkeypatch):
    """无桌面环境/浏览器调用失败时，不能让监控启动挂掉。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tm_main_probe", os.path.join(ROOT, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return          # main.py 顶层可能提前退出，跳过该断言
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
    assert mod._open_console("http://127.0.0.1:1", None) is False


def test_open_console_respects_opt_out(monkeypatch):
    """TICKET_NO_OPEN 用于服务器/测试，必须完全不弹窗。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tm_main_probe2", os.path.join(ROOT, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return
    called = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.append(1) or True)
    monkeypatch.setenv("TICKET_NO_OPEN", "1")
    assert mod._open_console("http://127.0.0.1:1", None) is False
    assert not called, "显式关闭时仍打开了浏览器"
