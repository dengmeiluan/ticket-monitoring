# -*- coding: utf-8 -*-
"""r999：特价雷达 390 元信息换行时，末尾「/」不再单独吊在行尾；
「覆盖 N/N 特价源」固定为整行第二行。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_specials_meta_rules():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#spMonSum .sep:nth-last-child(2){display:none!important}" in src
    assert "#spMonSum>span:last-child{flex:1 1 100%!important}" in src


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


def test_rendered_specials_meta_wrap():
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
                    pg.evaluate("()=>{switchView('mon');showMonTab('specials')}")
                    # 汇总条由数据异步渲染；固定 1800ms 在并发门禁下会量到 undefined（gate8 实测）
                    try:
                        pg.wait_for_function(
                            "()=>{const s=document.getElementById('spMonSum');"
                            "if(!s)return false;const k=[...s.children];"
                            "return k.length>=2&&s.getBoundingClientRect().width>1;}",
                            timeout=45000)
                    except Exception:
                        pass
                    pg.wait_for_timeout(200)
                    d = pg.evaluate(r"""()=>{
                      const s=document.getElementById('spMonSum');
                      if(!s)return {err:'no sum'};
                      const kids=[...s.children];
                      const last=kids[kids.length-1];
                      const sep=kids[kids.length-2];
                      const R=e=>{const r=e.getBoundingClientRect();
                        return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),
                          w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
                      return {n:kids.length,sum:R(s),last:R(last),
                        lastTxt:last.textContent.trim(),
                        sepDisp:getComputedStyle(sep).display,
                        sepCls:sep.className,
                        first:{y:+kids[0].getBoundingClientRect().y.toFixed(1),
                          x:+kids[0].getBoundingClientRect().x.toFixed(1)},
                        overflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth};}""")
                    assert not d.get("err"), (width, d)
                    assert d["lastTxt"].startswith("覆盖"), (width, d)
                    assert d["overflow"] <= 0, (width, d)
                    if narrow:
                        assert d["sepDisp"] == "none", d
                        assert d["last"]["y"] > d["first"]["y"] + 10, d
                        assert abs(d["last"]["x"] - d["sum"]["x"]) <= 1, d
                        assert d["sum"]["h"] <= 56, d
                    else:
                        assert d["sepDisp"] != "none", d
                        assert abs(d["last"]["y"] - d["first"]["y"]) <= 3, d
                        assert d["sum"]["h"] <= 30, d
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
