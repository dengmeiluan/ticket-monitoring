# -*- coding: utf-8 -*-
"""r1506：航班明细行高一致性门禁 + 负控。

背景：用户点名「明细行 92 / 药丸 30」。实测第一行（带 `a.vw` 源站外链）为
95.3px：外链是 `div.stl` 之后的块级兄弟，独占一行且只显示一个箭头；其余行
75.8px，首行明显鼓包。外链已移入航班名后的同一行内，所有行回到 75.8px。

本门禁只测真实渲染（桌面档，≥1000px；900 以下为卡片式重排，不按表行判）：
1. 120 行中前 8 行行高均在 72–88，极差 ≤2px。
2. 类型药丸高度 20–22px。
3. 首行的源站外链与航班名同一行（其 rect 在首行内且与首行顶部距离 < 30px）。
4. 负控：把 `a.vw` 改回 `display:block`，首行必须 >88 且与其余行差 ≥10。
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
def browser(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


PROBE = r"""
() => {
  const rows = [...document.querySelectorAll('#ftable tbody tr')]
    .filter(r => r.getBoundingClientRect().height > 1);
  const hs = rows.slice(0, 8).map(r => +r.getBoundingClientRect().height.toFixed(1));
  const first = rows[0];
  const fr = first.getBoundingClientRect();
  const vw = first.querySelector('a.vw');
  const vr = vw ? vw.getBoundingClientRect() : null;
  const pills = [...document.querySelectorAll('#ftable .tag')]
    .filter(e => e.getBoundingClientRect().height > 0).slice(0, 8)
    .map(e => +e.getBoundingClientRect().height.toFixed(1));
  return {
    n: rows.length, hs, pills,
    vw: vr ? {top: +(vr.top - fr.top).toFixed(1), h: +vr.height.toFixed(1)} : null,
    docDx: document.documentElement.scrollWidth - document.documentElement.clientWidth
  };
}
"""


def open_details(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.evaluate("() => document.querySelector('#montabs .mtab[data-t=details]').click()")
    page.wait_for_timeout(1200)
    return ctx, page


@pytest.mark.parametrize("width", [1440, 1180, 1024])
def test_detail_rows_uniform_height(browser, width):
    ctx, page = open_details(browser, width)
    d = page.evaluate(PROBE)
    page.close()
    ctx.close()

    assert d["n"] >= 50, (width, d)
    assert len(d["hs"]) >= 6, (width, d)
    assert max(d["hs"]) <= 88, (width, d)
    assert min(d["hs"]) >= 72, (width, d)
    assert max(d["hs"]) - min(d["hs"]) <= 2, (width, d)
    assert all(20 <= h <= 22 for h in d["pills"]), (width, d)
    assert d["vw"] and 0 <= d["vw"]["top"] < 30, (width, d)
    assert d["docDx"] <= 0, (width, d)


def test_negative_control_source_link_block(browser):
    ctx, page = open_details(browser, 1440)
    page.add_style_tag(content="#ftable td>a.vw{display:block!important;margin-left:0!important}")
    page.wait_for_timeout(200)
    d = page.evaluate(PROBE)
    page.close()
    ctx.close()
    assert max(d["hs"]) > 88, d
    assert max(d["hs"]) - min(d["hs"]) >= 10, d
