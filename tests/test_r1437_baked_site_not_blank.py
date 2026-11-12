# -*- coding: utf-8 -*-
"""r1437：**烘焙静态站**（公开演示页）六视图不得是空壳。

为什么单独钉：`tests/test_r1130_wave3_pages_contract.py` 的"无空白面板"契约跑的是
**本地 demo 服务器**（`BASE + "/"`），覆盖不到 `docs/site/index.html` ——
而那才是访客在 GitHub Pages 上真正打开的东西。两者数据来源不同：
静态站的 `/api/*` 全由烘焙层 `window.__BAKED__` 答复，少烘一条就只剩空壳
（本轮实测：三率卡就曾是空表，因为我们烘的是真库快照）。

契约：
1. 六个子标签每个都有实质内容（可见字数 > 80），不是只有表头；
2. 全程无 JS 报错；
3. 三率卡展开后必须有行（演示数据必须真的烘进去）。
"""
import http.server
import os
import socketserver
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, "docs", "site")
INDEX = os.path.join(SITE_DIR, "index.html")

TABS = ["overview", "specials", "trend", "watch", "details", "health"]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """静态站服务（静音日志）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE_DIR, **kw)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site_url():
    assert os.path.isfile(INDEX), "缺少烘焙站：先跑 python docs/demo_build.py"
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Quiet)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/index.html" % port
    finally:
        srv.shutdown()


def test_baked_site_tabs_are_not_empty(site_url):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
        pg.goto(site_url, wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(3000)
        thin = []
        for t in TABS:
            pg.evaluate("(x)=>{try{showMonTab(x)}catch(e){}}", t)
            pg.wait_for_timeout(900)
            chars = pg.evaluate(
                "(x)=>{const e=document.getElementById('montab-'+x);"
                "return e?((e.innerText||'').replace(/\\s+/g,' ').trim().length):-1;}", t)
            if chars < 80:
                thin.append((t, chars))
        assert not thin, "烘焙站这些视图是空壳（可见字数 <80）：%s" % thin
        assert not errs, "烘焙站有 JS 报错：%s" % errs[:3]
        b.close()


def test_baked_site_rates_card_has_rows(site_url):
    """三率卡是上一轮踩过的坑：烘的是真库快照 → 线上空表。"""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        pg.goto(site_url, wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(2500)
        pg.evaluate("()=>{try{showMonTab('health')}catch(e){}}")
        pg.wait_for_timeout(700)
        pg.evaluate("()=>{const b=document.getElementById('ratesMore');if(b)b.click()}")
        pg.wait_for_timeout(1200)
        n = pg.evaluate("()=>document.querySelectorAll('#ratesBody .rt-row').length")
        assert n >= 5, "烘焙站三率卡只有 %d 行（演示数据没烘进去）" % n
        b.close()
