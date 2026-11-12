# -*- coding: utf-8 -*-
"""r1136 Wave4：10 渠道 × 全表面单源与四端同步。

- 渠道宇宙从源码派生（BROWSER/APP/PLATS/DEMO_SCAN_PLATS）
- 能力矩阵 10×7：非 y 格必须有 note/scope（不支持/未验证的原因）
- 11 轴平台契约 strict 无 n
- 推送中文名 / CSV 导出 / 登录卡 / 用户渠道 / 检索 chip / 健康行 / 演示站 / README
- 一个真实 CSV 下载断言 10 个渠道列值
"""
import csv
import io
import json
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


def _payload():
    from core.channels import channel_dims_payload
    return channel_dims_payload()


def _missing_notes(payload):
    bad = []
    for c in payload["channels"]:
        for d, v in c["cells"].items():
            if v != "y" and not (c.get("dim_notes", {}).get(d) or c.get("dim_scopes", {}).get(d)):
                bad.append("%s/%s=%r" % (c["plat"], d, v))
        for s, v in (c.get("surface_cells") or {}).items():
            if v != "y" and not (c.get("surface_notes", {}).get(s) or ""):
                bad.append("%s/surface-%s=%r" % (c["plat"], s, v))
    return bad


def test_universe_single_source_and_notes():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.channel_links import PLATS
    from core.demo import DEMO_SCAN_PLATS
    ps = list(BROWSER_CHANNELS) + list(APP_CHANNELS)
    assert len(ps) == 10 and len(set(ps)) == 10, ps
    assert set(PLATS) == set(BROWSER_CHANNELS), (PLATS, BROWSER_CHANNELS)
    assert set(DEMO_SCAN_PLATS) == set(ps), (DEMO_SCAN_PLATS, ps)
    p = _payload()
    assert len(p["channels"]) == 10
    assert p["dims"] == ["domestic", "intl", "calendar", "detail", "round_trip", "multi_city", "low_fare"]
    for c in p["channels"]:
        assert set(c["cells"]) == set(p["dims"]), c["plat"]
        assert all(v in ("y", "n", "") for v in c["cells"].values()), c["plat"]
    assert _missing_notes(p) == [], "non-y cells without reason: %s" % _missing_notes(p)[:8]


def test_negative_missing_note_is_caught():
    p = _payload()
    target = next((c, d) for c in p["channels"] for d, v in c["cells"].items() if v != "y")
    c, d = target
    c["dim_notes"][d] = ""
    c["dim_scopes"][d] = ""
    assert _missing_notes(p) != []
    restored = _payload()
    assert _missing_notes(restored) == []


def test_push_names_10_unique():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.alerter import Alerter
    ps = list(BROWSER_CHANNELS) + list(APP_CHANNELS)
    names = [Alerter.plat_cn(p) for p in ps]
    assert all(names), names
    assert len(set(names)) == 10, names


def test_contract_strict_no_n():
    r = subprocess.run([sys.executable, "-m", "core.channel_contract", "--strict"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])


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


def test_render_surfaces_and_csv(srv, browser):
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS, CHANNEL_CN
    expected = set(CHANNEL_CN[p] for p in list(BROWSER_CHANNELS) + list(APP_CHANNELS))
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    try:
        page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
        page.evaluate("switchView('search')")
        page.wait_for_function("document.querySelectorAll('#srxRows .srx-row').length>0", timeout=25000)
        page.wait_for_timeout(600)
        chips = page.evaluate("""() => [...document.querySelectorAll('#srxPlatPick .srx-pchip input')].map(e=>e.value)""")
        assert len(chips) == 10 and set(chips) == set(list(BROWSER_CHANNELS) + list(APP_CHANNELS)), chips

        page.evaluate("switchView('mon');showMonTab('health')")
        page.wait_for_function("document.querySelectorAll('#hbody .hrow').length>0", timeout=25000)
        assert page.evaluate("document.querySelectorAll('#hbody .hrow').length") == 10

        page.evaluate("switchView('cfg');showCfgPanel('login')")
        page.wait_for_timeout(1200)
        plats = page.evaluate("""() => [...new Set([...document.querySelectorAll('#panel-login [data-plat]')].map(e=>e.getAttribute('data-plat')))]""")
        assert len(plats) == 10 and set(plats) == set(list(BROWSER_CHANNELS) + list(APP_CHANNELS)), plats

        page.evaluate("showCfgPanel('users')")
        page.wait_for_timeout(700)
        user_plats = page.evaluate("""() => [...new Set([...document.querySelectorAll('#panel-users [data-plat],#panel-users [data-p]')].map(e=>e.getAttribute('data-plat')||e.getAttribute('data-p')))].filter(Boolean)""")
        assert len(set(user_plats) & (set(list(BROWSER_CHANNELS) + list(APP_CHANNELS)))) == 10, user_plats

        page.evaluate("switchView('search')")
        page.wait_for_function("document.querySelectorAll('#srxRows .srx-row').length>0", timeout=25000)
        page.wait_for_timeout(500)
        page.evaluate("document.querySelector('.srx-more-btn').click()")
        page.wait_for_timeout(250)
        with page.expect_download(timeout=30000) as dl:
            page.click("text=导出 CSV")
        path = dl.value.path()
        text = open(path, "rb").read().decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        head = rows[0]
        for col in ("渠道", "采集入口", "证据级别"):
            assert col in head, (col, head)
        idx = head.index("渠道")
        got = {r[idx] for r in rows[1:] if len(r) > idx and r[idx]}
        assert got == expected, "CSV channels=%s expected=%s" % (got, expected)
    finally:
        ctx.close()


def test_demo_site_and_readme_10_channels():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS, CHANNEL_CN
    names = [CHANNEL_CN[p] for p in list(BROWSER_CHANNELS) + list(APP_CHANNELS)]
    site = open(os.path.join(ROOT, "docs", "site", "index.html"), encoding="utf-8").read()
    for n in names:
        assert n in site, "demo site missing %s" % n
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "10 家" in readme or "10 渠道" in readme
    for n in names:
        if " App" in n:
            continue
        assert n in readme, "README missing %s" % n
