# -*- coding: utf-8 -*-
"""r1507：≤430 配置分区导航的选中竖线必须贴着图标 + 负控。

背景：配置侧栏在 ≤430 变成 2×2 等宽网格，导航片被拉满整格且内容居中；
`.on` 的 2px 左标记落在格左缘，与图标相距 390 为 41–48px、320 为 29–36px，
读作一个悬空括号（截图 cfg_users_390_r1505.png）。窄档改为内容贴左后，
四个导航片的图标都落在格左 13px 轨，选中竖线回到图标左侧。

门禁只测真实渲染：
1. 390/320/768/1440：所有可见导航片的图标距自身行盒左缘 ≤16px。
2. 选中项仍有 2px 左标记（不是把标记删掉了）。
3. 负控：390 注入 justify-content:center，选中项图标距行盒必须 ≥25px。
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

MEASURE = r"""
() => {
  const items = [...document.querySelectorAll('#cfgnav .cnav')]
    .filter(e => e.getBoundingClientRect().width > 0);
  return {
    items: items.map(e => {
      const r = e.getBoundingClientRect();
      const ic = e.querySelector('.ic');
      const ir = ic.getBoundingClientRect();
      const cs = getComputedStyle(e);
      const ps = getComputedStyle(e, '::before');
      return {
        on: e.classList.contains('on'),
        box: +r.x.toFixed(1),
        iconDx: +(ir.x - r.x).toFixed(1),
        borderL: cs.borderLeftWidth,
        markW: ps.width,
        markH: ps.height,
        markBg: ps.backgroundColor,
        markLeft: ps.left,
      };
    }),
    docDx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}
"""


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
def browser(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_cfg(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.evaluate("() => switchView('cfg')")
    page.wait_for_timeout(1100)
    return ctx, page


@pytest.mark.parametrize("width", [390, 320, 768, 1440])
def test_nav_icons_on_cell_left_rail(browser, width):
    ctx, page = open_cfg(browser, width)
    m = page.evaluate(MEASURE)
    page.close()
    ctx.close()

    assert len(m["items"]) == 4, (width, m)
    assert all(it["iconDx"] <= 16 for it in m["items"]), (width, m)
    assert m["docDx"] <= 0, (width, m)


def test_selected_marker_still_present(browser):
    ctx, page = open_cfg(browser, 390)
    m = page.evaluate(MEASURE)
    page.close()
    ctx.close()

    on = [it for it in m["items"] if it["on"]]
    assert len(on) == 1, m
    # r1508：标记改为独立 16px 短竖线，不再用会随圆角弯曲的 border-left
    assert on[0]["borderL"] == "0px", m
    assert on[0]["markW"] == "2px", m
    assert on[0]["markH"] == "16px", m
    assert on[0]["markLeft"] == "0px", m
    assert on[0]["markBg"] != "rgba(0, 0, 0, 0)", m


def test_negative_control_centered_cell(browser):
    ctx, page = open_cfg(browser, 390)
    page.add_style_tag(content=(
        "#cfgview #cfgnav .cnav{justify-content:center!important;padding-left:8px!important}"
    ))
    page.wait_for_timeout(150)
    m = page.evaluate(MEASURE)
    page.close()
    ctx.close()

    on = [it for it in m["items"] if it["on"]][0]
    assert on["iconDx"] >= 25, m
