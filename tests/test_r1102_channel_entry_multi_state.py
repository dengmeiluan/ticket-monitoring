# -*- coding: utf-8 -*-
"""r1102：渠道入口必须是单颗多态按钮。

用户要求：「渠道入口（打开）合并变成渠道入口按钮，点击打开，再点击关闭，
推崇按钮可以多态文案统一设计」。实测 390/1512：
  收起态「渠道入口」→ 点开「收起入口」→ 再点「渠道入口」；
  两态同宽 78px（4 字同长），面板在按钮下方 8–11px，不压按钮、不夹元素；
  面板内 10 家渠道名与 10 个官方图标齐全。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="渠道入口多态按钮依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [390, 1512]


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
    priv = tempfile.mkdtemp(prefix="r1102_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
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


STATE = """(() => {
  const s=document.getElementById('srxChLinksBtn');
  const p=document.getElementById('srxChLinksBox');
  const dr=document.getElementById('srxChLinksDrawer');
  const rb=s.getBoundingClientRect();
  const rp=dr?dr.getBoundingClientRect():null;
  return {txt:s.textContent.trim(),w:Math.round(rb.width),
    b:Math.round(rb.bottom),aria:s.getAttribute('aria-expanded'),
    panel:rp?{L:Math.round(rp.left),T:Math.round(rp.top),
      W:Math.round(rp.width),H:Math.round(rp.height),B:Math.round(rp.bottom)}:null,
    gap:0,
    names:p?p.querySelectorAll('.chband-name').length:0,
    icons:p?[...p.querySelectorAll('.chband-name img.bic')]
      .filter(i=>i.naturalWidth>0).length:0,
    over:document.documentElement.scrollWidth-innerWidth};
})()"""


def test_channel_entry_is_single_multi_state_button(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 1000},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.wait_for_timeout(1000)
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(700)
            pg.evaluate("()=>{const p=document.getElementById('srxProbe');"
                        "if(p&&!p.classList.contains('open'))"
                        "document.getElementById('srxProbeTool').click()}")
            pg.wait_for_timeout(450)
            pg.evaluate("()=>{const b=document.querySelector("
                        "'#searchview .srx-more-btn');"
                        "if(b&&!b.closest('.srx-hero-act')"
                        ".classList.contains('open'))b.click()}")
            pg.wait_for_timeout(350)
            a0 = pg.evaluate(STATE)
            pg.click("#srxChLinksBtn")
            pg.wait_for_timeout(650)
            a1 = pg.evaluate(STATE)
            # 窄档面板是浮层，可能盖住触发器；优先点面板自带的关闭 ×。
            try:
                pg.click("#srxChLinksBtn", timeout=1500)
            except Exception:
                pg.click("#srxChLinksDrawer .clx-x", timeout=3000)
            pg.wait_for_timeout(450)
            a2 = pg.evaluate(STATE)
            pg.close()
            if a0["txt"] != "渠道入口" or a0["aria"] != "false":
                bad.append("%d 初始态不是「渠道入口」: %s" % (w, a0))
            if a1["txt"] != "收起入口" or a1["aria"] != "true":
                bad.append("%d 打开态不是「收起入口」: %s" % (w, a1))
            if a2["txt"] != "渠道入口" or a2["aria"] != "false":
                bad.append("%d 再收起未回到「渠道入口」: %s" % (w, a2))
            if abs(a1["w"] - a0["w"]) > 1:
                bad.append("%d 两态按钮宽度跳变 %d→%d"
                           % (w, a0["w"], a1["w"]))
            if not a1["panel"] or a1["panel"]["H"] < 40:
                bad.append("%d 打开后面板不可见 %s" % (w, a1["panel"]))
            # r1122：≤560 渠道入口为底部 sheet（bottom:8px）；桌面浮动层贴
            # 触发器下方。两种稳定形态都合法，不允许出视口顶。
            else:
                sheet = a1["panel"]["B"] >= 984
                if a1["panel"]["T"] < 0 or not (sheet or a1["panel"]["T"] <= a1["b"] + 24):
                    bad.append("%d 面板位置异常 %s/%s" % (w, a1["panel"], a1["b"]))
            if a1["names"] != 10 or a1["icons"] != 10:
                bad.append("%d 面板渠道/图标 %d/%d（应 10/10）"
                           % (w, a1["names"], a1["icons"]))
            if a0["over"] > 1 or a1["over"] > 1:
                bad.append("%d 页面横向溢出 %d/%d"
                           % (w, a0["over"], a1["over"]))
        b.close()
    assert not bad, "渠道入口多态按钮: " + "；".join(bad)
