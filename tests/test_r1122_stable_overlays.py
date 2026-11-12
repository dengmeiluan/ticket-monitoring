# -*- coding: utf-8 -*-
"""r1122：检索页的临时控件一律住浮层，展开/收起不得推动正文。

用户原话：不要「隐藏出现挤压」，要小悬浮窗/弹窗的稳定展示交互；
顶部出发/到达不得贴边。门禁覆盖：
1) 探针渠道选择：打开前后 document.scrollHeight 不变，面板 fixed 且在视口内；
2) 组合队列：打开前后正文高度不变（绝对浮层）；
3) 渠道入口：打开前后正文高度不变（fixed 浮层 / 手机底部 sheet）；
4) 筛选展开体：fixed 浮层（手机为 sheet），不把结果列表当内容撑高；
5) 探针卡有上内衬：表单顶 > 卡顶（输入行不贴白卡上缘）。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    url = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(90):
            try:
                op.open(url + "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.skip("demo 服务未起来")
        yield url
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


SNAP = r"""() => {
  const q=s=>document.querySelector(s);
  const rr=el=>{if(!el)return null;const b=el.getBoundingClientRect();
    return {l:+b.left.toFixed(0),t:+b.top.toFixed(0),r:+b.right.toFixed(0),b:+b.bottom.toFixed(0),
      w:+b.width.toFixed(0),h:+b.height.toFixed(0),pos:getComputedStyle(el).position,
      disp:getComputedStyle(el).display};};
  const probe=q('#srxProbe'), form=q('#srxProbeForm');
  return {sh:document.documentElement.scrollHeight,vw:innerWidth,vh:innerHeight,
    over:document.documentElement.scrollWidth-innerWidth,
    probe:rr(probe),form:rr(form),
    plat:rr(q('#srxPlatPop')),batch:rr(q('#srxBatchDock')),
    ch:rr(q('#srxChLinksDrawer')),fly:rr(q('#srxCtxFly'))};
}"""


def _open_probe(pg):
    pg.evaluate("()=>{const p=document.getElementById('srxProbe');"
                "if(p&&!p.classList.contains('open'))document.getElementById('srxProbeTool').click()}")
    pg.wait_for_timeout(500)


def _open_more(pg):
    pg.evaluate("()=>{const b=document.querySelector('#searchview .srx-more-btn');"
                "if(b&&!b.closest('.srx-hero-act').classList.contains('open'))b.click()}")
    pg.wait_for_timeout(350)


@pytest.mark.parametrize("w", [1512, 390])
def test_transient_panels_do_not_push_content(base, w):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": w, "height": 950})
        pg.goto(base + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(900)
        pg.evaluate("switchView('search')")
        pg.wait_for_timeout(700)
        _open_probe(pg)
        a0 = pg.evaluate(SNAP)
        # 探针卡内衬：表单顶至少低于卡顶 6px
        assert a0["form"]["t"] - a0["probe"]["t"] >= 6, (w, a0["probe"], a0["form"])

        # 探针渠道：2026-11-07 起是首屏 10 渠道 rail（无浮层）。
        # 勾选/取消一个 chip 不得改变正文高度或产生横向溢出。
        before = pg.evaluate(SNAP)["sh"]
        chips = pg.evaluate("()=>document.querySelectorAll('#srxPlatPick .srx-pchip').length")
        assert chips == 10, (w, "渠道 rail 数量", chips)
        pg.evaluate("()=>{const i=document.querySelector('#srxPlatPick .srx-pchip input');"
                    "if(i)i.click()}")
        pg.wait_for_timeout(300)
        a = pg.evaluate(SNAP)
        assert a["sh"] == before, (w, "渠道勾选把正文撑高", before, a["sh"])
        assert a["over"] <= 1, (w, "渠道勾选横向溢出", a["over"])
        pg.evaluate("()=>{const i=document.querySelector('#srxPlatPick .srx-pchip input');"
                    "if(i)i.click()}")
        pg.wait_for_timeout(200)

        # 组合队列
        before = pg.evaluate(SNAP)["sh"]
        pg.evaluate("()=>document.getElementById('srxBatchToggle')?.click()")
        pg.wait_for_timeout(350)
        a = pg.evaluate(SNAP)
        assert a["sh"] == before, (w, "组合队列把正文撑高", before, a["sh"])
        assert a["batch"] and a["batch"]["pos"] == "absolute"
        pg.evaluate("()=>{if(SRX.batchOpen){SRX.batchOpen=false;srxBatchRender()}}")
        pg.wait_for_timeout(200)

        # 渠道入口
        if w <= 1200:
            _open_more(pg)
        before = pg.evaluate(SNAP)["sh"]
        pg.evaluate("()=>document.getElementById('srxChLinksBtn').click()")
        pg.wait_for_timeout(600)
        a = pg.evaluate(SNAP)
        assert a["sh"] == before, (w, "渠道入口把正文撑高", before, a["sh"])
        assert a["ch"] and a["ch"]["pos"] == "fixed"
        assert a["ch"]["b"] <= a["vh"] + 1 and a["ch"]["l"] >= -1 and a["ch"]["r"] <= a["vw"] + 1
        pg.evaluate("()=>srxChLinksClose()")
        pg.wait_for_timeout(250)

        # 筛选展开体
        pg.evaluate("()=>{const b=document.getElementById('srxFilterBtn');"
                    "if(b&&b.offsetParent!==null)b.click()}")
        pg.wait_for_timeout(450)
        a = pg.evaluate(SNAP)
        assert a["fly"] and a["fly"]["pos"] == "fixed", (w, "筛选展开体不是浮层", a["fly"])
        assert a["fly"]["l"] >= -1 and a["fly"]["r"] <= a["vw"] + 1 and a["fly"]["t"] >= 0
        assert a["over"] <= 1, (w, "浮层导致横向溢出", a["over"])
        b.close()
