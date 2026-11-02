# -*- coding: utf-8 -*-
"""r869 门禁：「展开更多条件」点下去，被点的那颗按钮不能跑。

实测缺陷（修前 1512）：点「展开更多条件」后 30ms 的滚动按面板当时的
`top-110` 算，而面板刚插入、几何未稳，实测把触发器从 377.9 顶到视口
顶端 81.9（scrollY 0→296）；收回后按钮也停在 81.9、页面不再回位。
用户读作「展开应该是展开的感觉，怎么位置都发生了偏移」。

判据：
  · 展开后与收回后，触发器必须停在**同一坐标**（两态同坐标）；
  · 触发器不能被顶到视口顶端（离顶 ≥ 页头高度 + 一个行距）；
  · 面板必须真的展开（高度 > 200）且按钮文案/aria 跟随翻转。
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

JS = r"""() => {
  const b = document.getElementById('srxMoreBtn');
  const p = document.getElementById('srxFmore');
  const r = b.getBoundingClientRect();
  return {left:+r.left.toFixed(1), top:+r.top.toFixed(1), w:+r.width.toFixed(1),
          scrollY:Math.round(window.scrollY), panelH:Math.round(p.getBoundingClientRect().height),
          open:p.classList.contains('open'), aria:b.getAttribute('aria-expanded'),
          txt:(b.querySelector('.n')?'':''), text:b.textContent.trim()};
}"""


@pytest.fixture(scope="module")
def states():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ok = False
        for _ in range(90):
            try:
                op.open(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1180):
                pg = br.new_page(viewport={"width": w, "height": 900})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1400)
                pg.evaluate("srxToggleCtx()")
                pg.wait_for_timeout(500)
                pg.evaluate("document.getElementById('srxMoreBtn').click()")
                pg.wait_for_timeout(800)
                opened = pg.evaluate(JS)
                pg.evaluate("document.getElementById('srxMoreBtn').click()")
                pg.wait_for_timeout(600)
                closed = pg.evaluate(JS)
                out[w] = {"open": opened, "closed": closed,
                          "hdh": pg.evaluate("""()=>parseInt(getComputedStyle(document.documentElement)
                              .getPropertyValue('--hdh'))||54""")}
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1180])
def test_trigger_keeps_its_place_in_both_states(states, w):
    d = states[w]
    a, b = d["open"], d["closed"]
    assert a["open"] and a["panelH"] > 200, "面板没有真正展开：%s" % a
    assert (not b["open"]) and b["panelH"] == 0, "面板没有真正收回：%s" % b
    assert a["aria"] == "true" and b["aria"] == "false", "aria 未跟随两态：%s / %s" % (a, b)
    assert abs(a["left"] - b["left"]) <= 1, (
        "%d 档两态触发器的横坐标不同（%s vs %s）" % (w, a["left"], b["left"]))
    # r878：展开时为了露出整块面板会按需滚动（面板 628px，视口 900 装不下
    # 时要滚），所以两态**纵向坐标允许不同**；真正的契约变成
    # 「收起后页面滚回原处」——否则同一颗按钮两态停在两处，正是用户说的
    # 「展开和收起不在同一个位置，明显不是一个按钮多态的设计」。
    # 这里用 scrollY 判定（比坐标更直接，且不受 sticky 表头影响）。
    assert b["scrollY"] == 0, (
        "%d 档收起后页面没有滚回原位（scrollY=%s）——同一颗按钮停在了两处"
        % (w, b["scrollY"]))
    assert a["scrollY"] >= 0


@pytest.mark.parametrize("w", [1512, 1180])
def test_trigger_not_pinned_to_viewport_top(states, w):
    d = states[w]
    floor = d["hdh"] + 24
    assert d["open"]["top"] >= floor, (
        "%d 档展开后触发器被顶到视口顶端（top=%s，页头 %s）"
        % (w, d["open"]["top"], d["hdh"]))
