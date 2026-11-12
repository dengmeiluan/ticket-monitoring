# -*- coding: utf-8 -*-
"""r999：矩阵视图下不再显示列表的「加载更多 N 行」按钮。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_matrix_more_guard():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "const n=SRX.view==='matrix'?0:Math.max(0,rows.length-srxShownRows(rows).length)" in src


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


def test_rendered_matrix_hides_load_more():
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
                pg.evaluate("()=>switchView('search')")
                pg.wait_for_timeout(900)
                pg.evaluate("""()=>{const b=[...document.querySelectorAll('#searchview button')]
                  .find(x=>x.offsetParent&&(x.textContent||'').trim()==='矩阵');if(b)b.click()}""")
                pg.wait_for_timeout(600)
                d = pg.evaluate("""()=>{
                  const more=document.getElementById('srxMoreRows');
                  const t=document.getElementById('srxListTitle');
                  return {view:SRX.view, more:getComputedStyle(more).display,
                    title:t.textContent,
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
    assert d["view"] == "matrix", d
    assert d["more"] == "none", d
    assert "矩阵" in d["title"], d
    assert d["overflow"] <= 0, d
