# -*- coding: utf-8 -*-
"""r257 WebUI 三案落地钉（_scratch/r257_webui_audit.md 审计消化，
P0-P2=0 后的可动手打磨项，均为既有 a11y/图例纪律族的漏收成员）：

- W-1 (P3-1) K线模式 #lgZone 成图例首项仍带 14px 左距：分组缝的
  语义是「数据系列组 vs 阈值组」之间，首项悬挂变成行首缩进——缝
  条件挂「任一系列色票可见」，K线/空数据系列档首项缩进归零。
- W-2 (P3-2) 走势模式/范围 chips（折线/K线/48h/7天）选中态纯 .on
  类视觉呈现、aria-pressed=null——#tabs/#cfgnav/#mainnav 先例同族
  补齐，setMode/setRange 切换点各同步一拍。
- W-3 (P3-3) 配置页三类折叠头（_setFold 单源）与明细改期胶囊（.tg）
  开合无 aria-expanded 状态语义——数据行 tr[aria-expanded] 与
  #fltBtn 先例同族补齐；互斥收口（开比价收改期）收敛进 _ariaOff。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r257_webui.py -q
"""
import os
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


# ---- W-1：图例分组缝条件化（K线首项缩进归零 + 折线缝保留，双态钉） ----

def test_lgzone_margin_conditional_on_series(pg):
    """缝只在「数据系列组在场」时保留：折线模式 lgZone 左距 14px
    （与 16px gap 合计 30px 分组缝，r256 落地形态不回归）；K线模式
    lgDirect/lgTrans 隐藏、lgZone 成首项，左距 0（行与上下行左缘
    平齐）。双态单测：条件化的另一半单态钉罩不住。"""
    pg.evaluate("switchView('mon');showMonTab('trend');")
    pg.wait_for_timeout(600)
    pg.evaluate("setMode('line')")
    pg.wait_for_timeout(300)
    line = pg.evaluate("""()=>{
      const z=document.getElementById('lgZone');
      const d=document.getElementById('lgDirect');
      return {ml:getComputedStyle(z).marginLeft,
              dDisp:getComputedStyle(d).display};}""")
    assert line["dDisp"] != "none", line
    assert line["ml"] == "14px", line
    pg.evaluate("setMode('kline')")
    pg.wait_for_timeout(300)
    k = pg.evaluate("""()=>{
      const z=document.getElementById('lgZone');
      const d=document.getElementById('lgDirect');
      const t=document.getElementById('lgTrans');
      return {ml:getComputedStyle(z).marginLeft,
              zDisp:getComputedStyle(z).display,
              dDisp:getComputedStyle(d).display,
              tDisp:getComputedStyle(t).display};}""")
    assert k["dDisp"] == "none" and k["tDisp"] == "none", k
    assert k["zDisp"] != "none", "K线档阈值组图例应仍在场"
    assert k["ml"] == "0px", "K线档 lgZone 成首项不应再悬挂 14px 缩进"
    pg.evaluate("setMode('line')")
    pg.wait_for_timeout(300)


# ---- W-2：走势模式/范围 chips 选中态读屏语义 ----

def test_rngchip_aria_pressed(pg):
    """四颗 rngchip aria-pressed 与 .on 同拍（初始态由 tabAria 兜底，
    setMode/setRange 切换点各同步一拍）。"""
    pg.evaluate("switchView('mon');showMonTab('trend');")
    pg.wait_for_timeout(400)
    init = pg.evaluate("""()=>{
      const g=id=>{const x=document.getElementById(id);
        return x.getAttribute('aria-pressed');};
      return {line:g('mdLine'),k:g('mdK'),r48:g('rng48'),r7d:g('rng7d')};}""")
    assert init == {"line": "true", "k": "false",
                    "r48": "true", "r7d": "false"}, init
    pg.evaluate("setMode('kline')")
    pg.wait_for_timeout(200)
    m = pg.evaluate("""()=>({
      a:document.getElementById('mdLine').getAttribute('aria-pressed'),
      b:document.getElementById('mdK').getAttribute('aria-pressed')})""")
    assert m == {"a": "false", "b": "true"}, m
    pg.evaluate("setRange('7d')")
    pg.wait_for_timeout(200)
    r = pg.evaluate("""()=>({
      a:document.getElementById('rng48').getAttribute('aria-pressed'),
      b:document.getElementById('rng7d').getAttribute('aria-pressed')})""")
    assert r == {"a": "false", "b": "true"}, r
    pg.evaluate("setMode('line');setRange('48h');")
    pg.wait_for_timeout(200)


# ---- W-3a：配置页折叠头 aria-expanded（_setFold 单源覆盖三类） ----

def test_fold_header_aria_expanded(pg):
    """折叠头 role=button 开合状态语义：初始展开='true'，点收='false'，
    再点还原。三类折叠头全走 _setFold 单源。cfg 用户卡默认手风琴
    折叠（grouplab 在卡体内），先走真实展开路径再取件（LESSONS
    十九§7：折叠详情探针先展开，offsetParent 过滤不可见件）。"""
    pg.evaluate("switchView('cfg');showCfgPanel('users');")
    pg.wait_for_timeout(800)
    head = pg.evaluate("""()=>{
      const uh=[...document.querySelectorAll('#cfgform .uhead2')].find(
        x=>x.offsetParent);
      if(uh&&uh.nextElementSibling&&
         uh.nextElementSibling.style.display==='none')uh.click();
      const h=[...document.querySelectorAll('[role="button"]')]
        .find(x=>x.classList.contains('grouplab')&&x.offsetParent);
      if(!h)return null;
      const before=h.getAttribute('aria-expanded');
      h.click();
      const folded=h.getAttribute('aria-expanded');
      h.click();
      const reopened=h.getAttribute('aria-expanded');
      return {before,folded,reopened};}""")
    assert head, "配置页展开用户卡后应有可见折叠头"
    assert head["before"] == "true", head
    assert head["folded"] == "false", head
    assert head["reopened"] == "true", head


# ---- W-3b：改期胶囊 .tg aria-expanded ----

def test_tg_capsule_aria_expanded(pg):
    """改期胶囊 role=button 开合状态语义：渲染初始='false'，展开='true'，
    再点收='false'；开比价互斥收改期时同步复位（_ariaOff 单源）；
    Esc 级联收改期同律回写；重渲染（TGOPEN 持久回填开态）初始态随
    TGOPEN 条件化，不硬编码 false。"""
    pg.evaluate("switchView('mon');showMonTab('details');")
    pg.wait_for_timeout(800)
    cap = pg.evaluate("""()=>{
      const t=[...document.querySelectorAll('.tg')].find(x=>x.offsetParent);
      if(!t)return null;
      const before=t.getAttribute('aria-expanded');
      t.click();
      const opened=t.getAttribute('aria-expanded');
      const rowOpen=[...document.querySelectorAll('tr.tgrow')]
        .some(x=>x.style.display!=='none');
      t.click();
      const closed=t.getAttribute('aria-expanded');
      return {before,opened,rowOpen,closed};}""")
    assert cap, "demo 明细应有可改期胶囊（.tg）"
    assert cap["before"] == "false", cap
    assert cap["opened"] == "true", cap
    assert cap["rowOpen"], cap
    assert cap["closed"] == "false", cap
    # Esc 级联：开胶囊后按 Esc，面板与胶囊 aria 同步收（Esc 分支须
    # 走 _ariaOff 单源，Solo 收行曾漏 .tg 回写）
    esc = pg.evaluate("""()=>{
      const t=[...document.querySelectorAll('.tg')].find(x=>x.offsetParent);
      t.click();
      const opened=t.getAttribute('aria-expanded');
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
      const afterEsc=t.getAttribute('aria-expanded');
      const rowOpen=[...document.querySelectorAll('tr.tgrow')]
        .some(x=>x.style.display!=='none');
      return {opened,afterEsc,rowOpen};}""")
    assert esc["opened"] == "true" and esc["afterEsc"] == "false", esc
    assert not esc["rowOpen"], esc
    # 重渲染回填：TGOPEN 持久态开着重渲，胶囊初始态=条件化 true
    # （硬编码 false 曾让「面板开着而读屏报收起」）
    rr = pg.evaluate("""()=>{
      const t=[...document.querySelectorAll('.tg')].find(x=>x.offsetParent);
      t.click();
      table();
      const t2=[...document.querySelectorAll('.tg')].find(x=>x.offsetParent);
      const rowOpen=[...document.querySelectorAll('tr.tgrow')]
        .some(x=>x.style.display!=='none');
      return {aria:t2.getAttribute('aria-expanded'),rowOpen};}""")
    assert rr["rowOpen"], "重渲后改期面板应随 TGOPEN 回填保持开"
    assert rr["aria"] == "true", rr
    pg.evaluate("TGOPEN=null;_hideXrows();saveUI();")
    pg.wait_for_timeout(200)


# ---- P2-1：用户卡折叠头（.uhead2）开合语义与手风琴回写 ----

def test_uhead2_aria_expanded_accordion(pg):
    """用户卡折叠头 aria-expanded：初始随开态、点收='false'、重开=
    'true'；手风琴开新卡收上一卡时上一卡 aria 同步复位（toggleUser
    曾旁路 _setFold 单源，aria 全族缺位——a11y 四族折叠头的最后
    漏员）。demo 单用户，addUser 造第二张卡驱动手风琴，收尾直接
    splice+buildForm 复原（delUser 走 armConfirm 异步确认不可直调）。"""
    pg.evaluate("switchView('cfg');showCfgPanel('users');")
    pg.wait_for_timeout(800)
    r = pg.evaluate("""()=>{
      addUser();   /* 第二张卡：新卡开、首卡被手风琴收起 */
      const heads=[...document.querySelectorAll('#cfgform .uhead2')]
        .filter(x=>x.offsetParent);
      if(heads.length<2)return {n:heads.length};
      const a=heads[0], b=heads[1];
      const out={};
      out.aFoldedByAccordion=a.getAttribute('aria-expanded');
      out.bOpen=b.getAttribute('aria-expanded');
      b.click();  out.bFolded=b.getAttribute('aria-expanded');
      a.click();  out.aReopened=a.getAttribute('aria-expanded');
      out.bFoldedByAccordion=b.getAttribute('aria-expanded');
      a.click();  out.aFolded=a.getAttribute('aria-expanded');
      a.click();  out.aRestored=a.getAttribute('aria-expanded');
      /* 复原：删掉新增用户，首卡回开态 */
      CFG.splice(1,1);OPEN_USER=0;buildForm();
      return out;}""")
    assert r.get("n", 2) >= 2, r
    assert r["aFoldedByAccordion"] == "false", \
        "手风琴收首卡未回写 aria：" + str(r)
    assert r["bOpen"] == "true", r
    assert r["bFolded"] == "false", r
    assert r["aReopened"] == "true", r
    assert r["bFoldedByAccordion"] == "false", \
        "开 A 手风琴收 B 未回写 aria：" + str(r)
    assert r["aFolded"] == "false" and r["aRestored"] == "true", r


# ---- P2-2：buildChartChips 类重写路径与 aria 同拍 ----

def test_rngchip_aria_syncs_via_buildchartchips(pg):
    """.rngchip 的 .on 存在第三写入口 buildChartChips（跨用户态/恢复
    路径不经 setMode/setRange）：类重写必须无条件同步 aria-pressed，
    含 arr<2 早退路径（单航线用户常态——早退曾跳过 mkactAll/tabAria，
    aria 停在上一态）。直改 CHR 状态模拟，收尾全量还原。"""
    pg.evaluate("switchView('mon');showMonTab('trend');")
    pg.wait_for_timeout(400)
    r = pg.evaluate("""()=>{
      const u=S.users[U]; const keep=u.routesArr;
      const keepSt=CHR[u.name];
      u.routesArr=keep.slice(0,1);        /* 单航线：走 box 早退路径 */
      CHR[u.name]=Object.assign({},(typeof keepSt==='object'&&keepSt)||{},
                                  {r:'7d'});   /* 绕 setRange 直改态 */
      buildChartChips();
      const g=id=>{const x=document.getElementById(id);
        return {on:x.classList.contains('on'),
                aria:x.getAttribute('aria-pressed')};};
      const out={r48:g('rng48'),r7d:g('rng7d')};
      u.routesArr=keep; CHR[u.name]=keepSt;
      buildChartChips(); setRange('48h');
      return out;}""")
    assert r["r7d"]["on"], r
    assert r["r7d"]["aria"] == "true", \
        "类重写路径 aria 未同拍（停在上一态）：" + str(r)
    assert not r["r48"]["on"] and r["r48"]["aria"] == "false", r
