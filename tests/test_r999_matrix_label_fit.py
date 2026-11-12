# -*- coding: utf-8 -*-
"""r999：390 矩阵卡片的 5 列渠道标签不得被 ellipsis 截断。
「去哪儿 App」实测文字 51px、可用 45.6px（16px 图标再占位），
窄档隐去卡内重复图标，把整格让给全名。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_matrix_label_rule():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#searchview .srx-mxcard .pn img.bic{display:none!important}" in src
    assert "「去哪儿 App」" in src


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


def test_rendered_matrix_labels_not_clipped():
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
                pg.evaluate("()=>{switchView('search');srxToggleView()}")
                pg.wait_for_timeout(700)
                d = pg.evaluate(r"""()=>{
                  const cards=[...document.querySelectorAll('#searchview .srx-mxcard')];
                  const labels=[...document.querySelectorAll('#searchview .srx-mxcard .pn i')];
                  const clipped=labels.filter(e=>e.scrollWidth>e.clientWidth+1)
                    .map(e=>e.textContent);
                  const icons=[...document.querySelectorAll('#searchview .srx-mxcard .pn img.bic')]
                    .filter(e=>getComputedStyle(e).display!=='none').length;
                  return {cards:cards.length,labels:labels.length,clipped:clipped,
                    visibleIcons:icons,
                    uniq:[...new Set(labels.map(e=>e.textContent))],
                    overflow:document.documentElement.scrollWidth
                      -document.documentElement.clientWidth};}""")
                assert d["cards"] >= 8, d
                assert d["labels"] >= 80, d
                assert d["clipped"] == [], d
                # 2026-11-07：渠道图标是全表面统一要求；矩阵视图每格都要有官方图标。
                assert d["visibleIcons"] >= d["labels"], d
                assert "去哪儿 App" in d["uniq"], d
                assert d["overflow"] <= 0, d
                pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
