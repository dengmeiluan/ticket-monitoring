# -*- coding: utf-8 -*-
"""r999：桌面概览每组直飞/中转 KPI 从竖排五行改为两列，减少右半列空白。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_scopes_overview_kpi_grid():
    """概览每组 KPI 仍是「两列网格、减少右半空白」，但实现已从
    `grid-template-areas` 换成**显式行列定位 + subgrid**（r1400 前后重构）。

    断言的本意是「桌面上 KPI 用两列排布，数值/说明在右列」，不是某个具体写法，
    所以这里钉列定义与四块的显式列位，别钉死 areas 字符串。
    """
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#montab-overview .dgroup .kpi{display:grid;" in src
    i = src.index("#montab-overview .dgroup .kpi{display:grid;")
    rule = src[i:i + 460]
    assert "grid-template-columns:minmax(150px,230px) minmax(0,1fr)" in rule, rule
    # 四块各就各位：标签整行、数值与说明分左右列
    assert ".kpi .lab{grid-column:1/-1" in src
    assert ".kpi .num{grid-column:1;grid-row:2}" in src
    assert ".kpi .muted:not(.fb){grid-column:2;grid-row:2" in src


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


def test_rendered_overview_kpi_is_two_column_on_desktop():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    out = {}
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for w in (1512, 390):
                    pg = b.new_page(viewport={"width": w, "height": 1000})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('mon');showMonTab('overview')}")
                    pg.wait_for_timeout(1500)
                    out[w] = pg.evaluate(r"""()=>{
                      const g=document.querySelector('#montab-overview .dgroup .grid');
                      const k=g.querySelector('.kpi');
                      const R=e=>e.getBoundingClientRect();
                      const by={}; for(const e of k.children)
                        by[e.className.split(' ').filter(Boolean).pop()||'x']=R(e);
                      return {disp:getComputedStyle(k).display,
                        kpiH:+R(k).height.toFixed(0),groupH:+R(g).height.toFixed(0),
                        numR:+by.num.right.toFixed(0),noteL:+by.muted?.left?.toFixed?.(0)||0,
                        overflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth};}""")
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    d = out[1512]
    assert d["disp"] == "grid", d
    assert d["kpiH"] <= 120, d
    assert d["overflow"] <= 0, d
    assert out[390]["disp"] == "block", out[390]
    assert out[390]["kpiH"] <= 140, out[390]
