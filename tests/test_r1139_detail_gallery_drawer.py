# -*- coding: utf-8 -*-
"""r1139 门禁：解析详情 / 页面校准册按「全屏抽屉」收口（真渲染 + 负控）。

细则 §7：详情/校准册 ≥90vw/92vh；header 56 / body 2 栏 / footer 56；
tab 单行；关闭回原行。旧结构（2026-11-09 实测）：详情 1180×855
（81.9vw/90vh，头 116 因动作独占第二行）、校准册 1180×747（78.6vh）。

本门禁锁：
1. 1440/1024：详情 ≥90vw/92vh，头/复核条 54–58，正文 2 栏，页签 42 内单行；
   动作位于页签同一行且右缘不越界；
2. 900/768/390：详情/校准册均 ≥90vw/92vh（窄档全屏 inset 8 自然满足）；
   页签单行（动作与页签同排横滑）；
3. 负控：把详情强制回 1180×830、页签改回 wrap，两项判据必须变红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = """() => {
 const g=e=>{if(!e)return null;const r=e.getBoundingClientRect();const cs=getComputedStyle(e);
  return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.left),
    right:Math.round(r.right),y:Math.round(r.top),
    disp:cs.display,cols:cs.gridTemplateColumns};};
 const d=document.getElementById('srxDetail');
 const acts=d.querySelector('.srx-dtabs .srx-dacts');
 const dg=d.querySelector('.srx-dgrid');
 return {vw:innerWidth,vh:innerHeight,
  detail:g(d),head:g(d.querySelector('.srx-dhead')),tabs:g(d.querySelector('.srx-dtabs')),
  foot:g(d.querySelector('.srx-savebar')),acts:g(acts),dgrid:g(dg),
  cols:dg?getComputedStyle(dg).gridTemplateColumns.split(' ').filter(Boolean).length:0,
  over:document.documentElement.scrollWidth-innerWidth};}"""

_GAL = """() => {
 const g=e=>{if(!e)return null;const r=e.getBoundingClientRect();
  return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.left),y:Math.round(r.top)};};
 const gal=document.getElementById('srxGallery');
 return {vw:innerWidth,vh:innerHeight,gal:g(gal),head:g(gal.querySelector('.srx-galhead')),
  over:document.documentElement.scrollWidth-innerWidth};}"""


@pytest.fixture(scope="module")
def server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(120):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def _page(browser, server, width):
    pg = browser.new_page(viewport={"width": width, "height": 950},
                          is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto("http://127.0.0.1:%d/" % server, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2200)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)
    return pg


def _open_detail(pg):
    ok = pg.evaluate("""()=>{const rows=(typeof srxFiltered==='function')
        ?srxFiltered():[];const f=rows[0];if(!f)return false;
      SRX.sel=srxKey(f);srxOpenDetail();return true;}""")
    assert ok, "演示数据没有可打开的行"
    pg.wait_for_timeout(500)


@pytest.mark.parametrize("width", [1440, 1024])
def test_desktop_detail_is_full_drawer_with_two_columns(server, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, width)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open_detail(pg)
            d = pg.evaluate(_PROBE)
            assert not errs, errs[:3]
            det = d["detail"]
            assert det["w"] >= d["vw"] * 0.90, d
            assert det["h"] >= d["vh"] * 0.92 - 1, d
            assert 54 <= d["head"]["h"] <= 58, d
            assert 54 <= d["foot"]["h"] <= 58, d
            assert d["cols"] >= 2, d
            # 页签单行：42 的高度里同排放下动作（不换行）
            assert d["tabs"]["h"] <= 46, d
            assert d["acts"]["y"] >= d["tabs"]["y"] - 1, d
            assert d["acts"]["y"] < d["tabs"]["y"] + d["tabs"]["h"], d
            assert d["acts"]["right"] <= det["right"] - 10, d
            assert d["over"] <= 0, d
        finally:
            b.close()


@pytest.mark.parametrize("width", [900, 768, 390])
def test_narrow_detail_and_gallery_fill_viewport(server, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, width)
            _open_detail(pg)
            d = pg.evaluate(_PROBE)
            det = d["detail"]
            assert det["w"] >= d["vw"] * 0.90, d
            assert det["h"] >= d["vh"] * 0.92 - 1, d
            assert d["tabs"]["h"] <= 46, d
            assert d["over"] <= 0, d
            pg.evaluate("srxCloseDetail();srxOpenGallery()")
            pg.wait_for_timeout(500)
            g = pg.evaluate(_GAL)
            assert g["gal"]["w"] >= g["vw"] * 0.90, g
            assert g["gal"]["h"] >= g["vh"] * 0.92 - 1, g
            assert g["over"] <= 0, g
        finally:
            b.close()


def test_negative_control_detail_size_and_tabs(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, 1440)
            _open_detail(pg)
            # 负控 1：强制回旧大浮卡尺寸 → ≥90vw/92vh 判据必须红
            d = pg.evaluate("""()=>{
              const el=document.getElementById('srxDetail');
              el.style.setProperty('width','1180px','important');
              el.style.setProperty('height','830px','important');
              const r=el.getBoundingClientRect();
              return {w:Math.round(r.width),h:Math.round(r.height),vw:innerWidth,vh:innerHeight};}""")
            assert not (d["w"] >= d["vw"] * 0.90 and d["h"] >= d["vh"] * 0.92 - 1), d
            pg.evaluate("""()=>{const el=document.getElementById('srxDetail');
              el.style.removeProperty('width');el.style.removeProperty('height');}""")
            d = pg.evaluate(_PROBE)
            assert d["detail"]["w"] >= d["vw"] * 0.90, d["detail"]
            # 负控 2：页签改回 wrap → 单行判据必须红
            h = pg.evaluate("""()=>{
              const t=document.querySelector('#srxDetail .srx-dtabs');
              t.style.setProperty('flex-wrap','wrap','important');
              t.style.setProperty('width','360px','important');
              const r=t.getBoundingClientRect();
              return {h:Math.round(r.height)};}""")
            assert h["h"] > 46, ("页签 wrap 负控没被抓住：%s" % h)
        finally:
            b.close()
