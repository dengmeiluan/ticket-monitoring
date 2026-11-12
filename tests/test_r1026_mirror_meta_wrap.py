# -*- coding: utf-8 -*-
"""r1026：原页镜像窄档的班次元信息不得用省略号藏日期/+1。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_mirror_meta_allows_two_lines():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index("r1026：原页镜像 390 的班次元信息")
    block = src[i:i + 700]
    assert "#searchview .srx-mrow .m span{white-space:normal!important" in block
    assert "word-break:keep-all!important" in block
    assert "overflow-wrap:normal!important" in block
    assert "text-overflow:clip!important" in block


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_rendered_mirror_meta_not_clipped():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            try:
                for width in (320, 390):
                    pg = br.new_page(viewport={"width": width, "height": 1200})
                    pg.goto(base + "/", wait_until="domcontentloaded")
                    pg.wait_for_timeout(1900)
                    pg.evaluate("switchView('search')")
                    pg.wait_for_timeout(900)
                    pg.evaluate("()=>srxToggleView()")
                    pg.wait_for_timeout(300)
                    pg.evaluate("()=>srxToggleView()")
                    pg.wait_for_timeout(300)
                    pg.locator("#searchview [data-mtab=mirror]").click()
                    pg.wait_for_timeout(700)
                    rows = pg.evaluate("""()=>{
                      const rows=[...document.querySelectorAll('#searchview .srx-mrow')].slice(0,10);
                      return rows.map(r=>{const s=r.querySelector('.m span');
                        return {sw:s?s.scrollWidth:0,cw:s?s.clientWidth:0,
                                h:+r.getBoundingClientRect().height.toFixed(1),
                                txt:s?s.innerText:''};});
                    }""")
                    assert rows, width
                    for r in rows:
                        assert r["sw"] <= r["cw"] + 1, (width, "镜像元信息被裁", r)
                        assert r["txt"].strip(), (width, r)
                        # 390 档最多两行 10px×1.35 ≈ 27px；320 档优先完整显示
                        # （不省略、不裁字），允许最多 4 行元信息 ≈ 96px。
                        assert r["h"] <= (96 if width == 320 else 80), (
                            width, "镜像行被撑过高", r)
                    pg.close()
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
