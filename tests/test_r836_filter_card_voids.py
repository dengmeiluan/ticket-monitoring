# -*- coding: utf-8 -*-
"""r836 门禁：筛选面板里任何一张卡内部都不得出现大空档，两列底边同线。

实测缺陷（修前 1512）：第二排「加工与历史 | 价格带 | 检索特有」三卡平铺、
网格拉到等高的 201px 后，价格带卡内空 57.3px、检索特有卡内空 100.5px
（r698 用 space-between 把死白均分成两个洞）。用户原话：「衔接空格很大很空」
「紧凑之中要大方质感，不要无意义留白过多」。

修法：价格带 + 检索特有竖向堆叠成一列（`.srf-stack`），两列都拉伸，
余量在卡内均布。修后实测 1512/1280：所有卡内最大空档 8px、两列底边同线。

判据用渲染几何（不是源码字面），否则「规则在、布局坏」会假绿。
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
  const fm = document.getElementById('srxFmore');
  if(!fm) return {err:'no panel'};
  const R = e => { const b=e.getBoundingClientRect();
    return {t:b.top, b:b.bottom, h:b.height, l:b.left, r:b.right, w:b.width}; };
  const cards = [...fm.querySelectorAll('.srf-card')].map(c=>{
    const kids=[...c.children].filter(k=>k.getBoundingClientRect().height>1);
    const cr=R(c), padT=parseFloat(getComputedStyle(c).paddingTop)||0;
    let prev=cr.t+padT, maxGap=0;
    kids.forEach(k=>{ const r=R(k); if(r.t-prev>maxGap) maxGap=r.t-prev; prev=r.b; });
    return {cls:c.className.trim(), h:+cr.h.toFixed(1), maxGap:+maxGap.toFixed(1),
            l:+cr.l.toFixed(1), b:+cr.b.toFixed(1), w:+cr.w.toFixed(1)};
  });
  // 「同排底边齐平」看的是网格的**直接子项**：共同筛选 / 起降时段 /
  // 加工与历史 / 堆叠列 / 当前筛选。堆叠列内部的卡是列内堆叠，不参与
  // 同一行的比较——否则 price 底边 594.8 会被误判成「与 history 差 122px」。
  const grid = fm.querySelector('.srf-grid');
  const gridW = R(grid).w;
  const tops = [...grid.children].filter(e=>e.getBoundingClientRect().height>1).map(e=>{
    const r=e.getBoundingClientRect();
    return {cls:(e.className||'').toString().trim(), t:+r.top.toFixed(1),
            b:+r.bottom.toFixed(1), w:+r.width.toFixed(1)};
  });
  const bands=[];
  tops.forEach(k=>{
    if(k.w >= gridW - 1) return;                 // 全宽行自成一行，不参与比较
    const band=bands.find(x=>Math.abs(x.top-k.t)<=2);
    if(band)band.items.push(k); else bands.push({top:k.t, items:[k]});
  });
  const rowSpreads=bands.filter(x=>x.items.length>1).map(x=>{
    const bs=x.items.map(k=>k.b);
    return {top:+x.top.toFixed(1), spread:+(Math.max(...bs)-Math.min(...bs)).toFixed(1),
            items:x.items.map(k=>k.cls+'@'+k.b)};
  });
  return {panelH:+R(fm).h.toFixed(1), cards, rowSpreads};
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
                pg = br.new_page(viewport={"width": w, "height": 1400})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2500)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1200)
                pg.evaluate("""()=>{try{if(!SRX.ctx)srxToggleCtx();
                    document.getElementById('searchview').classList.add('show-filters');}catch(e){}
                    const b=document.getElementById('srxMoreBtn'); if(b)b.click();}""")
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
def test_no_card_holds_a_large_internal_void(probe, w):
    """卡内「洞」而不是「舒展」：均匀铺开的间距（如时段卡 21~29px）是

    space-between 的正常呼吸感；缺陷是**一个**远大于其余的孤立空洞
    （修前价格带 57.3、检索特有 100.5）。阈值取 34px：高于任何一档
    的均匀间距，低于两个真实缺陷。
    """
    d = probe[w]
    assert "err" not in d, d
    bad = [c for c in d["cards"] if c["maxGap"] > 34]
    assert not bad, (
        "%d 档以下卡内部出现孤立大空洞（>34px）：%s"
        % (w, [(c["cls"], c["maxGap"], c["h"]) for c in bad]))


@pytest.mark.parametrize("w", [1512, 1280])
def test_same_row_cards_end_on_the_same_line(probe, w):
    d = probe[w]
    assert "err" not in d, d
    rows = d["rowSpreads"]
    assert rows, "没有量到同排两张以上的卡：%s" % d["cards"]
    bad = [r for r in rows if r["spread"] > 2]
    assert not bad, (
        "%d 档同排卡片底边相差（%s）——用户读作「上下不对齐、廉价感」"
        % (w, bad))


def test_price_and_evidence_stack_vertically():
    """结构判据：两张稀疏卡必须在同一个堆叠列里，否则网格又会把它们拉平。

    判据跟着「谁把 price/evidence 包进堆叠列」走，不再按固定字符窗口截取
    ——往同文件别处加代码会把窗口推离目标，制造与缺陷无关的假红。
    """
    import webui
    src = webui.PAGE
    assert "'<div class=\"srf-stack\">'+price+evidence" in src, \
        "价格带/检索特有没有并进同一个堆叠列"
    assert "grid-area:stack" in src, "堆叠列没有落在网格的 stack 区域"
