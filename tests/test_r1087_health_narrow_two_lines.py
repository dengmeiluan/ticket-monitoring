# -*- coding: utf-8 -*-
"""r1087：320 档渠道健康 24h 格带只剩 68px（24 格每格 ~2.8px，读不出也点不中）。

行改成两行：首行「渠道名 + 徽标」，次行 24h 格带吃满卡宽（~240–260px），
每格回到 ~9px；仍保持 r1058 的「默认只露 4 行」。390 保持 104|1fr|64 单行。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="健康 24h 格带依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1087_")
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
  const rg=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {L:Math.round(r.left),T:Math.round(r.top),R:Math.round(r.right),
      B:Math.round(r.bottom),W:Math.round(r.width),H:Math.round(r.height)}};
  const rows=[...document.querySelectorAll('#healthcard .hrow')]
    .filter(e=>e.checkVisibility()&&e.getBoundingClientRect().height>0);
  return {n:rows.length,
    over:document.documentElement.scrollWidth-innerWidth,
    rows:rows.slice(0,4).map(r=>({
      lab:rg(r.querySelector('.hlab')),grid:rg(r.querySelector('.hcells')),
      badge:rg(r.querySelector('.hbadge')),row:rg(r)}))};
})()"""


def _open_health(pg):
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1200)
    pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
    pg.wait_for_timeout(900)
    try:
        pg.wait_for_function(
            "()=>document.querySelectorAll('#healthcard .hrow').length>0",
            timeout=20000)
    except Exception:
        pass
    pg.evaluate("()=>{const c=document.getElementById('healthcard');"
                "if(c)c.scrollIntoView({block:'start'})}")
    pg.wait_for_timeout(300)


def test_health_grid_full_width_at_320(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 320, "height": 900},
                        is_mobile=True, has_touch=True)
        pg.goto(BASE + "/", wait_until="load")
        _open_health(pg)
        d = pg.evaluate(SNAP)
        pg.close()
        b.close()
    assert d["n"] >= 4, "320 档默认应至少可见 4 条渠道行，实测 %d" % d["n"]
    assert d["over"] <= 1, "320 健康页横向溢出 %d" % d["over"]
    bad = []
    for i, r in enumerate(d["rows"]):
        if not r["grid"] or r["grid"]["W"] < 230:
            bad.append("第%d行 24h 格带仅 %s" % (i + 1, r["grid"]))
        if r["grid"]["T"] < r["lab"]["B"] - 2:
            bad.append("第%d行格带未换到名称下方" % (i + 1))
        if abs(r["lab"]["T"] - r["badge"]["T"]) > 4:
            bad.append("第%d行名称/徽标不同顶（%d vs %d）"
                       % (i + 1, r["lab"]["T"], r["badge"]["T"]))
        if not (60 <= r["row"]["H"] <= 90):
            bad.append("第%d行行高 %d 不在两行档 60–90" % (i + 1, r["row"]["H"]))
    assert not bad, "320 健康两行格带: " + "；".join(bad)


def test_health_grid_is_stacked_at_390(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        pg.goto(BASE + "/", wait_until="load")
        _open_health(pg)
        d = pg.evaluate(SNAP)
        pg.close()
        b.close()
    assert d["n"] >= 4
    assert d["over"] <= 1
    bad = []
    # 2026-11-07：390 起格带整行落到名称下方（三行节奏），不再把 96 格挤进
    # 名称与徽标之间。行高按真实内容 60–90，格带须占满可用宽。
    for i, r in enumerate(d["rows"]):
        if not r["grid"] or r["grid"]["W"] < 230:
            bad.append("第%d行 390 格带仅 %s" % (i + 1, r["grid"]))
        if r["grid"]["T"] < r["lab"]["B"] - 2:
            bad.append("第%d行 390 格带未换到名称下方" % (i + 1))
        if not (60 <= r["row"]["H"] <= 90):
            bad.append("第%d行 390 行高 %d 不在 60–90" % (i + 1, r["row"]["H"]))
    assert not bad, "390 健康三行节奏: " + "；".join(bad)
