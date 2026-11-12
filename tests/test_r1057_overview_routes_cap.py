# -*- coding: utf-8 -*-
"""r1057：概览「关注航线」窄档默认只露前 2 条，不再 6 张卡全铺开。

用户否定「穷举默认铺开」。入口放卡头（内容在按钮下方，触发器不随展开移动），
展开/收起同词同长：「展开全部航线」↔「收起全部航线」。桌面 3 列网格不裁。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="概览裁量依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1057_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


SNAP = """(() => {
  const box=document.getElementById('monRouteList');
  const cards=[...box.querySelectorAll('article.monroute')];
  const btn=document.getElementById('monRouteMore');
  const br=btn?btn.getBoundingClientRect():null;
  return {n:cards.length,
    visible:cards.filter(c=>c.getBoundingClientRect().height>1).length,
    btnDisp:btn?getComputedStyle(btn).display:'none',
    btnHidden:!!(btn&&btn.hidden),
    txt:btn?(btn.textContent||'').trim():'',
    aria:btn?btn.getAttribute('aria-expanded'):null,
    box:br?[Math.round(br.left),Math.round(br.top+window.scrollY),Math.round(br.width)]:null,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg, w):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1600)
    pg.evaluate("()=>switchView('mon')")
    pg.wait_for_timeout(1200)


def test_overview_routes_cap_and_toggle_on_phone(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        _open(pg, 390)
        a = pg.evaluate(SNAP)
        assert a["n"] == 6, a
        assert a["visible"] == 2, "390 默认应只露前 2 条关注航线：%s" % a
        assert a["btnDisp"] != "none" and not a["btnHidden"], "展开按钮不可见：%s" % a
        assert a["txt"] == "展开全部航线" and a["aria"] == "false", a
        pg.click("#monRouteMore")
        pg.wait_for_timeout(350)
        b2 = pg.evaluate(SNAP)
        assert b2["visible"] == 6, "展开后未显示全部航线：%s" % b2
        assert b2["txt"] == "收起全部航线" and b2["aria"] == "true", b2
        assert b2["box"] == a["box"], "展开时按钮位置跳了：%s -> %s" % (a, b2)
        pg.click("#monRouteMore")
        pg.wait_for_timeout(350)
        c = pg.evaluate(SNAP)
        assert c["visible"] == 2 and c["txt"] == "展开全部航线" and c["aria"] == "false", c
        assert c["box"] == a["box"], "收起时按钮位置跳了：%s -> %s" % (a, c)
        assert not c["over"], c
        b.close()


def test_overview_routes_uncapped_on_desktop(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg, 1512)
        a = pg.evaluate(SNAP)
        assert a["visible"] == 6, "桌面不应裁航线卡：%s" % a
        assert a["btnDisp"] == "none", "桌面不该出现窄档展开钮：%s" % a
        assert not a["over"], a
        b.close()
