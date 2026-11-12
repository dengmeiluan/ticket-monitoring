# -*- coding: utf-8 -*-
"""r999：航线走势的当前航线选中态与检索 chip/mtab 同为软蓝底品牌蓝字。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_scopes_trend_chip_selection():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#montab-trend .frow .chip.on{background:var(--r-blue-soft)!important" in src
    assert "color:var(--r-blue)!important" in src[src.index(
        "#montab-trend .frow .chip.on"):][:200]


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise RuntimeError("demo server did not start")


def test_rendered_trend_selection_is_soft_blue():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 390, "height": 900})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('mon');showMonTab('trend')}")
                pg.wait_for_timeout(1400)
                d = pg.evaluate(r"""()=>{
                  const c=document.querySelector('#montab-trend .frow .chip.on');
                  if(!c)return {err:'no chip'};
                  const cs=getComputedStyle(c);
                  return {bg:cs.backgroundColor,c:cs.color,fw:cs.fontWeight,
                    h:+c.getBoundingClientRect().height.toFixed(0),
                    overflow:document.documentElement.scrollWidth
                      -document.documentElement.clientWidth};}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    assert not d.get("err"), d
    assert d["bg"] == "rgb(237, 244, 255)", d
    assert d["c"] == "rgb(26, 99, 216)", d
    assert d["fw"] == "600", d
    assert d["h"] <= 32, d
    assert d["overflow"] <= 0, d
