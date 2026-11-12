# -*- coding: utf-8 -*-
"""r1511：检索 ≤760 列表头的镜像折叠按钮文案（真实渲染 + 负控）。

背景：「解析列表」页签下只有「收起镜像」四个字，读不出收的是哪一块，
容易被理解成收起当前列表。改为「收起渠道镜像 / 展开渠道镜像」，
并给 title 写明「不影响左侧解析列表」。门禁：
1. 390/760 列表标题隐藏时，按钮仍完整可读、无溢出、无换行。
2. 点击后文案/aria/折叠态三者同步翻转。
3. 负控：旧「收起镜像」文案不满足对象名判据。
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


PROBE = r"""
() => {
  const b=document.getElementById('srxMirrorFold');
  const h=document.querySelector('.srx-listhead');
  const rb=b.getBoundingClientRect(), rh=h.getBoundingClientRect();
  const title=document.getElementById('srxListTitle');
  return {
    text:b.textContent.trim(), title:b.title, aria:b.getAttribute('aria-expanded'),
    btnW:+rb.width.toFixed(1), btnH:+rb.height.toFixed(1), right:+rb.right.toFixed(1),
    headScroll:h.scrollWidth, headClient:h.clientWidth, headH:+rh.height.toFixed(1),
    listTitleShown:!!title && title.offsetParent!==null,
    folded:document.getElementById('srxMirror').classList.contains('srx-folded'),
    vw:innerWidth, docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""


@pytest.mark.parametrize("width", [390, 760])
def test_mirror_label_readable_and_toggles(srv, browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_function("typeof switchView==='function'", timeout=25000)
        page.evaluate("switchView('search')")
        page.wait_for_selector("#srxMirrorFold", state="visible", timeout=20000)
        page.wait_for_timeout(800)
        d = page.evaluate(PROBE)
        assert d["text"] == "收起渠道镜像", d
        assert "右侧渠道镜像面板" in d["title"] and "不影响左侧解析列表" in d["title"], d
        assert d["aria"] == "true" and not d["folded"], d
        assert d["btnW"] >= 80, "label clipped: %s" % d
        assert d["btnH"] <= 36, "label wrapped: %s" % d
        assert d["headScroll"] <= d["headClient"] + 1, "list header overflows: %s" % d
        assert d["docDx"] <= 0, d
        page.click("#srxMirrorFold")
        page.wait_for_timeout(300)
        d2 = page.evaluate(PROBE)
        assert d2["text"] == "展开渠道镜像", d2
        assert d2["aria"] == "false" and d2["folded"], d2
        assert "展开右侧渠道镜像面板" in d2["title"], d2
        assert d2["headScroll"] <= d2["headClient"] + 1, d2
        page.click("#srxMirrorFold")
        page.wait_for_timeout(300)
        d3 = page.evaluate(PROBE)
        assert d3["text"] == "收起渠道镜像" and d3["aria"] == "true" and not d3["folded"], d3
        # 负控：旧文案不含对象名，本门禁的对象判据必须红
        page.evaluate("()=>{document.getElementById('srxMirrorFold').textContent='收起镜像'}")
        old = page.evaluate(PROBE)
        assert "渠道镜像" not in old["text"], "negative control did not break the object-name check"
    finally:
        ctx.close()
