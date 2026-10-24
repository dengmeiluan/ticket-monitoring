# -*- coding: utf-8 -*-
"""r256 WebUI 三案落地钉（_scratch/r256_webui_audit.md 审计消化，
P0-P2=0 后的可动手打磨项）：

- W-1 (P3-4) KPI 空日期卡「-」孤立小连字符与相邻 31px 大数字对比
  突兀（空卡显残缺）：!brief 分支弱化为 40% 透明大号「—」，说明行
  保留（过期停采/下轮补上语义不变）。
- W-2 (美感1) 走势图例「行情 vs 阈值」两组间加分隔间距：lgDirect/
  lgTrans 是数据系列、lgZone/lgThD/lgThT 是阈值参考，等距一排扫读
  无分组感——#lgZone 加 14px 左距（与 16px 基础 gap 合计 30px 分组
  缝，折行档仅多 14px 前距无实害）。
- W-3 (美感3) 日历格 hover 反馈：.calcell 有 title 无视觉暗示——
  :hover 描边升 --line2 一档（与 ucard hover 同语言；不加 pointer
  光标，维持「非可点」语义诚实）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r256_webui.py -q
"""
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    logf = tempfile.TemporaryFile("w+", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
    if not _wait_up(proc):
        proc.kill()
        logf.seek(0)
        pytest.fail("demo 服务未起来：%s" % logf.read()[-600:])
    yield proc
    proc.kill()
    logf.close()


@pytest.fixture(scope="module")
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10000)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        yield page
        b.close()


def _cssom_rules(pg, needle):
    """CSSOM 规则枚举（容器判定带 length，LESSONS 二十一§11）。"""
    return pg.evaluate("""(needle)=>{
      const out=[];
      const walk=(rs)=>{for(const r of rs){
        if(r.cssRules&&r.cssRules.length){walk(r.cssRules);continue;}
        if(r.selectorText&&r.selectorText.includes(needle))
          out.push({sel:r.selectorText,css:r.style.cssText});}};
      for(const s of document.styleSheets){
        try{walk(s.cssRules);}catch(e){}}
      return out;}""", needle)


# ---- W-1：KPI 空日期卡空态弱化 ----

def test_kpi_empty_dash_muted(pg):
    """空卡 num 槽=40% 透明「—」（孤置小连字符与相邻大数字对比突兀、
    空卡显残缺）；说明行保留。demo 概览自带无数据卡（合成数据日期
    缺口），DOM 面直测。"""
    empty = pg.evaluate("""()=>{
      const nums=[...document.querySelectorAll('.kpi .num')];
      const n=nums.find(x=>x.textContent.trim()==='-'||
                           x.classList.contains('em'));
      if(!n)return null;
      return {txt:n.textContent.trim(), em:n.classList.contains('em'),
              op:getComputedStyle(n).opacity,
              muted:!!n.parentElement.querySelector('.muted')};}""")
    assert empty, "demo 概览应有无数据 KPI 卡"
    assert empty["em"], empty
    assert empty["txt"] == "—", empty
    assert abs(float(empty["op"]) - 0.4) < 0.01, empty
    assert empty["muted"], empty
    # CSS 规则真实在场且值=0.4（CSSOM 层叠真值，非源码字符串）
    ok = _cssom_rules(pg, ".num.em")
    assert ok, "缺 .num.em 规则"
    assert any("0.4" in r["css"] for r in ok), ok


# ---- W-2：走势图例分组间距 ----

def test_trend_legend_group_gap(pg):
    """阈值参考组（lgZone 起）左距 14px：与数据系列组分缝。"""
    m = pg.evaluate("""()=>{
      const el=document.getElementById('lgZone');
      return {ml:getComputedStyle(el).marginLeft,
              gap:getComputedStyle(el.parentElement).gap};}""")
    assert m["ml"] == "14px", m
    assert m["gap"] == "16px", m


# ---- W-3：日历格 hover 反馈 ----

def test_calcell_hover_feedback(pg):
    """:hover 描边升 --line2 档（行为钉：真实 hover 前后 computed
    变化；.calcell:hover 特异度 (0,2,0) 压过基规 (0,1,0) 无层叠悬念，
    CSSOM 规则在场双证）。"""
    rules = _cssom_rules(pg, ".calcell:hover")
    assert rules and any("var(--line2)" in c["css"] for c in rules), rules
    # 日历在 monitor 视图 trend 子页（默认概览不显示），先落视图
    pg.evaluate("switchView('mon');showMonTab('trend');")
    pg.wait_for_timeout(800)
    # 可见格取件（首格可能在隐藏容器，LESSONS 十九§7 offsetParent 过滤）；
    # 格常在折叠线下，先滚动居中再取坐标；before 与 hover 目标同元素
    # 取件（LESSONS 十九§12 触发后取件律的预防面）
    box = pg.evaluate("""()=>{
      const c=[...document.querySelectorAll('.calcell')]
        .find(x=>x.offsetParent);
      if(!c)return null;
      const before=getComputedStyle(c).borderTopColor;
      c.scrollIntoView({block:'center'});
      const b=c.getBoundingClientRect();
      return {before, x:b.x+b.width/2, y:b.y+b.height/2};}""")
    pg.wait_for_timeout(200)
    assert box, "demo 概览应有可见日历格"
    # 坐标级 hover：demo 轮询重渲染会让 actionability 检查饿死
    # （LESSONS r250 click 饿死家族），mouse.move 直打格心
    pg.mouse.move(box["x"], box["y"])
    pg.wait_for_timeout(200)
    after = pg.evaluate("""()=>{
      const c=document.querySelector('.calcell:hover');
      return c?getComputedStyle(c).borderTopColor:null;}""")
    line2 = pg.evaluate("""()=>{
      const d=document.createElement('div');
      d.style.color='var(--line2)';document.body.appendChild(d);
      const v=getComputedStyle(d).color;d.remove();return v;}""")
    assert after, "hover 态未命中日历格（指针未落在格上）"
    assert after != box["before"], (box["before"], after)
    assert after == line2, (after, line2)
