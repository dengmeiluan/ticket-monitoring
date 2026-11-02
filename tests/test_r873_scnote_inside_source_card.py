# -*- coding: utf-8 -*-
"""r873 门禁：检索页「展开说明」，说明必须长在触发器的正下方。

用户实报两段：「说明的展开是在检索控制台的下面！展开收起怎么能中间有元素呢？
然后排版位置呢？！」修前实测（1512）：触发器在来源条里（卡 540.2~1147.6），
说明却是 `#healthDiag` 的直接子级，展开后铺满整行
（left=107.5 / width=1287）——说明与触发器分属两处，中间还压着整条卡头。

判据（渲染几何，不看 CSS 声明）：
  1. 说明盒必须**整块落在来源条内**（left ≥ 卡左缘、right ≤ 卡右缘）；
  2. 说明宽度必须接近卡宽（≥ 卡宽 − 24，即只让出左右内衬），
     不允许缩成一小块浮在整行中间；
  3. 说明与触发器之间**不得夹着别的东西**：说明顶 − 触发器底 ≤ 12px
     （= 触发器行的下内衬），且 `elementFromPoint` 命中的就是说明本身；
  4. 触发器两态坐标完全一致（展开不能把按钮顶走）；
  5. 收起后来源条高度回到初始值（不留常驻空档）。

负控：把说明从 `#srccap` 挪回 `#healthDiag` 直接子级再展开，
第 1/2 条必须判红（证明判据真的连在产品上）。
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


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

SNAP = r"""() => {
  const b = document.getElementById('scNoteBtn');
  const n = document.getElementById('scNote');
  const cap = document.getElementById('srccap');
  const R = e => { const r = e.getBoundingClientRect();
    return {l:+r.left.toFixed(1), r:+r.right.toFixed(1), t:+r.top.toFixed(1),
            b:+r.bottom.toFixed(1), w:+r.width.toFixed(1), h:+r.height.toFixed(1)}; };
  const nr = n.getBoundingClientRect(), br = b.getBoundingClientRect(), cr = cap.getBoundingClientRect();
  const vis = getComputedStyle(n).display !== 'none';
  let hit = null;
  if (vis) {
    const x = nr.left + Math.min(24, nr.width / 2), y = nr.top + nr.height / 2;
    const el = document.elementFromPoint(x, y);
    hit = el ? (el.id || (el.closest('#scNote') ? 'scNote-child' : el.className || el.tagName)) : null;
  }
  return {btn:R(b), note:R(n), cap:R(cap), vis,
          gap:+(nr.top-br.bottom).toFixed(1),
          inside:(nr.left >= cr.left-0.6 && nr.right <= cr.right+0.6),
          noteW:+nr.width.toFixed(1), capW:+cr.width.toFixed(1),
          hit, aria:b.getAttribute('aria-expanded'), txt:b.textContent.trim(),
          capPadB:getComputedStyle(cap).paddingBottom};
}"""


@pytest.fixture(scope="module")
def states():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1024, 900, 390):
                pg = br.new_page(viewport={"width": w, "height": 1000})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(900)
                pg.evaluate("showMonTab('health')")
                pg.wait_for_timeout(1400)
                closed = pg.evaluate(SNAP)
                pg.evaluate("document.getElementById('scNoteBtn').click()")
                pg.wait_for_timeout(420)
                opened = pg.evaluate(SNAP)
                pg.evaluate("document.getElementById('scNoteBtn').click()")
                pg.wait_for_timeout(420)
                reclosed = pg.evaluate(SNAP)
                neg = pg.evaluate("""() => {
                  const n = document.getElementById('scNote');
                  const d = document.getElementById('healthDiag');
                  d.appendChild(n);
                  document.getElementById('scNoteBtn').click();
                  const b = document.getElementById('scNoteBtn');
                  const cap = document.getElementById('srccap');
                  const nr = n.getBoundingClientRect(), cr = cap.getBoundingClientRect();
                  const br = b.getBoundingClientRect();
                  const res = {l:+nr.left.toFixed(1), w:+nr.width.toFixed(1),
                               capW:+cr.width.toFixed(1),
                               gap:+(nr.top-br.bottom).toFixed(1),
                               inside:(nr.left >= cr.left-0.6 && nr.right <= cr.right+0.6)};
                  b.click();
                  return res;
                }""")
                out[w] = {"closed": closed, "open": opened, "reclosed": reclosed, "neg": neg}
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1024, 900, 390])
def test_note_sits_inside_source_card(states, w):
    d = states[w]
    a = d["open"]
    assert a["vis"], "%d 档说明没有展开：%s" % (w, a)
    assert a["inside"], (
        "%d 档说明跑出了来源条：note %s~%s vs 卡 %s~%s"
        % (w, a["note"]["l"], a["note"]["r"], a["cap"]["l"], a["cap"]["r"]))
    assert a["noteW"] >= a["capW"] - 24.5, (
        "%d 档说明宽度没跟卡对齐（说明 %s / 卡 %s）" % (w, a["noteW"], a["capW"]))


@pytest.mark.parametrize("w", [1512, 1024, 900, 390])
def test_nothing_between_trigger_and_note(states, w):
    d = states[w]
    a = d["open"]
    assert a["gap"] <= 12.5, (
        "%d 档触发器底到说明顶之间夹了 %spx" % (w, a["gap"]))
    assert a["gap"] >= -0.6, "%d 档说明压住了触发器：%s" % (w, a["gap"])
    assert a["hit"] in ("scNote", "scNote-child"), (
        "%d 档说明位置命中的不是说明本身（hit=%s）" % (w, a["hit"]))


@pytest.mark.parametrize("w", [1512, 1024, 900, 390])
def test_trigger_stays_put_and_card_restores(states, w):
    d = states[w]
    c, a, z = d["closed"], d["open"], d["reclosed"]
    assert abs(a["btn"]["l"] - c["btn"]["l"]) <= 0.6, (
        "%d 档展开把触发器横移了（%s→%s）" % (w, c["btn"]["l"], a["btn"]["l"]))
    assert abs(a["btn"]["t"] - c["btn"]["t"]) <= 0.6, (
        "%d 档展开把触发器纵移了（%s→%s）" % (w, c["btn"]["t"], a["btn"]["t"]))
    assert a["aria"] == "true" and z["aria"] == "false", (
        "%d 档 aria 未跟随两态：%s / %s" % (w, a["aria"], z["aria"]))
    assert a["txt"] == "收起说明" and z["txt"] == "展开说明", (
        "%d 档文案未跟随两态：%s / %s" % (w, a["txt"], z["txt"]))
    assert abs(z["cap"]["h"] - c["cap"]["h"]) <= 0.6, (
        "%d 档收起后来源条没回到原高度（%s→%s）" % (w, c["cap"]["h"], z["cap"]["h"]))


@pytest.mark.parametrize("w", [1512, 1024, 900, 390])
def test_negative_control_note_outside_card_goes_red(states, w):
    """负控：说明挪回 #healthDiag 直接子级，判据 1/2/3 至少一条必须判红。

    窄档卡本身接近满宽（390 档卡 324 / 视口 390），所以「是否落在卡内」
    单独不成立——必须把「与触发器之间夹了东西」也算进负控，否则判据在
    窄档没有区分力。
    """
    neg = states[w]["neg"]
    assert (not neg["inside"]) or neg["w"] < neg["capW"] - 24.5 or neg["gap"] > 12.5, (
        "%d 档负控没有触发——判据没连在产品上：%s" % (w, neg))
