# -*- coding: utf-8 -*-
"""概览卡进入完整走势：用户显式选过的范围必须保留，默认才落 7 天。

概览迷你曲线固定 7 天；monRouteOpen 曾无条件 st.r='7d'，用户在走势页
选 90 天后点概览「查看关注航线走势」会被重置。此钉守住：
  1) 显式范围（90d）跨概览→完整走势保留；
  2) 无显式选择（启动默认 48h）时，概览入口仍按卡片语义落 7d。
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="行为钉依赖 playwright")
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    logf = tempfile.TemporaryFile("w+", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
    if not _wait_up(proc):
        proc.kill()
        logf.seek(0)
        pytest.fail("demo 服务未起来：%s" % logf.read()[-600:])
    yield proc
    proc.kill()
    logf.close()


def _open_mon_tab(pg, tab):
    pg.evaluate("t=>{switchView('mon');showMonTab(t)}", tab)
    pg.wait_for_timeout(600)


def test_overview_entry_preserves_explicit_range(srv):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1360, "height": 900})
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users&&S.users.length")
        pg.wait_for_timeout(800)
        _open_mon_tab(pg, "trend")
        pg.click("#rng90")
        pg.wait_for_timeout(500)
        _open_mon_tab(pg, "overview")
        btn = pg.locator("[data-mroute]").first
        if not btn.count():
            pytest.skip("demo 无关注航线卡，无法验证概览入口")
        btn.click()
        pg.wait_for_timeout(900)
        state = pg.evaluate("""()=>({
            range:curRoute().range,
            pressed:document.getElementById('rng90').getAttribute('aria-pressed'),
            cls:document.getElementById('rng90').className,
            title:document.getElementById('chartTitle').textContent,
            tab:document.querySelector('#montabs .mtab.on').dataset.t})""")
        assert state["tab"] == "trend"
        assert state["range"] == "90d", state
        assert state["pressed"] == "true" and "on" in state["cls"], state
        assert "90天" in state["title"], state
        b.close()


def test_overview_entry_defaults_to_7d_without_explicit_range(srv):
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1360, "height": 900})
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users&&S.users.length")
        pg.wait_for_timeout(800)
        _open_mon_tab(pg, "overview")
        btn = pg.locator("[data-mroute]").first
        if not btn.count():
            pytest.skip("demo 无关注航线卡，无法验证概览入口")
        btn.click()
        pg.wait_for_timeout(800)
        state = pg.evaluate("""()=>({range:curRoute().range,
            pressed:document.getElementById('rng7d').getAttribute('aria-pressed'),
            title:document.getElementById('chartTitle').textContent})""")
        assert state["range"] == "7d", state
        assert state["pressed"] == "true", state
        assert "7天" in state["title"], state
        b.close()
