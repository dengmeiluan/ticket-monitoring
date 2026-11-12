# -*- coding: utf-8 -*-
"""r999：用户与航线工具栏 390 换行后，范围/状态之间的竖线不再吊在行尾。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_users_toolbar_separator_rule():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#cfgview .cfgtoolbar .cbsp{display:none!important}" in src


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


def test_rendered_users_toolbar_separator():
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
                for width, narrow in ((390, True), (1512, False)):
                    pg = b.new_page(viewport={"width": width, "height": 950})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('cfg');showCfgPanel('users')}")
                    pg.wait_for_timeout(800)
                    # 并行负载下用户面板可能还没渲染出工具条；固定 800ms
                    # 会让 seg/st 为 null，读取 rect 抛 TypeError。
                    pg.wait_for_function(
                        "()=>{const s=document.querySelector('#cfgScopeBar .cfgseg');"
                        "const t=document.getElementById('cfgStatusSel');"
                        "return !!(s&&t&&t.getBoundingClientRect().height>1)}",
                        timeout=12000)
                    d = pg.evaluate(r"""()=>{
                      const sep=document.querySelector('#cfgScopeBar .cbsp');
                      const seg=document.querySelector('#cfgScopeBar .cfgseg');
                      const st=document.getElementById('cfgStatusSel');
                      const R=e=>{const r=e.getBoundingClientRect();
                        return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),
                          w:+r.width.toFixed(1),h:+r.height.toFixed(1),
                          bottom:+r.bottom.toFixed(1)}};
                      return {sep:sep?getComputedStyle(sep).display:null,
                        sepBox:sep?R(sep):null,seg:R(seg),st:R(st),
                        stH:+st.getBoundingClientRect().height.toFixed(1),
                        overflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth};}""")
                    assert d["sep"] is not None, (width, d)
                    assert d["overflow"] <= 0, (width, d)
                    assert d["stH"] == 30, (width, d)
                    if narrow:
                        assert d["sep"] == "none", d
                        assert d["st"]["y"] > d["seg"]["bottom"] + 5, d
                    else:
                        assert d["sep"] != "none", d
                        assert abs(d["st"]["y"] - d["seg"]["y"]) <= 4, d
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
