# -*- coding: utf-8 -*-
"""r999：用户与航线 390 动作条三颗按钮等宽、整行铺满，与范围/状态同左缘。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_users_actions_grid_rule():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#cfgview .cfgtoolbar-act{width:100%!important;display:grid!important" in src
    assert "grid-template-columns:repeat(3,minmax(0,1fr))!important" in src[src.index(
        "#cfgview .cfgtoolbar-act{width:100%!important"):][:300]
    assert "#cfgview .cfgtoolbar-act .btn2{width:100%!important" in src


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


def test_rendered_users_actions_equal_columns():
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
                pg = b.new_page(viewport={"width": 390, "height": 950})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('cfg');showCfgPanel('users')}")
                pg.wait_for_timeout(800)
                d = pg.evaluate(r"""()=>{
                  const act=document.querySelector('#cfgview .cfgtoolbar-act');
                  const bar=document.getElementById('cfgScopeBar');
                  const btns=[...act.querySelectorAll('.btn2')].map(b=>{
                    const r=b.getBoundingClientRect();
                    return {t:b.innerText.trim(),x:+r.x.toFixed(1),
                      w:+r.width.toFixed(1),h:+r.height.toFixed(1),
                      right:+r.right.toFixed(1)}});
                  const br=bar.getBoundingClientRect();
                  return {n:btns.length,btns:btns,
                    bar:{x:+br.x.toFixed(1),right:+br.right.toFixed(1)},
                    overflow:document.documentElement.scrollWidth
                      -document.documentElement.clientWidth};}""")
                assert d["n"] == 3, d
                assert d["overflow"] <= 0, d
                assert len({round(x["w"]) for x in d["btns"]}) == 1, d
                assert len({round(x["h"]) for x in d["btns"]}) == 1, d
                assert abs(d["btns"][0]["x"] - d["bar"]["x"]) <= 1, d
                assert abs(d["btns"][-1]["right"] - d["bar"]["right"]) <= 1, d
                assert all(b["h"] == 32 for b in d["btns"]), d
                pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
