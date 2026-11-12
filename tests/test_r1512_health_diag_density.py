# -*- coding: utf-8 -*-
"""r1512：渠道诊断 3 列密排 + 无证据行不占位（真实渲染 + 负控）。

背景：1512 档原为固定两列，每卡 625px 宽、95px 高，正文只占左半，
10 张卡总高 525px，读作「两列稀疏清单」。改为：
- ≥1400 四列（1512 实测 4×309px，4+4+2），701–1399 两列（5×2）；
  不用三列：10 张 ÷ 3 必然 3+3+3+1，末张落单（r813d 门禁）；
- 无证据的卡不再显示「证据：—」行，有证据的卡保留（同排等高）；
- 「登录 登录状态未读取」收敛为「登录 未读取」，去掉重复主语。
本门禁只测真实渲染：列数/卡宽/总高/无证据行是否隐藏/溢出，并用
「两列 + 强制显示空证据行」复现旧行为做负控。
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


PROBE = r"""
() => {
  const b=document.getElementById('healthDiagBody');
  const br=b.getBoundingClientRect();
  const cards=[...b.querySelectorAll('.hdiag-card')];
  const ev=[...b.querySelectorAll('.hdiag-card>.hdiag-e')];
  return {
    vw:innerWidth, cols:getComputedStyle(b).gridTemplateColumns,
    boxH:+br.height.toFixed(1), boxW:+br.width.toFixed(1),
    n:cards.length,
    cardW:[...new Set(cards.map(c=>+c.getBoundingClientRect().width.toFixed(1)))],
    cardH:cards.map(c=>+c.getBoundingClientRect().height.toFixed(1)),
    evVisible:ev.filter(e=>getComputedStyle(e).display!=='none').length,
    evHidden:ev.filter(e=>getComputedStyle(e).display==='none').length,
    badgeClip:[...b.querySelectorAll('.hdiag-card>.hdiag-h>.hdiag-st')]
      .filter(e=>e.scrollWidth>e.clientWidth+1).length,
    badLoginCopy:[...b.querySelectorAll('.hdiag-l')].filter(e=>e.innerText.indexOf('登录状态未读取')>=0).length,
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""


def open_health(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.wait_for_timeout(800)
    page.evaluate("()=>{switchView('mon');showMonTab('health')}")
    page.wait_for_function(
        "()=>document.querySelectorAll('#healthDiagBody .hdiag-card').length>=10", timeout=25000)
    if width > 600:
        page.evaluate("()=>document.getElementById('healthDiagMore')?.click()")
    page.wait_for_timeout(600)
    return ctx, page


def test_three_columns_and_hidden_empty_evidence(srv, browser):
    ctx, page = open_health(browser, 1512)
    try:
        d = page.evaluate(PROBE)
        assert d["n"] == 10, d
        assert len(d["cols"].split()) == 4, d["cols"]
        assert 290 <= d["cardW"][0] <= 330, d["cardW"]
        assert max(d["cardH"]) <= 120, d["cardH"]
        assert d["boxH"] <= 380, "diag box too tall: %s" % d["boxH"]
        assert d["evVisible"] >= 1 and d["evHidden"] >= 5, d
        assert d["badLoginCopy"] == 0, "redundant 登录 登录状态未读取 copy: %s" % d
        assert d["docDx"] <= 0, d
        # r1555：4 列卡头里「去哪儿 App」比其余 App 长 13px，徽标曾被压到
        # 109.8px（内容 115px）末字省略；徽标必须完整。
        assert d["badgeClip"] == 0, "状态徽标被截断：%s" % d
        _badge_bad = page.evaluate(
            "()=>{const st=document.createElement('style');"
            "st.textContent='#healthDiagBody.hdiag.diag-open .hdiag-card"
            ">.hdiag-h{gap:8px!important}#healthDiagBody.hdiag.diag-open "
            ".hdiag-card>.hdiag-h>.hdiag-st{flex:0 1 auto!important}';"
            "document.head.appendChild(st);"
            "const b=document.getElementById('healthDiagBody');"
            "const n=[...b.querySelectorAll('.hdiag-card>.hdiag-h>.hdiag-st')]"
            ".filter(e=>e.scrollWidth>e.clientWidth+1).length;"
            "st.remove();return n;}")
        assert _badge_bad >= 1, "旧卡头间距必须复现徽标省略"
        # 负控：两列 + 强制显示空证据行，旧行为必须让上述判据红
        page.add_style_tag(content="#healthDiagBody.hdiag.diag-open{grid-template-columns:repeat(2,minmax(0,1fr))!important}"
                                   "#healthDiagBody .hdiag-card>.hdiag-e[aria-hidden=\"true\"]{display:block!important}")
        page.wait_for_timeout(300)
        d2 = page.evaluate(PROBE)
        assert len(d2["cols"].split()) == 2, d2["cols"]
        assert d2["boxH"] > 450, "empty evidence rows did not grow the panel: %s" % d2["boxH"]
        assert d2["evHidden"] == 0, d2
    finally:
        ctx.close()


def test_two_columns_at_1024(srv, browser):
    ctx, page = open_health(browser, 1024)
    try:
        d = page.evaluate(PROBE)
        assert d["n"] == 10, d
        assert len(d["cols"].split()) == 2, d["cols"]
        assert 420 <= d["cardW"][0] <= 480, d["cardW"]
        assert d["boxH"] <= 470, d["boxH"]
        assert d["docDx"] <= 0, d
    finally:
        ctx.close()
