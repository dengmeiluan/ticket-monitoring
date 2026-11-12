# -*- coding: utf-8 -*-
"""r1130：10 渠道全表面闭环契约（2026-11-07）。

用同一份源码真源核对 10 家渠道在主要用户表面的出现：
检索 chip / 筛选 / 明细渠道筛选 / 健康行 / 配置航线渠道 / 登录卡 /
推送中文名 / 特价雷达能力 / 演示种子 / README 中英文 / 演示站。
App 渠道无网页入口属业务上不适用（—），不做假链接。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EXPECTED = ["ctrip", "qunar", "fliggy", "tongcheng", "tuniu",
            "app_zhixing", "app_qunar", "app_fliggy", "app_ctrip", "app_tongcheng"]
CN = ["携程", "去哪儿", "飞猪", "同程", "途牛",
      "智行 App", "去哪儿 App", "飞猪 App", "携程 App", "同程 App"]


def test_source_universe_is_10():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.channel_links import PLATS
    assert set(BROWSER_CHANNELS) | set(APP_CHANNELS) == set(EXPECTED)
    assert set(PLATS) == set(BROWSER_CHANNELS)  # App 无网页入口，业务上不适用


def test_specials_push_export_demo_and_docs_cover_10():
    from core.specials import SPECIAL_CAPABILITY
    from core.demo import DEMO_SCAN_PLATS
    from core.alerter import Alerter
    assert sorted(SPECIAL_CAPABILITY) == sorted(EXPECTED)
    assert set(DEMO_SCAN_PLATS) == set(EXPECTED)
    for p, n in zip(EXPECTED, CN):
        assert Alerter.plat_cn(p) == n
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "'渠道'" in src and "f.plat" in src, "CSV 导出缺渠道列"
    for path in ("README.md", "README_EN.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            txt = f.read()
        assert "10" in txt
    with open(os.path.join(ROOT, "docs", "site", "index.html"), encoding="utf-8") as f:
        site = f.read()
    for n in CN:
        assert n in site, ("演示站缺渠道", n)


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
    priv = tempfile.mkdtemp(prefix="r1130w4_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv, PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo", "--port", str(port)],
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


BASE = None


def test_runtime_surfaces_show_all_10(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(800)
        # 检索 chip
        pg.evaluate("()=>switchView('search')"); pg.wait_for_timeout(600)
        chips = pg.evaluate("()=>[...document.querySelectorAll('#srxPlatPick .srx-pchip')].map(e=>e.textContent.trim())")
        assert chips == CN, chips
        # 明细渠道筛选
        pg.evaluate("()=>switchView('mon')"); pg.wait_for_timeout(200)
        pg.evaluate("()=>showMonTab('details')"); pg.wait_for_timeout(800)
        txt = pg.evaluate("()=>document.getElementById('platchips').textContent")
        for n in CN:
            assert n in txt, ("明细渠道筛选缺", n)
        # 健康 10 行
        pg.evaluate("()=>showMonTab('health')"); pg.wait_for_timeout(900)
        rows = pg.evaluate("()=>[...document.querySelectorAll('#hbody .hrow .hlab')].map(e=>e.textContent.trim())")
        assert rows == CN, rows
        # 配置航线渠道 10 chip
        pg.evaluate("()=>switchView('cfg')"); pg.wait_for_timeout(250)
        pg.evaluate("()=>showCfgPanel('users')"); pg.wait_for_timeout(700)
        pch = pg.evaluate("()=>[...document.querySelectorAll('.pch')].map(e=>e.textContent.trim())")
        assert pch == CN, pch
        # 登录 10 卡
        pg.evaluate("()=>showCfgPanel('login')"); pg.wait_for_timeout(700)
        cards = pg.evaluate("()=>[...document.querySelectorAll('#loginRows .lgcard')].map(e=>e.textContent.replace(/\\s+/g,' ').trim())")
        assert len(cards) == 10, len(cards)
        for c, n in zip(cards, CN):
            assert n.replace(" ", "") in c.replace(" ", ""), (n, c[:50])
        pg.close()
        b.close()
