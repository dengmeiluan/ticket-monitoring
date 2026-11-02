# -*- coding: utf-8 -*-
"""r801 门禁：检索页 `.srx-chip` 在触控档的有效命中高度必须 ≥ 32px。

背景：390/430 档 coarse 下 chip 只有 26px，指尖落点偏一点就点不中。
项目里其它小控件用 `::after` 伪元素撑高（不占版面），**这里不成立**：
日期 chip 的容器 `.srx-band-days` 在窄档带 `mask-image` 渐隐，遮罩把后代
的绘制与命中一起裁到边框盒内——实测 33px 红伪元素只画出 26 行（=盒高），
盒子外 elementFromPoint 直接穿透到父容器。所以改为直接提盒高。

判据：elementFromPoint 上下探测「有效命中高度」（盒内 + 上下探出）≥ 32。
负控：把盒高回退到 25px 并加回旧伪元素写法，effH 必须掉回 26，
证明判据量的是盒高本身、而不是恒真的量法。
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

MEASURE = r"""() => {
  const vis = e => e.getBoundingClientRect().height > 1 && e.offsetParent !== null;
  const hit = (e, x, y) => { const t = document.elementFromPoint(x, y);
    return !!t && (t === e || e.contains(t)); };
  const chips = [...document.querySelectorAll('#searchview .srx-chip')].filter(vis);
  const rows = chips.map(e => {
    const r = e.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) return null;
    let up = 0, dn = 0;
    const mid = hit(e, cx, cy);
    if (mid) {
      for (let d = 1; d <= 12; d++) { if (hit(e, cx, r.top - d)) up = d; else break; }
      for (let d = 1; d <= 12; d++) { if (hit(e, cx, r.bottom - 1 + d)) dn = d; else break; }
    }
    return {t: (e.textContent || '').trim().slice(0, 10), boxH: Math.round(r.height),
            up, dn, effH: mid ? Math.round(r.height) + up + dn : -1, mid};
  }).filter(Boolean);
  const days = document.getElementById('srxBandDays');
  return {coarse: matchMedia('(pointer:coarse)').matches, n: rows.length, rows,
          daysH: days ? Math.round(days.getBoundingClientRect().height) : null,
          daysScrollX: days ? days.scrollWidth - days.clientWidth : null};
}"""

# 负控：还原 r801 之前的写法（25px 盒 + 伪元素撑高）
REVERT = """
#searchview .srx-chip{min-height:25px!important}
#searchview .srx-chip{position:relative}
#searchview .srx-chip::after{content:"";position:absolute;left:0;right:0;
 top:50%;height:36px;transform:translateY(-50%)}
"""


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
            for w in (430, 390):
                # has_touch+is_mobile 才能让 matchMedia('(pointer:coarse)') 为真
                ctx = br.new_context(viewport={"width": w, "height": 950},
                                     has_touch=True, is_mobile=True)
                pg = ctx.new_page()
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3200)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                # 概览默认收起时日期 chip 在 display:none 里，先展开
                pg.evaluate("(()=>{try{srxToggleOverview()}catch(e){}})()")
                pg.wait_for_timeout(1100)
                out[w] = pg.evaluate(MEASURE)
                pg.add_style_tag(content=REVERT)
                pg.wait_for_timeout(400)
                out.setdefault("revert", {})[w] = pg.evaluate(MEASURE)
                ctx.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [430, 390])
def test_chip_touch_target_at_least_32(probe, w):
    d = probe[w]
    assert d["coarse"], "%d 档触控仿真没生效（matchMedia 为 false），本档无结论" % w
    assert d["n"] >= 2, "%d 档展开概览后可见 chip 只有 %d 个" % (w, d["n"])
    small = [r for r in d["rows"] if r["effH"] < 32]
    assert not small, (
        "%d 档有 %d 颗 chip 有效命中高度 < 32px：%s"
        % (w, len(small), json.dumps(small, ensure_ascii=False)))
    assert all(r["mid"] for r in d["rows"]), (
        "%d 档有 chip 中心点就命不中自己（探测无意义）：%s"
        % (w, json.dumps(d["rows"], ensure_ascii=False)))
    # 提盒高不能把日期行挤出横向滚动条
    assert d["daysScrollX"] is not None and d["daysScrollX"] <= 0, (
        "%d 档日期行出现横向溢出 %spx（提盒高不该改横向）" % (w, d["daysScrollX"]))


@pytest.mark.parametrize("w", [430, 390])
def test_negative_control_pseudo_element_really_fails(probe, w):
    """负控：旧写法（25px 盒 + ::after 撑高）必须仍然 < 32px。

    若这条挂了，说明遮罩裁切的前提变了（例如 `.srx-band-days` 的
    mask-image 被移除）——那时可以改用伪元素手法，但必须先重新实测。
    """
    d = probe["revert"][w]
    assert d["n"] >= 2, "%d 档负控没有可见 chip" % w
    assert all(r["effH"] < 32 for r in d["rows"]), (
        "%d 档负控无效：撤掉盒高后 chip 有效命中仍 ≥32px（%s），"
        "说明判据没量到盒高本身" % (w, json.dumps(d["rows"], ensure_ascii=False)))
