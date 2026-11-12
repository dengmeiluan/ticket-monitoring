# -*- coding: utf-8 -*-
"""r1065：概览用户卡窄档默认只露前 2 个日期，卡头触发、展开向下。

390 原 5 个日期 = 2073px，关注航线/关注航班被推到两三屏外。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="概览日期裁量依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1065_")
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
  const card = [...document.querySelectorAll('#montab-overview .ucard')]
    .find(c => (c.textContent || '').includes('演示用户'));
  if (!card) return {exists: false};
  const btn = card.querySelector('.udays-more');
  const days = [...card.querySelectorAll('.ukpis>.dgroup')];
  const vis = days.filter(d => d.getBoundingClientRect().height > 1);
  const r = btn ? btn.getBoundingClientRect() : null;
  return {
    exists: true, n: days.length, vis: vis.length,
    cardH: Math.round(card.getBoundingClientRect().height),
    btn: btn ? {d: getComputedStyle(btn).display,
                t: (btn.textContent || '').trim(),
                aria: btn.getAttribute('aria-expanded'),
                L: Math.round(r.left), T: Math.round(r.top + scrollY),
                W: Math.round(r.width)} : null,
    pageOver: document.documentElement.scrollWidth - innerWidth,
  };
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>{switchView('mon');showMonTab('overview')}")
    pg.wait_for_timeout(1600)


def test_phone_dates_capped_and_toggle_keeps_position(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        _open(pg)
        a = pg.evaluate(SNAP)
        assert a.get("exists"), "概览用户卡未渲染"
        assert a["n"] >= 3, a
        assert a["vis"] == 2, "390 默认应只露前 2 个日期：%s" % a
        assert a["btn"] and a["btn"]["d"] != "none", a
        assert "全部日期" in a["btn"]["t"] and a["btn"]["aria"] == "false", a
        assert a["cardH"] <= 1000, "390 用户卡仍 %spx" % a["cardH"]
        assert a["pageOver"] <= 1, a
        pg.evaluate("()=>document.querySelector('#montab-overview .udays-more').click()")
        pg.wait_for_timeout(500)
        o = pg.evaluate(SNAP)
        assert o["vis"] == o["n"], o
        assert "收起日期" in o["btn"]["t"] and o["btn"]["aria"] == "true", o
        assert (o["btn"]["L"], o["btn"]["T"], o["btn"]["W"]) == \
               (a["btn"]["L"], a["btn"]["T"], a["btn"]["W"]), \
            "展开时触发钮位移：%s -> %s" % (a["btn"], o["btn"])
        assert o["pageOver"] <= 1, o
        pg.evaluate("()=>document.querySelector('#montab-overview .udays-more').click()")
        pg.wait_for_timeout(400)
        c = pg.evaluate(SNAP)
        assert c["vis"] == 2 and "全部日期" in c["btn"]["t"], c
        b.close()


def test_desktop_shows_all_days_and_no_toggle(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg)
        d = pg.evaluate(SNAP)
        assert d["vis"] == d["n"], d
        assert d["btn"]["d"] == "none", d
        assert d["pageOver"] <= 1, d
        b.close()
