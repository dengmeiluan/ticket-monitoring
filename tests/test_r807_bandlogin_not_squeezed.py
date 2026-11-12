# -*- coding: utf-8 -*-
"""r807 门禁：窄档（≤900）价带头里的「渠道登录」不得被挤成竖排/截断。

实测缺陷（修前）：
  · `.srx-bandlogin` 的 `grid-area:4/2/5/3` 是给宽档三列写的；窄档这里
    三列实际是 `294px 8px 62px`（430）/`254px 8px 62px`（390），
    第 2 列只剩 **8px**：scrollWidth 15 > clientWidth 8 → 文字被裁，
    截图里「渠道」二字被压成竖排两行。
  · 更严重的是它与第 4 行第 1 列的 `.srx-axis`（出发日/采集日）
    **纵向重叠 25px**（900/600 档同样重叠）——两个控件叠在一起。

判据（渲染几何，两条）：
  1. `scrollWidth <= clientWidth + 1`（文字不被裁）；
  2. 与 `.srx-axis` 的矩形不相交（纵向不重叠），且位于其下方（gap ≥ 0）。
负控：把 grid-area 注回 `4/2/5/3`，窄档必须重新出现「截断 或 重叠」。
宽档（≥1024）只在负控之外做一次「未截断」检查，绑定布局不被这条规则影响。
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
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && e.offsetParent !== null; };
  const b = document.querySelector('#srxBand .srx-bandlogin');
  if (!b || !vis(b)) return {n: 0};
  const r = b.getBoundingClientRect();
  const ax = document.querySelector('#srxBand .srx-axis');
  const ar = ax && vis(ax) ? ax.getBoundingClientRect() : null;
  return {n: 1,
          w: +r.width.toFixed(1), t: +r.top.toFixed(1), l: +r.left.toFixed(1),
          scrollW: b.scrollWidth, clientW: b.clientWidth,
          trunc: b.scrollWidth > b.clientWidth + 1,
          overlapAxis: ar ? (r.top < ar.bottom - 1 && r.bottom > ar.top + 1) : false,
          gapToAxis: ar ? +(r.top - ar.bottom).toFixed(1) : null,
          gridArea: getComputedStyle(b).gridArea};
}"""

REVERT = ("@media(max-width:900px){"
          "#searchview #srxBand .srx-band-h>.srx-bandlogin{"
          "grid-area:4/2/5/3!important;justify-self:auto!important}}")


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
            for w in (1512, 900, 600, 430, 390, 320):
                pg = br.new_page(viewport={"width": w, "height": 1200})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                pg.evaluate("()=>{try{srxToggleOverview()}catch(e){}}")
                pg.wait_for_timeout(1000)
                out[w] = pg.evaluate(M)
                if w <= 900:
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


@pytest.mark.parametrize("w", [900, 600, 430, 390, 320])
def test_narrow_bandlogin_is_not_squeezed(probe, w):
    d = probe[w]
    assert d.get("n") == 1, "%d 档价带头没渲染出「渠道登录」" % w
    assert not d["trunc"], (
        "%d 档「渠道登录」被裁：scrollWidth %s > clientWidth %s"
        % (w, d["scrollW"], d["clientW"]))
    assert not d["overlapAxis"], (
        "%d 档「渠道登录」与「出发日/采集日」纵向重叠（gapToAxis=%s）"
        % (w, d["gapToAxis"]))
    assert d["gapToAxis"] is not None and d["gapToAxis"] >= 0, (
        "%d 档「渠道登录」没有落在轴下方：gapToAxis=%s"
        % (w, d["gapToAxis"]))


@pytest.mark.parametrize("w", [900, 600, 430, 390, 320])
def test_negative_control_old_grid_area_squeezes_again(probe, w):
    """负控：把 grid-area 注回 4/2/5/3，必须重新出现截断或重叠。"""
    d = probe["revert"][w]
    assert d.get("n") == 1, "%d 档负控里没有渠道登录" % w
    assert d["trunc"] or d["overlapAxis"], (
        "%d 档负控无效：注回 4/2/5/3 后既不截断也不重叠（w=%s trunc=%s overlap=%s）"
        % (w, d["w"], d["trunc"], d["overlapAxis"]))


def test_wide_bandlogin_still_readable(probe):
    """宽档：绑定布局未被窄档规则影响，文字仍完整。"""
    d = probe[1512]
    assert d.get("n") == 1, "1512 档价带头没有「渠道登录」"
    assert not d["trunc"], (
        "1512 档「渠道登录」被裁：scrollWidth %s > clientWidth %s"
        % (d["scrollW"], d["clientW"]))
    assert d["gridArea"].replace(" ", "") == "4/2/5/3", (
        "1512 档 grid-area 变了（%s）——窄档规则泄漏到宽档" % d["gridArea"])
