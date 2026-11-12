# -*- coding: utf-8 -*-
"""r1051：能力矩阵窄档自身滚动 + 表头行冻结。

用户实报「滚动的东西能滚到冻结行/列里」：390 矩阵原随页面纵向滚动，
渠道表头滚出屏后只剩一排勾叉；现在矩阵成为独立滚动区，纵向滚时
表头行固定在顶部，横向滚时首列仍冻结，且表头底色不透明不露字。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_matrix_scroll_and_sticky_header():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#cfgDimMatrix .dimwrap{max-height:min(50vh,520px);overflow:auto!important" in src
    assert "#cfgDimMatrix .dimtbl thead th{position:sticky;top:0;z-index:3;" in src
    assert "background:var(--card)!important" in src


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


def test_rendered_matrix_freezes_header_on_vertical_scroll():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    srv, base = _boot()
    out = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for w in (390, 1512):
                    pg = b.new_page(viewport={"width": w, "height": 900})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('cfg');showCfgPanel('login')}")
                    # 矩阵由 /api 异步渲染，固定 2200ms 在并发门禁下会量到 missing（gate7 实测）
                    try:
                        pg.wait_for_function(
                            "()=>{const w=document.querySelector('#cfgDimMatrix .dimwrap');"
                            "const t=document.querySelector('#cfgDimMatrix .dimtbl thead th');"
                            "if(!w||!t)return false;"
                            "const r=w.getBoundingClientRect(),h=t.getBoundingClientRect();"
                            "return r.width>1&&r.height>1&&h.width>1;}",
                            timeout=30000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(200)
                    out[w] = pg.evaluate(r"""()=>{
                      const wrap=document.querySelector('#cfgDimMatrix .dimwrap');
                      const th=document.querySelector('#cfgDimMatrix .dimtbl thead th');
                      if(!wrap||!th)return {err:'missing'};
                      const before=th.getBoundingClientRect().top;
                      wrap.scrollTop=180;
                      const after=th.getBoundingClientRect().top;
                      const cs=getComputedStyle(th);
                      return {sh:wrap.scrollHeight,ch:wrap.clientHeight,
                        before:+before.toFixed(1),after:+after.toFixed(1),
                        bg:cs.backgroundColor,pos:cs.position,
                        pageOverflow:document.documentElement.scrollWidth-innerWidth};}""")
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    d = out[390]
    assert not d.get("err"), d
    assert d["sh"] > d["ch"] + 20, ("390 矩阵没有纵向内滚", d)
    assert abs(d["after"] - d["before"]) <= 1, ("表头行未冻结", d)
    assert d["pos"] == "sticky" and d["bg"] == "rgb(255, 255, 255)", d
    assert d["pageOverflow"] <= 0, d
    desk = out[1512]
    assert desk["sh"] == desk["ch"], ("桌面矩阵不该出现内滚", desk)
