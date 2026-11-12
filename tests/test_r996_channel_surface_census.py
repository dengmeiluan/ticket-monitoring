# -*- coding: utf-8 -*-
"""r996：渠道能力必须辐射到每个面向用户的表面。

检查 6 个表面都出现全部 10 个渠道（5 网页 + 5 App）：
渠道登录卡、配置渠道入口、能力矩阵列、检索渠道下拉、检索渠道入口、
特价来源；渠道健康 10 行同样逐个点名。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise RuntimeError("demo server did not start")


def test_all_channels_on_every_surface():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    from crawlers import REGISTRY
    from core.channels import CHANNEL_CN
    expected = set(REGISTRY.keys())
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1512, "height": 1000})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('cfg')}")
                pg.wait_for_timeout(1800)
                # r1588：渠道入口板是**异步**拉的（/api/channel-links），固定
                # 1800ms 在负载高时会量到 0 条，把"还没渲染"误报成"缺渠道"
                # （CI 与本地都实测过）。等不到就自己触发一次加载再等。
                try:
                    pg.wait_for_function(
                        "()=>document.querySelectorAll('#cfgChannelLinksBox .chband')"
                        ".length>=8", timeout=10000)
                except Exception:
                    pg.evaluate("()=>{try{if(typeof srxChLinksLoad==='function')"
                                "srxChLinksLoad('cfg')}catch(e){}}")
                    pg.wait_for_function(
                        "()=>document.querySelectorAll('#cfgChannelLinksBox .chband')"
                        ".length>=8", timeout=20000)
                out = {}
                out["login"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#loginRows .lgcard')]"
                    ".map(x=>x.dataset.channel)")
                out["chlinks"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#cfgChannelLinksBox .chband')]"
                    ".map(x=>x.dataset.channel)")
                out["matrix"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#cfgDimMatrix thead th b')]"
                    ".map(x=>x.textContent.trim())")
                pg.evaluate("()=>{switchView('search')}")
                pg.wait_for_timeout(1500)
                out["picker"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#srxPlatPop .srx-pchip input')]"
                    ".map(x=>x.value)")
                pg.evaluate("()=>{srxOpenChLinks()}")
                pg.wait_for_timeout(1500)
                out["srchlinks"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#srxChLinksBox .clx-row')]"
                    ".map(x=>x.dataset.channel)")
                pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
                pg.wait_for_timeout(1800)
                out["health"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#hbody .hrow .hlab')]"
                    ".map(x=>x.textContent.trim())")
                pg.evaluate("()=>{showMonTab('specials')}")
                pg.wait_for_timeout(2000)
                out["specials"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#spentryboard .chband')]"
                    ".map(x=>x.dataset.channel)")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()

    for k in ("login", "chlinks", "picker", "srchlinks", "specials"):
        got = set(out[k])
        assert got == expected, (k, "缺 %s / 多 %s" % (
            sorted(expected - got), sorted(got - expected)))
    assert len(out["health"]) == len(expected), out["health"]
    for p in expected:
        assert any(CHANNEL_CN[p] == x or CHANNEL_CN[p] in x
                   for x in out["health"]), (p, out["health"])
    for p in expected:
        assert any(CHANNEL_CN[p] == x or CHANNEL_CN[p] in x
                   for x in out["matrix"]), (p, out["matrix"])
