# -*- coding: utf-8 -*-
"""r806 门禁：展开筛选面板必须与同一张卡里的每一行同缘，且不自绘第二层盒子。

背景：r469 给 `#srxFmore` 加了 `margin-left:60px`（想「对齐标签列」），并且
r6xx 又在里面套了 `border:1px + border-radius:r10 + padding:12px 14px`。
实测 1512：面板左缘 151.5、右缘 1410.5 —— 左边内缩 60px、右边贴死卡缘，
左右内衬不对称；卡内标题被推到 l=106.5，而同卡「航线」行从 91.5 起。
用户原话：「展开筛选条件的这个面板的布局明显跟当前页面没有对齐，大小布局
对称，不够协调」「折叠起来了，但是有很多分割线，很不干净」。

判据：面板左右缘与 `#srxContext` 相同（容差 1px），且面板头与面板左缘
同线。负控：把 margin-left 改回 60px / 把 border+padding 加回去即红。
"""
import os
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 9136
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const box = e => { if(!e) return null; const r=e.getBoundingClientRect();
    return {l:+r.left.toFixed(1), r:+r.right.toFixed(1), w:+r.width.toFixed(1)}; };
  const ctx = box(document.getElementById('srxContext'));
  const fm = box(document.getElementById('srxFmore'));
  if(!ctx || !fm) return {err:'missing node', ctx:ctx, fm:fm};
  const lines = [...document.querySelectorAll('#srxContext > .srx-line')]
    .filter(l=>l.getBoundingClientRect().width>1).map(box);
  const headB = box(document.querySelector('#srxFmore .srf-head b'));
  const cs = getComputedStyle(document.getElementById('srxFmore'));
  return {ctx:ctx, fm:fm, lines:lines, headB:headB,
          fmPad:cs.padding, fmBorder:cs.borderTopWidth, fmBg:cs.backgroundColor};
}"""


@pytest.fixture(scope="module")
def probe():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            pg = br.new_page(viewport={"width": 1512, "height": 1000})
            pg.goto(BASE + "/", wait_until="domcontentloaded")
            pg.wait_for_timeout(2500)
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1500)
            pg.evaluate("""()=>{const b=document.getElementById('srxMoreBtn');
                if(b && b.getAttribute('aria-expanded')!=='true') b.click();}""")
            pg.wait_for_timeout(1000)
            data = pg.evaluate(JS)
            br.close()
        yield data
    finally:
        srv.terminate()


def test_panel_left_edge_matches_page(probe):
    if probe.get("err"):
        pytest.fail("探针取不到节点：%s" % probe)
    d = probe
    assert abs(d["fm"]["l"] - d["ctx"]["l"]) <= 1.0, (
        "面板左缘 %.1f 与卡片左缘 %.1f 不齐（内缩 %.1f）——同卡其余行：%s"
        % (d["fm"]["l"], d["ctx"]["l"], d["fm"]["l"] - d["ctx"]["l"], d["lines"]))
    assert abs(d["fm"]["r"] - d["ctx"]["r"]) <= 1.0, (
        "面板右缘 %.1f 与卡片右缘 %.1f 不等（差 %.1f）"
        % (d["fm"]["r"], d["ctx"]["r"], d["fm"]["r"] - d["ctx"]["r"]))


def test_panel_shares_row_grid(probe):
    if probe.get("err"):
        pytest.fail("探针取不到节点：%s" % probe)
    d = probe
    lefts = [x["l"] for x in d["lines"]]
    assert lefts, "一行都没量到"
    assert any(abs(d["fm"]["l"] - l) <= 1.0 for l in lefts), (
        "面板左缘 %.1f 不落在任何一行的左缘上：%s" % (d["fm"]["l"], lefts))
    assert d["headB"], "面板头不见了"
    assert abs(d["headB"]["l"] - d["fm"]["l"]) <= 4.0, (
        "面板标题 %.1f 相对面板左缘 %.1f 偏了 %.1f（多了一层内衬）"
        % (d["headB"]["l"], d["fm"]["l"], d["headB"]["l"] - d["fm"]["l"]))


def test_panel_draws_no_second_box(probe):
    if probe.get("err"):
        pytest.fail("探针取不到节点：%s" % probe)
    d = probe
    assert d["fmBorder"] in ("0px", "0"), (
        "面板又自带边框（卡中卡）：border-top=%s" % d["fmBorder"])
    assert d["fmPad"].startswith("0px"), (
        "面板又自带内衬（与同卡各行不同缘）：padding=%s" % d["fmPad"])


def test_source_rules_kept(probe):
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "#searchview .srx-fmore{margin-left:60px" not in src, (
        "60px 左缩进回来了：面板会再次左侧内缩、右侧贴边")
    assert "#searchview .srx-fmore{margin-left:0;margin-top:0;padding-top:6px}" in src
    assert "#searchview #srxFmore.open{background:transparent;border:0;border-radius:0;padding:0;gap:7px}" in src
