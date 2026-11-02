# -*- coding: utf-8 -*-
"""r811 门禁：配置页 900px 精确断点不许「两边都命中」。

实测缺陷（修前 900 档）：
  · 2097 行 `@media(max-width:900px)` 把 `.cfglayout` 收成 `minmax(0,1fr)`；
  · 5518 行 `@media(min-width:900px)` 又把它设回 `188px + 1fr`。
  两条在 **900px 精确宽度下同时为真**，后写的 min-width 那条胜出，
  于是 `.cfglayout` 仍是两列 188px；可 `.cfgnav` 的横排规则
  （`flex-direction:row` + 每项 `flex:1 1 0`）没被覆盖——
  4 个导航项在 188px 里各分到 **35px**，而「用户与航线」需要 58px
  （scrollW 58 > clientW 33），文字全部溢出压到隔壁。
  760/600/390 档是单列铺满（每项 170/130/77px），只有 900 这一个点坏。

判据（渲染几何）：
  1. 900 档 `.cfglayout` 必须是**单列**（计算后的列数 == 1）；
  2. 900 档每个 `.cnav` 文字放得下（scrollWidth <= clientWidth + 1）；
  3. 1024 档仍是两列 188px（证明修正没有把桌面布局一起改掉）。
负控：把 `min-width:901px` 注回 `min-width:900px`，900 档必红。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M = r"""() => {
  const lay = document.querySelector('#cfgview .cfglayout');
  const nav = document.querySelector('#cfgview .cfgnav');
  if (!lay || !nav) return {err: 'no cfglayout/cfgnav'};
  const cols = getComputedStyle(lay).gridTemplateColumns.trim().split(/\s+/);
  const items = [...nav.querySelectorAll('.cnav')].map(e => {
    const r = e.getBoundingClientRect();
    return {txt: (e.textContent || '').trim().slice(0, 10),
            w: +r.width.toFixed(1), scrollW: e.scrollWidth, clientW: e.clientWidth,
            lost: e.scrollWidth - e.clientWidth};
  });
  return {nCols: cols.length, cols: cols.join(' '),
          navW: +nav.getBoundingClientRect().width.toFixed(1), items};
}"""

REVERT = ("@media(min-width:900px) and (max-width:901px){"
          ".cfglayout{grid-template-columns:188px minmax(0,1fr)!important}}")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def probe():
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.4)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (900, 1024, 780):
                pg = br.new_page(viewport={"width": w, "height": 1200})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('cfg')")
                pg.wait_for_timeout(1800)
                out[w] = pg.evaluate(M)
                if w == 900:
                    pg.add_style_tag(content=REVERT)
                    pg.wait_for_timeout(400)
                    out["revert"] = pg.evaluate(M)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [900, 780])
def test_900_breakpoint_is_single_column(probe, w):
    d = probe[w]
    assert "err" not in d, d
    assert d["nCols"] == 1, (
        "%d 档 cfglayout 是 %d 列（%s）——窄档应为单列"
        % (w, d["nCols"], d["cols"]))
    bad = [x for x in d["items"] if x["lost"] > 1]
    assert not bad, (
        "%d 档导航项文字放不下：%s" % (w, json.dumps(bad, ensure_ascii=False)))


def test_desktop_still_two_columns(probe):
    d = probe[1024]
    assert "err" not in d, d
    assert d["nCols"] == 2, (
        "1024 档 cfglayout 变成 %d 列（%s）——桌面两列布局被误改"
        % (d["nCols"], d["cols"]))
    assert d["cols"].split(" ")[0] == "188px", (
        "1024 档侧栏列宽变成 %s（应为 188px）" % d["cols"].split(" ")[0])


def test_negative_control_two_columns_at_900_breaks_nav(probe):
    """负控：把两列布局注回 900，导航必须重新放不下。"""
    d = probe["revert"]
    assert d["nCols"] == 2, (
        "负控没生效：注回两列后仍是 %d 列（%s）" % (d["nCols"], d["cols"]))
    bad = [x for x in d["items"] if x["lost"] > 1]
    assert bad, (
        "负控无效：900 档两列布局下导航仍放得下（%s）"
        % json.dumps(d["items"], ensure_ascii=False))
