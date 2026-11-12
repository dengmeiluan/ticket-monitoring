# -*- coding: utf-8 -*-
"""r730 内嵌登录画面能力补齐：返回 / 桌面 / 同窗切换渠道。

用户反馈「整体能力感觉比较有限」：弹窗里只有「输入文字 / 退格 / 已完成」，
登录时一旦 App 停在子页（比如验证码页、协议页）或卡在别处，就只能关掉
重来；要登另一个 App 也得关窗再找入口。

本轮补三件事（都走已有的 /api/app-login/key 与 create）：
  * 「返回」KEYCODE_BACK
  * 「桌面」KEYCODE_HOME
  * 切换条：同窗直接切到另一个 App 渠道（标题/画面/选中态一起换）

门禁分两层：
  1. 页面源码里确实渲染出这些控件（静态，快）；
  2. 真浏览器里点一遍，标题与选中态跟着换（渲染，慢但真实）。
第 2 层在 `_scratch/r730_render_applogin.py` 已跑过；这里把它固化成
可回归的断言（用项目自己的服务地址，没有就跳过）。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_modal_has_back_and_home_buttons():
    src = _src()
    assert "onclick=\"appLoginKey(\\'KEYCODE_BACK\\')\"" in src, (
        "内嵌登录没有「返回」按钮：App 停在子页时只能关窗重来")
    assert "onclick=\"appLoginKey(\\'KEYCODE_HOME\\')\"" in src, (
        "内嵌登录没有「桌面」按钮")


def test_modal_renders_channel_switch_bar():
    src = _src()
    assert "function appLoginSwitchHTML(" in src
    assert "function appLoginSwitch(" in src
    assert "appLoginSwitchHTML(plat)" in src, (
        "切换条没有被插进弹窗 HTML")


def test_switch_reopens_modal_for_target_plaform():
    """切渠道必须重开弹窗（标题/画面/选中态一起换），并先停帧轮询。"""
    src = _src()
    i = src.index("function appLoginSwitch(")
    body = src[i:i + 420]
    assert "appLoginStop()" in body, "切渠道前没停掉上一家的帧轮询"
    assert "appLoginOpen(plat)" in body, "切渠道没有重开弹窗"


def test_switch_bar_lists_every_app_channel():
    """切换项不能写死两家——从 APP_PLAT_NAME 派生，新增 App 自动出现。"""
    src = _src()
    i = src.index("function appLoginSwitchHTML(")
    body = src[i:i + 700]
    assert "APP_PLAT_NAME" in body, "切换项写死了渠道名，新增 App 不会出现"
    assert "Object.keys(M)" in body


def test_render_switch_bar_titles(monkeypatch):
    """真浏览器：点切换后标题与选中态都跟着换。

    不再依赖本机 8765 是否在跑：没有 BASE 时自己拉起 --demo 服务。
    旧写法在干净克隆/CI 里直接 skip，与「0 skipped」口径冲突。
    """
    import socket
    import subprocess
    import time
    import urllib.request

    base = os.environ.get("BASE") or ""
    srv = None
    if not base:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        base = "http://127.0.0.1:%d" % port
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        srv = subprocess.Popen(
            [sys.executable, "webui.py", "--demo", "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            srv.kill()
            pytest.fail("demo 服务未在期限内起来")
    try:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            pytest.skip("playwright 不可用")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(base + "/#config", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(3000)
            pg.evaluate("() => appLoginOpen('app_zhixing')")
            pg.wait_for_timeout(1500)
            t1 = pg.evaluate(
                "() => document.querySelector('#lgModal .lgmodal-h b').textContent")
            bars = pg.evaluate(
                "() => [...document.querySelectorAll('#lgModal .appsw button')]"
                ".map(b => b.textContent.trim())")
            pg.evaluate("() => appLoginSwitch('app_qunar')")
            pg.wait_for_timeout(1500)
            t2 = pg.evaluate(
                "() => document.querySelector('#lgModal .lgmodal-h b').textContent")
            on = pg.evaluate(
                "() => [...document.querySelectorAll('#lgModal .appsw button.on')]"
                ".map(b => b.textContent.trim())")
            b.close()
        assert "智行" in t1, t1
        assert len(bars) >= 2, bars
        assert "去哪儿" in t2, t2
        assert any("去哪儿" in t for t in on), on
    finally:
        if srv is not None:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except Exception:
                srv.kill()
