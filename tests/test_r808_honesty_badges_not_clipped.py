# -*- coding: utf-8 -*-
"""r808 门禁：窄档英雄区小字行不得把「演示数据 · 合成」硬切掉半句。

实测缺陷（修前）：
  `@media(max-width:560px)` 给 `.srx-eyebrow` 写的是
  `flex-wrap:nowrap` + 父级 `overflow:hidden` / `text-overflow:ellipsis`。
  **ellipsis 只对父级直接文本节点生效**，而这一行四个成员全是子 span，
  于是变成硬切且无省略号：
    · 430 档「演示数据 · 合成」被切掉「合成」（scrollW 87 > clientW 65），
      同行的 heroMeta 也被切；
    · 390 档同样（87 > 58）；
    · 320 档连 DEMO 徽标都被切（43 > 37）。
  「演示数据 · 合成」是**数据诚信标记**——切掉后半句等于说了半句假话。

修法：窄档允许换行（段内仍 nowrap），让四段各自完整；长航线名交给
`#srxHeroMeta` 的 ellipsis（有意省略）。

判据（渲染几何）：
  1. `#srxLiveTag` / `#srxModeLabel` 必须 `scrollWidth <= clientWidth + 1`
     ——这两个是诚信标记，任何宽度下都不许裁；
  2. `#srxHeroMeta` 允许 ellipsis，但要真的**带省略号**（computed
     `text-overflow === 'ellipsis'` 且 `overflow !== 'visible'`），
     不许「溢出到父级外被硬切」。
负控：把 `flex-wrap` 注回 `nowrap`，430/390 必须重新裁切。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M = r"""() => {
  const eb = document.querySelector('#searchview .srx-hero-copy .srx-eyebrow');
  if (!eb) return {err: 'no eyebrow'};
  const g = id => {
    const e = document.getElementById(id);
    if (!e) return null;
    const cs = getComputedStyle(e);
    return {scrollW: e.scrollWidth, clientW: e.clientWidth,
            trunc: e.scrollWidth > e.clientWidth + 1,
            textOverflow: cs.textOverflow, overflow: cs.overflow,
            txt: (e.textContent || '').trim()};
  };
  const r = eb.getBoundingClientRect();
  return {h: +r.height.toFixed(1), wrap: getComputedStyle(eb).flexWrap,
          live: g('srxLiveTag'), mode: g('srxModeLabel'),
          meta: g('srxHeroMeta')};
}"""

REVERT = ("@media(max-width:560px){"
          "#searchview .srx-hero-copy .srx-eyebrow{flex-wrap:nowrap!important}}")


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
            for w in (560, 430, 390, 320):
                pg = br.new_page(viewport={"width": w, "height": 1100})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                out[w] = pg.evaluate(M)
                pg.add_style_tag(content=REVERT)
                pg.wait_for_timeout(400)
                out.setdefault("revert", {})[w] = pg.evaluate(M)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [560, 430, 390, 320])
def test_honesty_badges_are_never_clipped(probe, w):
    d = probe[w]
    assert "err" not in d, d
    for key in ("live", "mode"):
        b = d[key]
        assert b, "%d 档找不到 %s" % (w, key)
        assert not b["trunc"], (
            "%d 档诚信标记「%s」被裁：scrollWidth %s > clientWidth %s"
            % (w, b["txt"], b["scrollW"], b["clientW"]))


@pytest.mark.parametrize("w", [560, 430, 390, 320])
def test_hero_meta_truncates_with_ellipsis_not_hard_cut(probe, w):
    """航线/日期可省，但必须真带省略号——不能被父级 overflow 硬切。"""
    d = probe[w]
    m = d.get("meta")
    if not m or not m["trunc"]:
        return
    assert m["textOverflow"] == "ellipsis" and m["overflow"] != "visible", (
        "%d 档 heroMeta 溢出（%s>%s）却没有省略号：text-overflow=%s overflow=%s"
        % (w, m["scrollW"], m["clientW"], m["textOverflow"], m["overflow"]))


@pytest.mark.parametrize("w", [430, 390, 320])
def test_negative_control_nowrap_clips_again(probe, w):
    """负控：注回 nowrap，诚信标记必须重新被裁。"""
    d = probe["revert"][w]
    assert d["wrap"] == "nowrap", "%d 档负控的 nowrap 没生效" % w
    clipped = [k for k in ("live", "mode")
               if d.get(k) and d[k]["trunc"]]
    assert clipped, (
        "%d 档负控无效：注回 nowrap 后 %s 仍不裁，说明判据没量到 flex-wrap"
        % (w, ["live", "mode"]))
