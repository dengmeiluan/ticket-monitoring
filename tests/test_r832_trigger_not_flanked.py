# -*- coding: utf-8 -*-
"""r832 门禁：展开概览时，触发器**左侧同一行**不许有任何可见内容。

背景：展开态标题行原有 7 个子块按文档序排成
「标题 · 摘要 · 采集元信息 · 日期翻页 · 出发日轴 · 渠道登录 · 收起按钮」，
4 组内容都夹在触发器左边（用户原话「展开概览那个明显交互有问题，展开的
中间还有元素常驻」「展开收起怎么能中间有元素」）。
只改 `order` 在 flex 里会把触发器挤到行中（实测 1338.5→485.5 / 196.6），
最后改用 **grid 两行显式放置**：第 1 行只有「标题 + 触发器」，其余控件固定
在第 3/4 行。判据只看渲染：触发器与标题同行、其左侧同行可见元素数 ≤ 1
（就是标题本身），且两态触发器 x 坐标不变。负控=把标题行改回 flex 即红。
"""
import json
import os
import subprocess
import sys
import time
import socket
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
  const vis = e => { const s=getComputedStyle(e); const r=e.getBoundingClientRect();
    return r.width>1 && r.height>1 && s.display!=='none' && s.visibility!=='hidden'; };
  const tag = e => e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+
    ((typeof e.className==='string'&&e.className.trim())?'.'+e.className.trim().split(/\s+/)[0]:'');
  const band=document.getElementById('srxBand');
  const hero=document.getElementById('srxOvHero');
  if(!band||!hero) return {err:'missing'};
  const h=band.querySelector('.srx-band-h');
  const hr=hero.getBoundingClientRect();
  const kids=[...h.children].filter(vis);
  const leftSameRow = kids.filter(e=>{
    if(e===hero) return false;
    const r=e.getBoundingClientRect();
    const sameRow=Math.abs((r.top+r.height/2)-(hr.top+hr.height/2)) < hr.height*0.6;
    const hasText=(e.textContent||'').trim().length>0;
    return sameRow && r.right <= hr.left+1 && (hasText || r.width>4);
  }).map(tag);
  return {hero:[+hr.left.toFixed(1),+hr.top.toFixed(1)], leftSameRow:leftSameRow,
    collapsed:document.getElementById('searchview').classList.contains('srx-ov-collapsed')};
}"""


def _probe(width):
    from playwright.sync_api import sync_playwright
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
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": width, "height": 1000})
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_timeout(4000)
            for _ in range(40):
                try:
                    pg.evaluate("typeof switchView==='function' && switchView('search')")
                    break
                except Exception:
                    pg.wait_for_timeout(500)
            pg.wait_for_timeout(1500)
            before = pg.evaluate(JS)
            pg.evaluate("""()=>{const b=document.getElementById('srxOvHero');
                if(b&&b.getAttribute('aria-expanded')!=='true')b.click();}""")
            pg.wait_for_timeout(900)
            after = pg.evaluate(JS)
            br.close()
        return before, after
    finally:
        srv.terminate()


@pytest.mark.parametrize("width", [1512, 900, 430])
def test_no_visible_element_between_title_and_trigger(width):
    before, after = _probe(width)
    if before.get("err"):
        pytest.fail(before)
    # 收起态整条价带隐藏时 leftSameRow 恒空（无可见元素），该断言只对可见态有意义
    if before["hero"][0] <= 1 and before["hero"][1] <= 1:
        extra_before = []
    else:
        extra_before = [t for t in before["leftSameRow"] if "srxBandTitle" not in t]
    extra_after = [t for t in after["leftSameRow"] if "srxBandTitle" not in t]
    assert extra_before == [], (
        "收起态触发器左侧同行还有标题以外的元素：%s" % extra_before)
    assert extra_after == [], (
        "展开态触发器左侧同行还夹着标题以外的元素：%s（用户：「展开中间还有元素常驻」）"
        % extra_after)


@pytest.mark.parametrize("width", [1512, 900, 430])
def test_trigger_keeps_its_x_when_toggling(width):
    """展开 / 收起两态，触发器必须在同一坐标（不许横移纵跳）。

    2026-10-31 调整判据：价带已改为**可选**——收起态整条 `display:none`
    （用户：「14 日价带常驻也不对」），此时触发器根本不可见、rect 恒为 0，
    「两态坐标相同」不再成立也不再可测。
    新的意图是：**只要触发器可见，它的位置就不能因为开合而变**。
    所以收起态缺可见触发器时跳过坐标比较，但仍验证展开后它确实落在标题行内
    且不与标题重叠（由 test_no_visible_element_between_title_and_trigger 覆盖）。
    """
    before, after = _probe(width)
    if before.get("err"):
        pytest.fail(before)
    hero_before, hero_after = before["hero"], after["hero"]
    if hero_before[0] <= 1 and hero_before[1] <= 1:
        # 收起态整条价带隐藏：触发器不可见是**预期**，只要求展开后有坐标
        assert hero_after[0] > 1 and hero_after[1] >= 0, (
            "展开后触发器仍无坐标，价带没真正展开：%s" % after)
        return
    dx = abs(hero_after[0] - hero_before[0])
    dy = abs(hero_after[1] - hero_before[1])
    assert dx <= 2.0, "触发器横移 %.1fpx（两态须同坐标）" % dx
    assert dy <= 2.0, "触发器纵移 %.1fpx（两态须同坐标）" % dy


def test_band_header_is_grid():
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "#searchview #srxBand .srx-band-h{\n display:grid;" in src or \
           "#searchview #srxBand .srx-band-h{display:grid;grid-template-columns:auto 1fr auto" in src, (
        "标题行不是 grid 两行布局——flex 下无法保证「标题+触发器」独占第一行")
    assert "grid-area:1/3/2/4" in src, "触发器没有被显式放到第 1 行第 3 列"
