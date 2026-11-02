# -*- coding: utf-8 -*-
"""r991 门禁：≤760 明细筛选卡里「同一排的标签槽」不能被拆成两条左缘线。

用户最新一轮原话：「看看类似筛选列表中的筛选条件的不对齐的情况，类似的
布局不对称、不对齐的都要修掉。」

r851c 给 ≤760 档把标签槽改回自适应宽——当时是为了不让 72px 槽把「更多日期」
这类按钮压到裁字（430/390/320 档 6 处）。但自适应宽在「标签与内容仍然同排」
的行上会造出第二条左缘线：541–760 实测「智能筛选」内容左缘 100、「属性」
68，**同一张卡里差 32px**。

定案：541–760 这段本来就单排、槽宽放得下，恢复统一槽位；<541 才是逐行换行、
内容整体回行首的那一档，槽位在那里既无意义又会压字，保持自适应。

判据只量渲染几何：取「标签与首个内容块在同一排（top 相差 <8px）」的行，
它们的首个内容左缘跨度必须 ≤1px。

r991b：<541 档同样有这条分叉——行首标签虽已单起一行，但行内的 grid 组
（`.ag-wide` 用 `56px 1fr`）仍留着标签列，于是网格行的内容在 100、
flex 行的在 68。实测 540/500/430/390/375/320 恢复槽位后跨度 32→0，
且**没有新增裁字或行级溢出**，所以两档一起统一；门禁覆盖 760→320。
负控：注入还原规则（≤760 一律自适应宽）后，各档跨度必回到 32px → 红。
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
  const vis = e => { const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1; };
  const txt = el => { if (!el) return null;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) { if (!n.nodeValue.trim()) continue;
      const r = document.createRange(); r.selectNodeContents(n);
      const b = r.getBoundingClientRect();
      if (b.width > 0) return {l:+b.left.toFixed(1), t:+b.top.toFixed(1)}; }
    return null; };
  const wrap = document.getElementById('fltwrap');
  const rows = [];
  [...wrap.querySelectorAll(':scope > .frow')].filter(vis).forEach(r => {
    const lab = r.querySelector(':scope > .chiplab')
             || r.querySelector('.wingrp > .chiplab')
             || r.querySelector('.agrp > .chiplab');
    const lt = txt(lab);
    let first = null;
    const pool = [...r.querySelectorAll(
      ':scope > label, :scope > .chip, :scope > input, :scope > button, ' +
      ':scope > .wingrp .winsel, :scope > .agrp .chip, :scope > .agrp input')];
    for (const e of pool) {
      if (!vis(e) || e.contains(lab)) continue;
      const b = e.getBoundingClientRect();
      first = {l:+b.left.toFixed(1), t:+b.top.toFixed(1)}; break;
    }
    rows.push({id: r.id || ('' + r.className).replace('frow', '').trim(),
      labTxt: lab ? lab.textContent.trim().slice(0, 6) : null,
      labL: lt ? lt.l : null, firstL: first ? first.l : null,
      inline: (lt && first) ? (Math.abs(first.t - lt.t) < 8) : false});
  });
  return rows;
}"""

REVERT = """
@media(max-width:760px){
 #tablecard .frow>.chiplab,#tablecard .frow .wingrp>.chiplab,
 #tablecard #attrchips .chiplab{
  width:auto!important;flex:0 0 auto!important;
  margin-right:0!important;padding-right:0!important}
}
"""


@pytest.fixture(scope="module")
def probe():
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
            for w in (760, 700, 600, 541, 540, 430, 375, 320):
                pg = br.new_page(viewport={"width": w, "height": 1100})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(700)
                pg.evaluate("showMonTab('details')")
                pg.wait_for_timeout(1500)
                pg.evaluate("document.getElementById('fltBtn').click()")
                pg.wait_for_timeout(900)
                now = pg.evaluate(JS)
                pg.add_style_tag(content=REVERT)
                pg.wait_for_timeout(400)
                rev = pg.evaluate(JS)
                out[w] = {"now": now, "revert": rev}
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


def _spread(rows):
    lefts = [r["firstL"] for r in rows if r["inline"] and r["firstL"] is not None]
    assert len(lefts) >= 3, "单排行不足 3 条，判据没接上：%s" % rows
    return max(lefts) - min(lefts), lefts


@pytest.mark.parametrize("w", [760, 700, 600, 541, 540, 430, 375, 320])
def test_single_row_label_slot_is_shared(probe, w):
    """541–760 与 <541：标签与内容同排的行，首个内容必须落在同一左缘。"""
    spread, lefts = _spread(probe[w]["now"])
    assert spread <= 1.0, (
        "%d 档同一张筛选卡里单排行分成 %d 条左缘线（跨度 %.1fpx）：%s"
        % (w, len(set(lefts)), spread,
           [(r["id"], r["labTxt"], r["firstL"]) for r in probe[w]["now"] if r["inline"]]))


@pytest.mark.parametrize("w", [760, 541])
def test_negative_control_adaptive_slot_splits_the_edge(probe, w):
    """负控：把 ≤760 恢复成自适应宽，跨度必须回来（否则判据没打到对象）。"""
    spread, _ = _spread(probe[w]["revert"])
    assert spread > 10, (
        "%d 档负控无效：还原规则后跨度仍 %.1fpx，说明这条判据量的不是标签槽"
        % (w, spread))
