# -*- coding: utf-8 -*-
"""r1131：以真实渲染普查代替“旧 r1130 绿”的结构门禁。

覆盖 prompt v1.3 本轮 7 项硬约束：
1) 检索顶部 <=2 行；#srxToolsRow 高度 0；组合入口单例且在主行；
2) 渠道入口固定按钮 + fixed 右侧抽屉 + 遮罩，不带航线日期；
3) 镜像折叠按钮唯一、在结果卡头、两态坐标 <=1px、镜像 bbox 不压表头/卡头；
4) 诊断状态链与动作组间距 <=24px，无 margin-left:auto；
5) 节流行 <=64、chip <=4/行、右栏 280-360、健康行 <=56、配置 12 列且无“取值”、筛选 chip <=2 行/组；
6) 每项均有负控：故意破坏后同一探测函数必须返回失败。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染普查依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = _free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1512, "height": 950})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
        page.wait_for_timeout(900)
        page.evaluate("switchView('search')")
        page.wait_for_timeout(900)
        yield page, errs
        b.close()


SEARCH = """() => {
  const vis=e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();
    return c.display!=='none'&&c.visibility!=='hidden'&&r.width>2&&r.height>2};
  const kids=[...document.querySelectorAll('#srxProbe>*')].filter(vis);
  const ys=[...new Set(kids.map(e=>Math.round(e.getBoundingClientRect().top)))];
  const comboNodes=[...document.querySelectorAll('button,span,em,b,div')]
    .filter(e=>vis(e)&&/^组合\\s*\\d\\/4$/.test((e.textContent||'').trim()));
  const btns=[...document.querySelectorAll('#srxBatchToggle')].filter(vis);
  return {ys, kids:kids.map(e=>e.id||e.className),
    toolsH:+document.getElementById('srxToolsRow').getBoundingClientRect().height.toFixed(1),
    batchN:btns.length, comboN:comboNodes.length,
    inForm:!!(btns[0]&&btns[0].closest('#srxProbeForm'))};
}"""


def _search_bad(d):
    bad = []
    if len(d["ys"]) > 2:
        bad.append("顶部可见 y 行 %d: %s" % (len(d["ys"]), d["ys"]))
    if d["toolsH"] > 1:
        bad.append("#srxToolsRow 高 %s" % d["toolsH"])
    if d["batchN"] != 1:
        bad.append("#srxBatchToggle %d 个" % d["batchN"])
    if d["comboN"] != 1:
        bad.append("可见组合 N/4 %d 个" % d["comboN"])
    if not d["inForm"]:
        bad.append("组合不在表单主行")
    return bad


def test_search_two_rows_and_single_combo(pg):
    page, errs = pg
    d = page.evaluate(SEARCH)
    assert not _search_bad(d), (d, errs)
    page.evaluate("""()=>{const p=document.getElementById('srxProbe');
      const x=document.createElement('div');x.id='__neg3';x.style.height='20px';p.appendChild(x)}""")
    assert _search_bad(page.evaluate(SEARCH)), "负控失败：第三行没被拦"
    page.evaluate("()=>document.getElementById('__neg3').remove()")
    assert not _search_bad(page.evaluate(SEARCH))


DRAWER = """() => {
  const d=document.getElementById('srxChLinksDrawer'),m=document.getElementById('srxChLinksMask');
  const b=document.getElementById('srxChLinksBtn');
  if(!d||!m||!b)return {exists:false};
  const r=d.getBoundingClientRect(),cs=getComputedStyle(d);
  return {exists:true, hidden:d.hidden, pos:cs.position, vw:innerWidth,
    w:+r.width.toFixed(1), name:b.textContent.trim(), aria:b.getAttribute('aria-expanded'),
    mask:!m.hidden, maskPos:getComputedStyle(m).position,
    ctx:/当前航线|from=|date=/.test(d.innerText),
    triggers:[...document.querySelectorAll('#srxChLinksBtn')].length};
}"""


def _drawer_bad(d):
    if not d.get("exists"):
        return ["抽屉不存在"]
    bad = []
    if d["hidden"]:
        bad.append("抽屉未显示")
    if d["pos"] != "fixed":
        bad.append("position=%s" % d["pos"])
    # 用户裁定：渠道入口为 420–480 宽右抽屉；桌面非模态（无遮罩、
    # 不锁滚动），≤600 窄档才用遮罩底部抽屉。
    if not (420 <= d["w"] <= 480):
        bad.append("宽 %s 超出 420-480" % d["w"])
    if d.get("vw", 9999) > 600:
        if d["mask"]:
            bad.append("桌面不应有遮罩")
    else:
        if not d["mask"]:
            bad.append("窄档无遮罩")
        if d["maskPos"] != "fixed":
            bad.append("遮罩非 fixed")
    if d["ctx"]:
        bad.append("携带航线/日期上下文")
    if d["triggers"] != 1:
        bad.append("触发器 %d 个" % d["triggers"])
    if d["aria"] != "true":
        bad.append("aria-expanded 未同拍")
    return bad


def test_channel_entry_is_fixed_masked_drawer(pg):
    page, errs = pg
    y0 = page.evaluate("scrollY")
    page.evaluate("document.getElementById('srxChLinksBtn').click()")
    page.wait_for_timeout(700)
    d = page.evaluate(DRAWER)
    assert not _drawer_bad(d), (d, errs)
    # 桌面非模态：不锁页面滚动（≤600 才锁）
    assert page.evaluate("document.body.style.overflow") != "hidden"
    page.evaluate("()=>{const d=document.getElementById('srxChLinksDrawer');"
                  "d.style.width='300px'}")
    assert _drawer_bad(page.evaluate(DRAWER)), "负控失败：过窄抽屉没被拦"
    page.evaluate("()=>{const d=document.getElementById('srxChLinksDrawer');"
                  "d.style.width=''}")
    assert not _drawer_bad(page.evaluate(DRAWER))
    page.evaluate("()=>{const d=document.getElementById('srxChLinksDrawer');"
                  "d.hidden=false;d.style.position='absolute'}")
    assert _drawer_bad(page.evaluate(DRAWER)), "负控失败：absolute 没被拦"
    page.evaluate("()=>{const d=document.getElementById('srxChLinksDrawer');d.style.position='';srxChLinksClose()}")
    page.wait_for_timeout(300)
    assert page.evaluate("scrollY") == y0
    assert page.evaluate("document.activeElement && document.activeElement.id") == "srxChLinksBtn"


MIRROR = """() => {
  const q=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const inter=(a,b)=>!!(a&&b&&a.w>0&&a.h>0&&b.w>0&&b.h>0&&
    a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h);
  const fs=[...document.querySelectorAll('button')].filter(e=>/^(展开|收起)渠道镜像$/.test((e.textContent||'').trim()));
  const m=q('#srxMirror'),head=q('#srxListHead'),th=q('.srx-thead');
  return {foldN:fs.length,inHead:!!(fs[0]&&fs[0].closest('#srxListHead')),
    fold:q('#srxMirrorFold'),mirror:m,head,thead:th,
    interHead:inter(m,head),interThead:inter(m,th),
    label:fs[0]?fs[0].textContent.trim():''};
}"""


def test_mirror_fold_single_stable_and_no_overlap(pg):
    page, errs = pg
    a = page.evaluate(MIRROR)
    assert a["foldN"] == 1 and a["inHead"], (a, errs)
    assert not a["interHead"] and not a["interThead"], a
    page.evaluate("document.getElementById('srxMirrorFold').click()")
    page.wait_for_timeout(450)
    b = page.evaluate(MIRROR)
    assert b["foldN"] == 1
    assert abs(a["fold"]["x"] - b["fold"]["x"]) <= 1
    assert abs(a["fold"]["y"] - b["fold"]["y"]) <= 1, (a, b)
    assert b["mirror"]["w"] == 0 or (not b["interHead"] and not b["interThead"]), b
    assert b["label"] == "展开渠道镜像", b
    page.evaluate("""()=>{const b=document.createElement('button');b.className='srx-btn';
      b.textContent='收起渠道镜像';b.id='__negFold';document.getElementById('srxListHead').appendChild(b)}""")
    assert page.evaluate(MIRROR)["foldN"] == 2, "负控失败：重复折叠按钮没被数到"
    page.evaluate("()=>document.getElementById('__negFold').remove()")
    page.evaluate("document.getElementById('srxMirrorFold').click()")
    page.wait_for_timeout(400)


DIAG = """() => {
  const q=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const p=q('#healthDiag>#srccap .scpath'),a=q('#healthDiag>#srccap .scfoot');
  return {p,a,gap:p&&a?+(a.x-(p.x+p.w)).toFixed(1):null,
    ml:getComputedStyle(document.querySelector('#healthDiag>#srccap .scfoot')).marginLeft,
    diagH:+document.getElementById('healthDiag').getBoundingClientRect().height.toFixed(1)};
}"""


def test_diagnosis_actions_stay_next_to_chain(pg):
    page, _ = pg
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_timeout(1300)
    d = page.evaluate(DIAG)
    assert d["gap"] is not None and 0 <= d["gap"] <= 24, d
    assert d["ml"] != "auto", d
    assert d["diagH"] <= 130, d
    page.evaluate("()=>{document.querySelector('#healthDiag>#srccap .scfoot').style.setProperty('margin-left','auto','important')}")
    d2 = page.evaluate(DIAG)
    assert d2["gap"] > 24 or d2["ml"] == "auto", "负控失败：margin-left:auto 没被拦"
    page.evaluate("()=>{document.querySelector('#healthDiag>#srccap .scfoot').style.removeProperty('margin-left')}")


PACE = """() => {
  const rows=[...document.querySelectorAll('#hbody .hrow')].map(e=>+e.getBoundingClientRect().height.toFixed(1));
  const pr=[...document.querySelectorAll('#paceBox .pace-row')].map(e=>+e.getBoundingClientRect().height.toFixed(1));
  const side=document.querySelector('#paceBox .pace-side');
  const chips=[...document.querySelectorAll('#paceBox .pstrip .pchip')];
  const byTop={};chips.forEach(e=>{if(e.getBoundingClientRect().width<2)return;
    const t=Math.round(e.getBoundingClientRect().top);byTop[t]=(byTop[t]||0)+1});
  const body=document.querySelector('#paceBox .pace-body');
  const main=document.querySelector('#paceBox .pace-main');
  return {healthMax:rows.length?Math.max(...rows):0,paceMax:pr.length?Math.max(...pr):0,
    sideW:side?+side.getBoundingClientRect().width.toFixed(1):0,
    bodyW:body?+body.getBoundingClientRect().width.toFixed(1):0,
    mainW:main?+main.getBoundingClientRect().width.toFixed(1):0,
    chipPerRow:Math.max(0,...Object.values(byTop)),nChips:chips.length};
}"""


def test_health_and_pacing_density(pg):
    page, _ = pg
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_timeout(1400)
    d = page.evaluate(PACE)
    assert d["healthMax"] <= 56, d
    assert d["paceMax"] <= 64, d
    # r1454：节流区单列，逐渠道占满整宽；340px 侧栏已取消。
    assert abs(d["mainW"] - d["bodyW"]) <= 1, d
    assert d["chipPerRow"] <= 4, d
    page.evaluate("()=>{const m=document.querySelector('#paceBox .pace-main');m.style.setProperty('width','500px','important')}")
    assert abs(page.evaluate(PACE)["mainW"] - d["bodyW"]) > 2, "负控失败：500px 主区没被拦"
    page.evaluate("()=>{const m=document.querySelector('#paceBox .pace-main');m.style.removeProperty('width')}")


CFG = """() => {
  const g=document.querySelector('#cfgpacingRows .sgrid');
  if(!g)return {err:'no sgrid'};
  const labs=[...document.querySelectorAll('#cfgpacingRows .glab')].map(e=>e.textContent.trim());
  const cells=[...g.querySelectorAll('.glcell')];
  const mis=cells.filter(c=>{const l=c.querySelector('.glab'),i=c.querySelector('input,select,.sro');
    if(!l||!i)return false;return Math.abs(l.getBoundingClientRect().top-i.getBoundingClientRect().top)>8}).length;
  return {cols:getComputedStyle(g).gridTemplateColumns.split(/\\s+/).filter(Boolean).length,
    vals:labs.filter(x=>x==='取值').length,misaligned:mis,n:cells.length};
}"""


def test_config_twelve_col_grid_no_repeated_label(pg):
    page, _ = pg
    page.evaluate("switchView('cfg');showCfgPanel('pacing')")
    # r1451：节流面板的行是**异步**渲的（loadPacing）。原来固定等 1500ms，
    # 慢机上 `.sgrid` 还没建出来 → CFG 探针返回 `no sgrid`（假红）。
    # 改成等网格出现；等不到就主动调一次 loadPacing 再等。
    try:
        page.wait_for_function(
            "()=>!!document.querySelector('#cfgpacingRows .sgrid')", timeout=8000)
    except Exception:
        page.evaluate("()=>{try{loadPacing()}catch(e){}}")
        page.wait_for_function(
            "()=>!!document.querySelector('#cfgpacingRows .sgrid')", timeout=20000)
    page.evaluate("()=>{document.querySelectorAll('#cfgpacingRows .srow .sfold').forEach(b=>{if(!b.closest('.srow').classList.contains('open'))b.click()})}")
    page.wait_for_timeout(400)
    d = page.evaluate(CFG)
    assert not d.get("err"), d
    assert d["cols"] == 12, d
    assert d["vals"] == 0, d
    assert d["misaligned"] == 0, d
    page.evaluate("""()=>{const g=document.querySelector('#cfgpacingRows .sgrid');
      const x=document.createElement('div');x.className='glab';x.textContent='取值';g.appendChild(x)}""")
    assert page.evaluate(CFG)["vals"] == 1, "负控失败：重复取值没被数到"
    page.evaluate("()=>{document.querySelector('#cfgpacingRows .sgrid>.glab').remove()}")


FILTER = """() => {
  const cards=[...document.querySelectorAll('#srxCtxFly .srf-card')];
  let maxRows=0,bad=[];
  cards.forEach(card=>{
    card.querySelectorAll('.srf-chips').forEach(ch=>{
      const cr=ch.getBoundingClientRect();
      const tops=[...new Set([...ch.children].filter(e=>{const r=e.getBoundingClientRect();
        return r.width>2&&r.top<cr.bottom-1&&r.bottom<=cr.bottom+1})
        .map(e=>Math.round(e.getBoundingClientRect().top)))];
      maxRows=Math.max(maxRows,tops.length);
      if(tops.length>2)bad.push({card:(card.querySelector('header b')||{}).textContent,n:tops.length});
    });
  });
  return {maxRows,bad:bad.slice(0,3),n:cards.length};
}"""


def test_filter_groups_max_two_chip_rows(pg):
    page, _ = pg
    page.evaluate("document.getElementById('srxFilterBtn').click()")
    page.wait_for_timeout(900)
    d = page.evaluate(FILTER)
    assert d["n"] > 0 and d["maxRows"] <= 2, d
    page.evaluate("""()=>{const ch=document.querySelector('#srxCtxFly .srf-chips');
      const card=ch&&ch.closest('.srf-card');
      if(card)card.classList.add('srf-expanded');
      if(ch){ch.style.maxHeight='none';ch.style.overflow='visible';
        for(let i=0;i<40;i++){const b=document.createElement('button');b.className='srf-opt';b.textContent='负控'+i;ch.appendChild(b)}}}""")
    assert page.evaluate(FILTER)["maxRows"] > 2, "负控失败：10 颗 chip 没被拦"
