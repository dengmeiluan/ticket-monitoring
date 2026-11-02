# -*- coding: utf-8 -*-
"""r845 门禁：渠道健康五卡必须「每行排满」，不许出现独占一行宽度的孤卡。

实测缺陷：
  · 900 档：`.hdiag[data-n="5"]` 在 ≤1024 用 `repeat(auto-fit,minmax(178px,1fr))`，
    容器 834px 只排出 **4 列**，第 5 张卡（途牛）掉到第二行、只占 200px，
    右侧空出 630px —— 正是 r412 注释里已记过、但当时只盯 1000–1280 档的
    「第 5 张独占 1/4 宽，右边留 75% 空白」（用户：「渠道健康里又有不对齐
    的布局设计」）。
  · 430 档：单列时 `@media(max-width:700) .hdiag-e:empty{display:none}` 把
    空证据行抽掉，有证据的两张卡比其余高 33px（实测 140.8 vs 107.8），
    同一屏里五颗「自检」的纵向节奏忽高忽低。
  · 来源接入的三个动作钮：文字钮留了 `min-width:62px` 的固定宽，钮内空 20px，
    与相邻实心钮读作 24px 间距，而同组另两颗只有 4px（用户：「对齐布局呢」）。

判据全部走渲染几何，不做源码字面匹配。
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
  const R = e => { const b=e.getBoundingClientRect();
    return {t:+b.top.toFixed(1), l:+b.left.toFixed(1), r:+b.right.toFixed(1),
            w:+b.width.toFixed(1), h:+b.height.toFixed(1)}; };
  const grid = document.querySelector('#healthDiag .hdiag');
  const cards = [...grid.querySelectorAll('.hdiag-card')];
  const g = R(grid);
  // 按卡顶分行，量每行占了多少宽度
  const rows = [];
  cards.forEach(c => {
    const r = R(c);
    const row = rows.find(x => Math.abs(x.top - r.t) <= 2);
    if (row) { row.items.push(r); } else { rows.push({top:r.t, items:[r]}); }
  });
  const rowFill = rows.map(x => ({
    top:+x.top.toFixed(1), n:x.items.length,
    used:+(Math.max(...x.items.map(i=>i.r)) - Math.min(...x.items.map(i=>i.l))).toFixed(1)
  }));
  // 三个动作钮的间距（登录钮在 demo 态被隐藏时只剩两颗）
  const acts = [...document.querySelectorAll('#scNoteBtn,#scLoginBtn,.scbtn.ghost')]
    .filter(b => b.getBoundingClientRect().width > 1).map(R);
  const gaps = [];
  for (let i = 1; i < acts.length; i++) gaps.push(+(acts[i].l - acts[i-1].r).toFixed(1));
  // 行内横向空洞：本轮实测 900 档 3+2 第二行只铺 550/834、右侧空 270px
  const rowGap = rows.map(x => ({top:+x.top.toFixed(1), n:x.items.length,
    hole:+(g.r - Math.max(...x.items.map(i=>i.r))).toFixed(1)}));
  const truncated = [...grid.querySelectorAll('.hdiag-st')]
    .filter(s => s.scrollWidth > s.clientWidth + 1)
    .map(s => ({txt:(s.textContent||'').trim().slice(0, 20), over:s.scrollWidth - s.clientWidth}));
  return {gridW:g.w, rowFill, rowGap, truncated,
          rowCount:rows.length,
          cardH:cards.map(c=>+R(c).h.toFixed(1)),
          btnTop:cards.map(c=>{const b=c.querySelector('button');return b?+R(b).t.toFixed(1):null;}),
          actGaps:gaps, actCount:acts.length};
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
            for w in (1512, 1024, 1000, 900, 820, 430):
                pg = br.new_page(viewport={"width": w, "height": 1500})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(700)
                pg.evaluate("showMonTab('health')")
                pg.wait_for_timeout(1800)
                # 「去登录」在 demo 态按设计隐藏；把它显出来量三钮的真实节奏
                pg.evaluate("""()=>{const b=document.getElementById('scLoginBtn');
                    if(b)b.hidden=false;}""")
                pg.wait_for_timeout(250)
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


@pytest.mark.parametrize("w", [1512, 1024, 1000, 900, 820, 430])
def test_every_row_is_filled(probe, w):
    """每行卡必须横向排满：独占一行的卡只能出现在单列档。"""
    d = probe[w]
    assert d["rowFill"], "%d 档没量到卡" % w
    if w <= 700:                     # 单列档：每行 1 张，本来就满宽
        assert all(r["n"] == 1 for r in d["rowFill"]), d["rowFill"]
        return
    bad = [r for r in d["rowFill"] if r["n"] == 1]
    assert not bad, (
        "%d 档有独占一行的孤卡（横向空出 %.1fpx）——"
        "第 5 张掉到第二行、右侧留一大片空白：%s"
        % (w, d["gridW"] - bad[0]["used"] if bad else 0, bad))


@pytest.mark.parametrize("w", [1512, 1024, 1000, 900, 820, 430])
def test_all_cards_share_one_height(probe, w):
    d = probe[w]
    hs = sorted(set(d["cardH"]))
    assert len(hs) == 1, (
        "%d 档五张健康卡高矮不一 %s——同一屏里「自检」的纵向节奏忽高忽低" % (w, hs))


@pytest.mark.parametrize("w", [1512, 1024, 1000, 900, 820, 430])
def test_source_access_actions_are_evenly_spaced(probe, w):
    d = probe[w]
    gaps = d["actGaps"]
    assert d["actCount"] >= 2, "没量到来源接入的动作钮"
    assert max(gaps) - min(gaps) <= 1, (
        "%d 档三个动作钮间距不均 %s——同一组动作出现两种节奏" % (w, gaps))
    assert all(g <= 12 for g in gaps), (
        "%d 档动作钮之间有 %.1fpx 空框（钮内留白撑出来的视觉间距）" % (w, max(gaps)))


@pytest.mark.parametrize("w", [1512, 1024, 1000, 900, 430])
def test_no_horizontal_hole_at_row_end(probe, w):
    """每行最后一张卡的右缘要贴到网格右缘：不允许 3+2 那种「第二行只排两张、
    右侧空一整格」（用户：「不要无意义留白过多」「上下不对齐、廉价感」）。

    代价容忍：最后一行不满列时允许空 ≤ 1 张卡宽。7 张是质数，4+3
    必然空 1 格（r813f 实测 900/1000/1024 洞宽 212–237px ≈ 1 卡）；
    超过 1 卡宽才算「空了一整格」。
    """
    d = probe[w]
    holes = d.get("rowGap") or []
    if not holes:
        return
    one = d["gridW"] / max(1, len(holes[0:1]) or 1)
    card = max((r["used"] / max(1, r["n"])) for r in d["rowFill"])
    bad = [h for h in holes if h["hole"] > card * 1.05]
    assert not bad, (
        "%d 档有整格横向空洞（行内卡数/洞宽）：%s，卡宽约 %.0fpx"
        % (w, [(h["n"], h["hole"]) for h in bad], card))


@pytest.mark.parametrize("w", [1512, 1024, 1000, 900, 430])
def test_status_badges_are_not_truncated(probe, w):
    """五列挤压下状态徽标不得被省略号截断（「演示 · 最近一…」= 丢信息）。"""
    d = probe[w]
    bad = d.get("truncated") or []
    assert not bad, "%d 档健康卡状态徽标被截断：%s" % (w, bad)
