# -*- coding: utf-8 -*-
r"""r653：App 没有「出口代理」控件是对的，但页面必须说清为什么。

`crawler.proxy_map` 只对浏览器渠道生效——`AppCrawler` 是独立基类
（`crawlers/app_base.py:class AppCrawler`），不继承 `BaseCrawler`，也就
不读 `proxy_map`；App 的出网由 MuMu 模拟器自己的网络负责。

所以这里**不该**给 App 加一个出口代理输入框：填了没用，比不给更糟
（用户会以为配好了，出问题时不查模拟器）。但也不能什么都不说——
否则用户看到 5 家有、App 没有，只会当成漏配。

判据（真渲染）：①出口代理控件恰好是 5 家浏览器渠道（不含 app_zhixing）；
②同分区里有说明「App 走真机、出口由模拟器决定」。
负控：删掉说明 → ②红；给 App 加一个 glbPm_app_zhixing → ①红。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BROWSER = {"qunar", "fliggy", "ctrip", "tongcheng", "tuniu"}


def _render_globals():
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('cfg')}")
                pg.wait_for_timeout(1200)
                pg.evaluate("""()=>{const c=document.querySelector(
                  '#cfgnav .cnav[data-p="globals"]');if(c)c.click()}""")
                pg.wait_for_timeout(1200)
                return pg.evaluate(r"""()=>{
                  const box=document.getElementById('cfgglobals');
                  return {
                    pm:[...box.querySelectorAll('input[id^="glbPm_"]')]
                        .map(e=>e.id.replace('glbPm_','')),
                    txt:(box.innerText||'').replace(/\s+/g,' ')};}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_proxy_controls_only_cover_browser_channels():
    got = _render_globals()
    assert set(got["pm"]) == BROWSER, (
        "出口代理控件的渠道集合变了（App 走真机，不该有这一项）：%s"
        % sorted(got["pm"]))


def test_page_explains_why_the_app_has_no_proxy_field():
    got = _render_globals()
    assert "智行 App 走真机" in got["txt"], (
        "5 家有、App 没有，却没说为什么——用户只会当成漏配：%r"
        % got["txt"][:200])
    assert "模拟器" in got["txt"], "没指出 App 的出口该去哪儿改"
