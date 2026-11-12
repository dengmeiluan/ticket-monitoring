# -*- coding: utf-8 -*-
"""r1068：配置·全局参数分区折叠：窄档默认只开首组，搜索临时全开。"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="配置分区折叠依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1068_")
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
  const root = document.getElementById('cfgglobals');
  const panel = document.getElementById('panel-globals');
  if (!root) return {exists: false};
  const secs = [...root.querySelectorAll('.subsec[data-cfgsec]')];
  const rows = secs.map(s => {
    const b = s.querySelector('.secfold');
    const grid = s.nextElementSibling;
    const r = grid ? grid.getBoundingClientRect() : {height: 0};
    return {t: (s.textContent || '').trim().slice(0, 12),
            folded: s.classList.contains('folded'),
            gridH: Math.round(r.height),
            btn: b ? b.textContent.trim() : null,
            btnDisp: b ? getComputedStyle(b).display : null,
            aria: b ? b.getAttribute('aria-expanded') : null};
  });
  return {exists: true, n: secs.length, rows,
          panelH: Math.round(panel.getBoundingClientRect().height),
          pageOver: document.documentElement.scrollWidth - innerWidth};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1400)
    pg.evaluate("()=>{switchView('cfg');showCfgPanel('globals')}")
    pg.wait_for_timeout(1800)


def test_phone_globals_only_first_section_open(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        _open(pg)
        d = pg.evaluate(SNAP)
        assert d.get("exists"), "全局参数未渲染"
        assert d["n"] == 7, d
        assert d["rows"][0]["folded"] is False and d["rows"][0]["gridH"] > 20, d
        assert all(x["folded"] for x in d["rows"][1:]), d
        assert all(x["gridH"] == 0 for x in d["rows"][1:]), d
        assert d["panelH"] < 1800, "390 全局参数仍 %spx" % d["panelH"]
        assert d["pageOver"] <= 1, d
        r0 = pg.evaluate("""()=>{const s=document.querySelectorAll('#cfgglobals .subsec[data-cfgsec]')[1];
          const b=s.querySelector('.secfold');const r=b.getBoundingClientRect();
          return [Math.round(r.left),Math.round(r.top+scrollY),Math.round(r.width),b.textContent.trim()]}""")
        pg.evaluate("()=>document.querySelectorAll('#cfgglobals .subsec[data-cfgsec]')[1].querySelector('.secfold').click()")
        pg.wait_for_timeout(400)
        d2 = pg.evaluate(SNAP)
        r1 = pg.evaluate("""()=>{const s=document.querySelectorAll('#cfgglobals .subsec[data-cfgsec]')[1];
          const b=s.querySelector('.secfold');const r=b.getBoundingClientRect();
          return [Math.round(r.left),Math.round(r.top+scrollY),Math.round(r.width),b.textContent.trim()]}""")
        assert d2["rows"][1]["folded"] is False and d2["rows"][1]["gridH"] > 20, d2
        assert r1[:3] == r0[:3], "展开时按钮位移：%s -> %s" % (r0, r1)
        assert "收起" in r1[3], r1
        b.close()


def test_phone_search_opens_folded_sections(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        _open(pg)
        pg.evaluate("()=>{document.getElementById('cfgSearch').value='指纹一致性';cfgFilter('指纹一致性')}")
        pg.wait_for_timeout(600)
        d = pg.evaluate("""()=>{const root=document.getElementById('cfgglobals');
          const secs=[...root.querySelectorAll('.subsec[data-cfgsec]')];
          const vis=e=>{const r=e.getBoundingClientRect();return r.height>1};
          const hit=[...root.querySelectorAll('.glcell')].filter(vis).map(c=>(c.textContent||'').trim().slice(0,20));
          return {qsearch:document.getElementById('cfgview').classList.contains('qsearch'),
            grids:secs.map(s=>{const g=s.nextElementSibling;return g?Math.round(g.getBoundingClientRect().height):0}),
            hits:hit, pageOver:document.documentElement.scrollWidth-innerWidth}}""")
        assert d["qsearch"] is True, d
        assert any("指纹一致性" in h for h in d["hits"]), d
        assert any(g > 20 for g in d["grids"]), d
        pg.evaluate("()=>cfgSearchClear()")
        pg.wait_for_timeout(500)
        e = pg.evaluate(SNAP)
        assert all(x["folded"] for x in e["rows"][1:]), e
        assert e["pageOver"] <= 1, e
        b.close()


def test_desktop_globals_all_open_and_no_buttons(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg)
        d = pg.evaluate(SNAP)
        assert all(not x["folded"] and x["gridH"] > 20 for x in d["rows"]), d
        assert all(x["btnDisp"] == "none" for x in d["rows"]), d
        assert d["pageOver"] <= 1, d
        b.close()
