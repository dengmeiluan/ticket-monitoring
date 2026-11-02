# -*- coding: utf-8 -*-
"""r872 门禁：配置页每一层可见文字必须落在同一条左缘。

实测缺陷（修前 1512，用户与航线）：
  · 卡头文字 311.5、分组标题 327.5、设置行 327.5、设置行首元素 329.5、
    航线行 311.5 —— 同一张卡里两条竖线，最大差 18px（用户：
    「配置页的交互排版层级似乎被改坏了，也没有对齐了」）。
  根因是卡体包裹层用**内联** `padding:4px 16px 14px`（内联压过任何选择器），
  加上 `.ucard{padding:16px 18px}` 只作用在卡头与直挂的 .rline 上。

判据走渲染几何：取每层**第一个可见子元素**的左缘（不是容器边），
逐档比较，差 ≤2px 视为同线。另查首字是否被裁（scrollWidth 溢出）。
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
  const vis = e => e.offsetParent !== null && e.getBoundingClientRect().height > 1;
  // 首字左缘：取元素内第一个非空文本节点的 Range（容器边不算）
  const textLeft = (el) => {
    if (!el) return null;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (!(n.nodeValue || '').trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      const r = rg.getBoundingClientRect();
      if (r.width < 1) continue;
      return +r.left.toFixed(1);
    }
    return null;
  };
  const main = document.getElementById('cfgmain');
  const panes = [...main.querySelectorAll('.cfpanel')].filter(vis);
  const pane = panes[0] || main;
  const pick = sel => [...pane.querySelectorAll(sel)].filter(vis)[0] || null;
  /* 只比「卡内正文类」三层：卡头 / 分组标题 / 设置行 / 参数格。
     .rline 可能取到卡头所在行或标题行（语义与正文行不同），不参与同线比较。 */
  /* 分组标题的「首元素」是 A/B/C 序号徽标（它自带 8px 内衬），
     按盒左缘量，才能和卡头可见文字比同一条竖线。 */
  const g = pick('.grouplab');
  const gno = g ? [...g.children].find(k => k.classList.contains('no')) : null;
  const layers = {
    uhead: textLeft(pick('.uhead')),
    grouplab: gno ? +gno.getBoundingClientRect().left.toFixed(1) : textLeft(g),
    srow: textLeft(pick('.srow .slab, .srow')),
    glcell: textLeft(pick('.glcell')),
  };
  const clipped = [];
  ['.uhead .zh', '.grouplab .zh', '.srow .slab b', '.glcell .glab, .glcell label'].forEach(sel => {
    const el = pick(sel);
    if (!el) return;
    if (el.scrollWidth > el.clientWidth + 1)
      clipped.push({sel, sw: el.scrollWidth, cw: el.clientWidth});
  });
  return {layers, clipped};
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
            for w in (1512, 1180, 900):
                pg = br.new_page(viewport={"width": w, "height": 1200})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('cfg')")
                pg.wait_for_timeout(1200)
                out[w] = {}
                for p in ("users", "pacing", "globals", "login"):
                    pg.evaluate("""(p)=>{const b=document.querySelector(
                        '#cfgview .cfgnav .cnav[data-p="'+p+'"]'); if(b)b.click();}""", p)
                    pg.wait_for_timeout(800)
                    out[w][p] = pg.evaluate(JS)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1180, 900])
@pytest.mark.parametrize("pane", ["users", "pacing", "globals"])
def test_all_layers_share_one_left_edge(probe, w, pane):
    d = probe[w][pane]
    got = {k: v for k, v in d["layers"].items() if v is not None}
    # 参数分区只有「卡头 + 参数格」两层，用户分区才有分组标题/设置行
    assert len(got) >= 2, "%d/%s 只量到 %s，判据没生效" % (w, pane, got)
    lo, hi = min(got.values()), max(got.values())
    # 修后实测四档同带：卡头/参数格 317.5、分组标题 320.5、设置行 313.5，
    # 极差 ≤6px（字号不同带来的笔画起点差）。修前 22px（311.5 vs 333.5），
    # 负控撤掉修复后 13px —— 6px 这条线两边都区分得开。
    assert hi - lo <= 6, (
        "%d/%s 各层首字左缘散开：%s（差 %.1fpx）"
        % (w, pane, got, hi - lo))


@pytest.mark.parametrize("w", [1512, 1180, 900])
@pytest.mark.parametrize("pane", ["users", "pacing", "globals", "login"])
def test_no_first_char_clipping(probe, w, pane):
    d = probe[w][pane]
    assert not d["clipped"], (
        "%d/%s 有文字被裁（首字/尾部丢失）：%s" % (w, pane, d["clipped"]))
