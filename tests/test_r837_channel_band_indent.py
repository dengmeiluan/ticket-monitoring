# -*- coding: utf-8 -*-
"""r837 门禁：渠道入口卡里「次行入口」必须与「主入口 chip」左缘同线。

实测缺陷（1512）：主入口 chip 左缘 477.5，次行「PC · H5 · 特价」的链接
左缘 487.5——差 10px 来自 `.chband-specs` 自带的 `padding:0 10px`。
两行同属一栏，用户读作「缩进没对齐、只扁平了但没有对齐布局」。

同时守「五条带等高」：r541 靠 chip 单行 + 固定行高做到 5/5 同为 91px，
任何让 band 高矮不一的改动都算回归。
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
  const R=e=>{const b=e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), h:+b.height.toFixed(1)};};
  const bands=[...document.querySelectorAll('#cfgChannelLinks .chband')];
  return bands.map(bd=>{
    const chip=bd.querySelector('.chband-grid .chlink');
    const spec=bd.querySelector('.chband-specs .chlink');
    return {band:R(bd), chip:chip?R(chip):null, spec:spec?R(spec):null};
  });
}"""


@pytest.fixture(scope="module")
def probe():
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
            for w in (1512, 1280):
                pg = br.new_page(viewport={"width": w, "height": 1500})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('cfg')")
                pg.wait_for_timeout(1400)
                pg.evaluate("""()=>{const b=document.querySelector('#cfgnav .cnav[data-p="login"]');
                    if(b)b.click();}""")
                pg.wait_for_timeout(1200)
                out[w] = pg.evaluate(JS)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1280])
def test_secondary_entries_share_the_chip_left_edge(probe, w):
    rows = probe[w]
    assert rows, "%d 档没有量到渠道带" % w
    bad = [(r["chip"]["l"], r["spec"]["l"]) for r in rows
           if r["chip"] and r["spec"] and abs(r["chip"]["l"] - r["spec"]["l"]) > 1]
    assert not bad, (
        "%d 档次行入口与主入口 chip 左缘不齐（chip_l, spec_l）：%s" % (w, bad))


@pytest.mark.parametrize("w", [1512, 1280])
def test_channel_bands_keep_one_height(probe, w):
    rows = probe[w]
    hs = sorted({r["band"]["h"] for r in rows})
    assert len(hs) == 1, (
        "%d 档五条渠道带高矮不一：%s——用户读作「大小布局不够对称协调」" % (w, hs))
