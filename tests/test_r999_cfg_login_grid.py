# -*- coding: utf-8 -*-
"""r999：配置页渠道登录桌面两列（5+5），不再单列 10 行、右侧全空。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_two_column_login_grid():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#loginRows .lggrid{grid-template-columns:repeat(2,minmax(0,1fr))!important" in src


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


def test_rendered_login_grid_desktop_two_columns_mobile_one():
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
                    pg = b.new_page(viewport={"width": w, "height": 900})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>switchView('cfg')")
                    # 登录槽位由 /api 异步渲染；固定 1200ms 在并发门禁下会量到 null（gate13 实测）
                    try:
                        pg.wait_for_function(
                            "()=>{const l=document.querySelector('#loginRows .lggrid');"
                            "if(!l)return false;const r=l.getBoundingClientRect();"
                            "return r.width>1&&r.height>1&&l.children.length>=10;}",
                            timeout=45000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(200)
                    out[w] = pg.evaluate(r"""()=>{
                      const list=document.querySelector('#loginRows .lggrid');
                      const rows=[...list.children];
                      const clipped=rows.filter(r=>{
                        const s=r.querySelector('.lgslots');
                        return s && (s.scrollWidth>s.clientWidth+1 ||
                                     s.scrollHeight>s.clientHeight+1);
                      }).length;
                      return {cols:getComputedStyle(list).gridTemplateColumns,
                        n:rows.length,
                        hs:rows.map(r=>+r.getBoundingClientRect().height.toFixed(0)),
                        clipped,
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
    assert len(d["cols"].split()) == 2, d
    assert d["n"] >= 10, d
    assert max(d["hs"]) <= 72, d
    assert d["clipped"] == 0, d
    assert d["overflow"] <= 0, d
    assert len(out[390]["cols"].split()) == 1, out[390]
