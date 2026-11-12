# -*- coding: utf-8 -*-
"""r999：390 航线走势的航线 chip 自然换行，不再横向裁断第二条。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_trend_routes_wrap_rule():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#chartcard #chartRoutes{flex-wrap:wrap!important" in src
    assert "overflow-x:visible!important" in src[src.index(
        "#chartcard #chartRoutes{flex-wrap:wrap!important"):][:260]


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


def test_rendered_trend_routes_wrap():
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
                    pg.evaluate("()=>{switchView('mon');showMonTab('trend')}")
                    pg.wait_for_timeout(1600)
                    d = pg.evaluate(r"""()=>{
                      const r=document.getElementById('chartRoutes');
                      if(!r)return {err:'no routes'};
                      const ch=[...r.querySelectorAll('.chip')];
                      const rr=r.getBoundingClientRect();
                      const R=e=>{const x=e.getBoundingClientRect();
                        return {x:+x.x.toFixed(1),y:+x.y.toFixed(1),
                          w:+x.width.toFixed(1),h:+x.height.toFixed(1),right:+x.right.toFixed(1)}};
                      return {disp:getComputedStyle(r).display,
                        wrap:getComputedStyle(r).flexWrap,
                        sw:r.scrollWidth,cw:r.clientWidth,
                        h:+rr.height.toFixed(1),right:+rr.right.toFixed(1),
                        left:+rr.left.toFixed(1),
                        n:ch.length,chips:ch.map(R),
                        overflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth,
                        out:ch.filter(e=>e.getBoundingClientRect().right
                          >rr.right+1).map(e=>e.textContent.trim())};}""")
                    assert not d.get("err"), (width, d)
                    assert d["n"] == 6, (width, d)
                    assert d["overflow"] <= 0, (width, d)
                    if narrow:
                        assert d["wrap"] == "wrap", d
                        assert d["sw"] <= d["cw"] + 1, d
                        assert d["out"] == [], d
                        assert d["h"] > 32, d
                        # r1007：片阵由「整条 324px 满宽清单」改成按内容宽
                        # 自然换行（每行 2 片、3 行收完）。约束改为「每行首片
                        # 都贴容器左缘 + 不超出容器 + 片高一致」，不再要求所有
                        # 片同一个 x（那会把 6 条航线铺成 6 个满宽行）。
                        assert all(c["w"] < d["cw"] - 10 for c in d["chips"]), d
                        rows = {}
                        for c in d["chips"]:
                            rows.setdefault(round(c["y"]), []).append(c)
                        assert 2 <= len(rows) <= 4, d
                        for row in rows.values():
                            assert abs(min(c["x"] for c in row) - d["left"]) <= 1, (row, d)
                        assert len({round(c["h"]) for c in d["chips"]}) == 1, d
                        assert len({round(c["w"]) for c in d["chips"]}) >= 2, d
                    else:
                        assert d["sw"] <= d["cw"] + 1, d
                        assert d["out"] == [], d
                        assert d["h"] <= 34, d
                        assert len({round(c["y"]) for c in d["chips"]}) == 1, d
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
