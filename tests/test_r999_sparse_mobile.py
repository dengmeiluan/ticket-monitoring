# -*- coding: utf-8 -*-
"""r999：390 特价雷达 sparse 空态从 168 再压到 128，减少大片灰底空白。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_mobile_sparse_override():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert ".spmon-chartwrap.is-sparse{min-height:128px!important;height:128px!important}" in src
    assert ".spmon-chartwrap.is-sparse canvas{height:110px!important}" in src


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


def test_rendered_mobile_sparse_chart_is_128():
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
                pg.evaluate("()=>{switchView('mon');showMonTab('specials')}")
                pg.wait_for_timeout(1500)
                d = pg.evaluate(r"""()=>{
                  const w=document.querySelector('.spmon-chartwrap');
                  if(!w)return {err:'no wrap'};
                  w.classList.add('is-sparse');
                  const c=w.querySelector('canvas');
                  const em=w.querySelector('.spmon-kempty');
                  return {h:+w.getBoundingClientRect().height.toFixed(0),
                    ch:w.clientHeight,sh:w.scrollHeight,
                    canvasH:+c.getBoundingClientRect().height.toFixed(0),
                    emSh:em?em.scrollHeight:0,emCh:em?em.clientHeight:0,
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
    assert d["h"] == 128, d
    assert d["canvasH"] == 110, d
    assert d["emSh"] <= d["emCh"] + 1, ("空态文字被裁", d)
    assert d["overflow"] <= 0, d
