# -*- coding: utf-8 -*-
"""r996：390 概览用户卡的路由串必须整行显示，不被动作区压掉日期尾数。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_uses_two_row_mobile_header():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'grid-template-areas:"name acts" "routes routes"' in src
    assert "#montab-overview .uhead>.uroutes" in src


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


def test_rendered_overview_route_is_not_clipped():
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
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('mon')}")
                pg.wait_for_timeout(1600)
                out = pg.evaluate(r"""()=>{
                  const u=document.querySelector('#montab-overview .uroutes');
                  const h=document.querySelector('#montab-overview .uhead');
                  if(!u)return {err:'no routes'};
                  const r=e=>{const b=e.getBoundingClientRect();
                    return {l:+b.left.toFixed(1),r:+b.right.toFixed(1),
                            w:+b.width.toFixed(1)};};
                  const ur=r(u), hr=r(h);
                  const nw=[...u.querySelectorAll('.nw')].map(r);
                  return {ur,hr,sw:u.scrollWidth,cw:u.clientWidth,
                    lastRight:nw.length?nw[nw.length-1].r:0,
                    display:getComputedStyle(h).display,
                    ov:document.documentElement.scrollWidth
                      -document.documentElement.clientWidth};}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    assert not out.get("err"), out
    assert out["display"] == "grid", out
    assert out["ur"]["w"] >= 250, "路由串没有拿到整行宽度：%s" % out
    assert out["sw"] <= out["cw"] + 1, "路由串仍横向溢出：%s" % out
    assert out["lastRight"] <= out["ur"]["r"] + 1, out
    assert out["ov"] <= 0, out
