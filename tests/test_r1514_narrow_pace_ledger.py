# -*- coding: utf-8 -*-
"""r1514：窄档节流台账条从「2×2 空表」压回一条读数。

背景：390/320 实测旧布局把四条 12px 台账读数放进 2×2 网格，每颗
min-height:44（94px 高），0/0 又单独占一行并带分隔线——整个台账条
166px，只有五个短值，读作一块空表。四颗读数总宽 294px，390 的
336px 内容宽一行放得下。

门禁只测真实渲染：
1. 390：台账条 ≤90px；四颗读数同一行；0/0 在下一行右对齐。
2. 320：≤120px；读数最多两行。
3. 1512：桌面台账条不回退（≤66px）。
4. 负控：注回旧 2×2/min-height:44/border-top，台账条必须重新
   长到 >140px，且读数占两行。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_health(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_function("()=>document.querySelectorAll('#hbody .hrow').length>=10", timeout=25000)
    if not page.evaluate("!!document.getElementById('hpaceFold')?.open"):
        page.click("#hpaceFold > summary")
    page.wait_for_function("()=>document.querySelectorAll('#paceBox .pace-row').length>=10", timeout=25000)
    page.wait_for_timeout(400)
    return ctx, page


PROBE = r"""
() => {
  const bx=e=>{if(!e)return null;const b=e.getBoundingClientRect();
    return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),right:+b.right.toFixed(1)}};
  const led=document.querySelector('#paceBox .pace-led');
  const facts=document.querySelector('#paceBox .pace-facts');
  const now=document.querySelector('#paceBox .pace-now');
  const kids=facts?[...facts.children]:[];
  return {led:bx(led),facts:bx(facts),now:bx(now),
    nowLast:bx(now?now.lastElementChild:null),
    fy:kids.map(e=>+e.getBoundingClientRect().y.toFixed(1)),
    fh:kids.map(e=>+e.getBoundingClientRect().height.toFixed(1)),
    n:kids.length,
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


@pytest.mark.parametrize("width", [390, 320])
def test_narrow_ledger_is_one_strip(srv, browser, width):
    ctx, page = open_health(browser, width)
    try:
        d = page.evaluate(PROBE)
        assert d["n"] == 4, "台账读数不是 4 颗：%s" % d
        limit = 90 if width >= 390 else 120
        assert d["led"]["h"] <= limit, "台账条 %.1f > %d（仍是一块空表）" % (d["led"]["h"], limit)
        ys = sorted(set(d["fy"]))
        assert len(ys) <= (1 if width >= 390 else 2), "读数行数 %d 过多：%s" % (len(ys), d)
        assert d["now"]["y"] >= d["facts"]["y"] + d["facts"]["h"] - 0.5, "0/0 未排在读数下方"
        assert abs(d["nowLast"]["right"] - d["led"]["right"]) <= 1.5, "0/0 未贴台账右缘：%s" % d
        assert d["docDx"] <= 0, "横向溢出 %s" % d["docDx"]
    finally:
        ctx.close()


def test_desktop_ledger_unchanged(srv, browser):
    ctx, page = open_health(browser, 1512)
    try:
        d = page.evaluate(PROBE)
        assert d["led"]["h"] <= 66, "桌面台账条回退：%.1f" % d["led"]["h"]
        assert len(set(d["fy"])) == 1, "桌面读数不在同一行：%s" % d
    finally:
        ctx.close()


def test_negative_control_old_grid(srv, browser):
    """负控：注回 2×2 网格 + 44px 高 + 分隔线，台账条必须重新变高。"""
    ctx, page = open_health(browser, 390)
    try:
        page.add_style_tag(content=(
            "#paceBox .pace-facts{display:grid!important;"
            "grid-template-columns:repeat(2,minmax(0,1fr))!important;"
            "gap:6px!important;flex-basis:100%!important}"
            "#paceBox .pace-fact{min-height:44px!important;padding:4px 9px!important;"
            "background:var(--r-surface)!important;border-radius:9px!important}"
            "#paceBox .pace-now{border-top:1px solid var(--r-hair)!important;padding-top:8px!important}"))
        page.wait_for_timeout(300)
        d = page.evaluate(PROBE)
        assert d["led"]["h"] > 140, "旧 2×2 台账未被识别：%.1f" % d["led"]["h"]
        assert len(set(d["fy"])) == 2, "旧 2×2 网格未被识别：%s" % d
    finally:
        ctx.close()
