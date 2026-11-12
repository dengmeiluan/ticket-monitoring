# -*- coding: utf-8 -*-
"""r1513：渠道健康 › 逐渠道清单不再是「表格」。

背景：用户点名「渠道节流逐渠道面板仍偏表格化」。实测 1512 档：
- 每行先画一条「渠道 / 判定 / 近24h·依据 / 操作」表头；
- 证据行被钉成 e1=42% / e2=58% 两栏，短结论后面留 390px 空洞，
  读作两列对不上；
- 空策略条仍预留 22px，63px 的行只有 30px 有内容。

本门禁只测真实渲染：
1. 桌面 1512/1024/768：无表头；行高 40–46；证据两段相邻
   （e2.x - e1.right ≤16）；e2 不落在 55% 之后的固定栏位；
   动作贴行右缘；无横向溢出。
2. 策略条真的在动时行仍 ≤64（第二条轨按内容出现，不是常驻空气）。
3. 窄档 390 保持既有两行结构，行高 ≤64。
4. 负控：注回旧 CSS（30px+22px 固定轨 + 42%/58% 分栏）必须使
   行高判据与相邻判据同时失败。
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


def open_pace(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_function("()=>document.querySelectorAll('#hbody .hrow').length>=10", timeout=25000)
    if not page.evaluate("!!document.getElementById('hpaceFold')?.open"):
        page.click("#hpaceFold > summary")
    page.wait_for_function("()=>document.querySelectorAll('#paceBox .pace-row').length>=10", timeout=25000)
    # 演示策略条由 /api/strategy 异步插入（实测 0.5s 时无、3s 时 10/10，行高 44→63）。
    # 本文件桌面判据测的是「没有策略条时的行语法」，必须等载荷落定后把条移除再量，
    # 否则会在过渡窗口里随机量到 63px（并行 xdist 下必现假红）。策略条本身的高度
    # 由 test_strategy_strip_still_fits 单独覆盖（≤64）。
    try:
        page.wait_for_function(
            "()=>document.querySelectorAll('#paceBox .pstrip').length>=10",
            timeout=6000)
    except Exception:
        pass
    page.evaluate(
        "()=>document.querySelectorAll('#paceBox .pstrip').forEach(e=>e.remove())")
    page.wait_for_timeout(100)
    return ctx, page


PROBE = r"""
() => {
  const rows=[...document.querySelectorAll('#paceBox .pace-row')];
  const box=e=>{if(!e)return null;const b=e.getBoundingClientRect();
    return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),
            right:+b.right.toFixed(1)}};
  const first=rows[0];
  const ev=first?first.querySelector('.ev'):null;
  const e1=ev?ev.querySelector('.e1'):null;
  const e2=ev?ev.querySelector('.e2'):null;
  return {
    n:rows.length,
    heads:document.querySelectorAll('#paceBox .pace-head').length,
    hs:rows.map(r=>+r.getBoundingClientRect().height.toFixed(1)),
    row:box(first), ev:box(ev), e1:box(e1), e2:box(e2),
    ac:box(first?first.querySelector('.ac'):null),
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""


def _cols(page):
    return page.evaluate(PROBE)


@pytest.mark.parametrize("width", [1512, 1024, 768])
def test_desktop_pace_is_list_not_table(srv, browser, width):
    ctx, page = open_pace(browser, width)
    try:
        d = _cols(page)
        assert d["n"] >= 10, d["n"]
        assert d["heads"] == 0, "表头还在：逐渠道仍读作表格"
        assert max(d["hs"]) <= 46, "行高 %.1f > 46（空策略条仍在占位）" % max(d["hs"])
        assert min(d["hs"]) >= 40, "行高 %.1f < 40（行被压塌）" % min(d["hs"])
        assert d["e1"] and d["e2"], "证据两段缺失：%s" % d
        # 两段基线对齐，盒高 16/17px，y 允许 1.5px 基线差。
        assert abs(d["e1"]["y"] - d["e2"]["y"]) <= 1.5, "证据两段不在同一行：%s" % d
        gap = d["e2"]["x"] - d["e1"]["right"]
        assert 4 <= gap <= 16, "证据两段间隔 %.1fpx（未相邻）" % gap
        # 旧实现 e2 起点固定在 42% 分栏之后；这里必须明显早于 55% 线。
        assert d["e2"]["x"] < d["ev"]["x"] + d["ev"]["w"] * 0.55, \
            "e2 仍被钉在固定栏位：%s" % d
        assert d["ac"]["right"] <= d["row"]["right"] + 0.5, "动作越过行右缘：%s" % d
        assert d["row"]["right"] - d["ac"]["right"] <= 2.0, "动作未贴行右缘：%s" % d
        assert d["docDx"] <= 0, "横向溢出 %s" % d["docDx"]
    finally:
        ctx.close()


def test_strategy_strip_still_fits(srv, browser):
    """策略条在动时必须能长出第二条轨，且总高仍 ≤64。"""
    ctx, page = open_pace(browser, 1024)
    try:
        base = page.evaluate("()=>document.querySelector('#paceBox .pace-row').getBoundingClientRect().height")
        got = page.evaluate(
            """() => {const r=document.querySelector('#paceBox .pace-row');
              const d=document.createElement('div');d.className='pstrip';
              d.innerHTML='<span class="pchip">降频 30s</span>';
              r.appendChild(d);
              return +r.getBoundingClientRect().height.toFixed(1);}"""
        )
        assert got > base + 10, "策略条没有撑出第二轨：base=%.1f got=%.1f" % (base, got)
        assert got <= 64, "带策略条的行 %.1f > 64" % got
    finally:
        ctx.close()


def test_narrow_still_two_line(srv, browser):
    ctx, page = open_pace(browser, 390)
    try:
        d = _cols(page)
        assert d["n"] >= 10, d["n"]
        assert d["heads"] == 0, "窄档仍渲染表头"
        assert max(d["hs"]) <= 64, "窄档行高 %.1f > 64" % max(d["hs"])
        assert d["docDx"] <= 0, "窄档横向溢出 %s" % d["docDx"]
    finally:
        ctx.close()


def test_negative_control_old_table_css(srv, browser):
    """负控：注回旧的固定 30/22 轨 + 42%/58% 分栏，两条判据必须同时红。"""
    ctx, page = open_pace(browser, 1024)
    try:
        page.add_style_tag(content=(
            "#paceBox .pace-row{grid-template-rows:30px 22px!important;min-height:0!important}"
            "#paceBox .pace-row .ev .e1{flex:0 1 42%!important}"
            "#paceBox .pace-row .ev .e2{flex:1 1 58%!important;min-width:120px!important}"))
        page.wait_for_timeout(300)
        d = _cols(page)
        assert max(d["hs"]) > 52, "旧固定轨未被识别：%.1f" % max(d["hs"])
        # 旧分栏的「空洞」长在 e1 自己的盒子里（文字只占 75px、盒占 42%），
        # 不是两段之间的 gap——所以量 e1 盒宽，而不是 e1.right 到 e2.x。
        assert d["e1"]["w"] > d["ev"]["w"] * 0.35, \
            "旧 42/58 分栏未被识别：e1 盒宽 %.1f / ev %.1f" % (d["e1"]["w"], d["ev"]["w"])
    finally:
        ctx.close()
