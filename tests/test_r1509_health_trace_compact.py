# -*- coding: utf-8 -*-
"""r1509：渠道健康「展开详情」必须是紧凑行内 detail row + 负控。

背景：详情曾按三段竖排（状态 / 分域·通路·会话 / 操作），每段 12px 上下
内衬，1440 实测整块 270px、右侧大半空白，读作「展开后变成另一个页面」。
用户点名「展开溯源非常劣质割裂」。现改为一行三列：状态徽标 | 分域/通路/
会话（可换行）| 操作；1440 实测 72px、390 实测 114px。

门禁：
1. 1440：展开体高度 ≤90，宽度=所属行宽−4，动作右缘距面板右缘 ≤24。
2. 390：展开体高度 ≤140，无横向溢出。
3. 负控：注入旧的三段竖排样式，1440 高度必须 ≥160。
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

PROBE = r"""
() => {
  const p = document.querySelector('#hbody .hcdet:not([hidden])');
  if (!p) return null;
  const r = p.getBoundingClientRect();
  const row = p.previousElementSibling.getBoundingClientRect();
  const acts = p.querySelector('.hcd-acts');
  const ar = acts ? acts.getBoundingClientRect() : null;
  return {
    h: +r.height.toFixed(1), w: +r.width.toFixed(1),
    rowW: +(row.width - 4).toFixed(1),
    sections: p.querySelectorAll('.hcd-sec').length,
    acts: p.querySelectorAll('.hcd-acts button').length,
    actRightGap: ar ? +(r.right - ar.right).toFixed(1) : null,
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


def open_expanded(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 1200})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.evaluate("() => document.querySelector('#montabs .mtab[data-t=health]').click()")
    page.wait_for_timeout(1300)
    page.click("#hbody .hrow [data-hcdetail]")
    page.wait_for_timeout(350)
    return ctx, page


@pytest.mark.parametrize("width,limit", [(1440, 90), (390, 140)])
def test_trace_detail_compact(browser, width, limit):
    ctx, page = open_expanded(browser, width)
    d = page.evaluate(PROBE)
    page.close()
    ctx.close()

    assert d, (width, "detail not open")
    assert d["h"] <= limit, (width, d)
    assert d["sections"] == 2, (width, d)
    assert d["acts"] >= 1, (width, d)
    assert d["docDx"] <= 0, (width, d)
    if width == 1440:
        assert abs(d["w"] - d["rowW"]) <= 1.5, d
        assert d["actRightGap"] is not None and d["actRightGap"] <= 24, d


def test_negative_control_old_stacked_sections(browser):
    ctx, page = open_expanded(browser, 1440)
    page.add_style_tag(content=(
        "#hbody .hcdet{display:block!important;padding:2px 12px 12px!important}"
        "#hbody .hcd-sec{display:block!important;padding:12px 0!important;border-top:1px solid var(--r-hair)!important}"
        "#hbody .hcd-sum{margin:8px 0 4px!important}"
    ))
    page.wait_for_timeout(200)
    d = page.evaluate(PROBE)
    page.close()
    ctx.close()
    assert d["h"] >= 160, d
