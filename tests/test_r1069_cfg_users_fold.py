# -*- coding: utf-8 -*-
"""r1069：配置·用户与航线：窄档默认只开首组 A，其余分组收在标题下。"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="配置分组折叠依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1069_")
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
  const panel = document.getElementById('panel-users');
  const gs = [...document.querySelectorAll('#cfgform .grouplab[data-sec]')];
  if (!gs.length) return {exists: false};
  return {exists: true,
    panelH: Math.round(panel.getBoundingClientRect().height),
    groups: gs.map((g, i) => {
      const n = g.nextElementSibling;
      const r = n ? n.getBoundingClientRect() : {height: 0};
      return {i, t: (g.textContent || '').trim().slice(0, 12),
              aria: g.getAttribute('aria-expanded'),
              next: n ? n.className : '', nh: Math.round(r.height)};
    }),
    pageOver: document.documentElement.scrollWidth - innerWidth};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1400)
    pg.evaluate("()=>{switchView('cfg');showCfgPanel('users')}")
    pg.wait_for_timeout(2000)


def test_phone_users_only_first_group_open(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        _open(pg)
        d = pg.evaluate(SNAP)
        assert d.get("exists"), "用户与航线分组未渲染"
        assert len(d["groups"]) >= 5, d
        assert d["groups"][0]["aria"] == "true" and d["groups"][0]["nh"] > 50, d
        folded = [x for x in d["groups"][1:] if x["aria"] == "false"]
        assert len(folded) >= 4, d
        assert d["panelH"] < 3200, "390 用户与航线仍 %spx" % d["panelH"]
        assert d["pageOver"] <= 1, d
        # 点第二组标题：同坐标换态、正文向下出现
        r0 = pg.evaluate("""()=>{const g=document.querySelectorAll('#cfgform .grouplab[data-sec]')[1];
          const r=g.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top+scrollY),Math.round(r.width),g.getAttribute('aria-expanded')]}""")
        pg.evaluate("()=>document.querySelectorAll('#cfgform .grouplab[data-sec]')[1].click()")
        pg.wait_for_timeout(500)
        d2 = pg.evaluate(SNAP)
        r1 = pg.evaluate("""()=>{const g=document.querySelectorAll('#cfgform .grouplab[data-sec]')[1];
          const r=g.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top+scrollY),Math.round(r.width),g.getAttribute('aria-expanded')]}""")
        assert r1[:3] == r0[:3], "展开时分组头位移：%s -> %s" % (r0, r1)
        assert r1[3] == "true", r1
        assert d2["groups"][1]["nh"] > 0, d2
        b.close()


def test_desktop_users_all_groups_open(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg)
        d = pg.evaluate(SNAP)
        assert all(x["aria"] == "true" for x in d["groups"]), d
        assert d["pageOver"] <= 1, d
        b.close()
