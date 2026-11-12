# -*- coding: utf-8 -*-
"""r1132：真实渲染兜住三类「门禁绿、用户仍看到乱」的缺陷。

1) 探针渠道浮层 portal 到 #searchview 后丢了卡面样式（背景透明、无边框/
   内衬），文案与渠道行叠在一起；收起探针后 details 仍 open，浮层按默认
   8/80 贴到左上角成为无主浮层。
2) 登录开窗按钮把「（等采集让出该渠道）」塞进 96px 按钮，文字向左溢出，
   压住同卡状态行 / 相邻行。
3) 12 列网格把嵌套的 .secbody 当成一个 60px 网格项，Android 参数整段
   挤成一条窄柱，右侧全空。

每项都配负控：故意恢复缺陷形态，同一探测函数必须判红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

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
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
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
        page = b.new_page(viewport={"width": 1191, "height": 950})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
        page.wait_for_timeout(900)
        yield page, errs
        b.close()


POP = """() => {
  const pop=document.getElementById('srxPlatPop'), dd=document.getElementById('srxPlatDD');
  const btn=document.getElementById('srxPlatBtn');
  if(!pop||!dd||!btn)return {exists:false};
  const r=pop.getBoundingClientRect(), b=btn.getBoundingClientRect(), c=getComputedStyle(pop);
  const br=b.right||0;
  return {exists:true, open:dd.open, parent:pop.parentElement.id||'',
    pos:c.position, bg:c.backgroundColor, border:c.borderTopWidth, pad:c.paddingLeft,
    x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1), h:+r.height.toFixed(1),
    btnB:+b.bottom.toFixed(1), header:pop.querySelector('.srx-platpop-h')?pop.querySelector('.srx-platpop-h').getBoundingClientRect().height:0,
    chips:pop.querySelectorAll('.srx-pchip').length,
    inView:r.x>=-1&&r.right<=innerWidth+1};
}"""


def _pop_bad(d):
    bad=[]
    if not d.get("exists"): return ["浮层不存在"]
    if not d["open"]: bad.append("details 未打开")
    if d["parent"]!="searchview": bad.append("未 portal 到 #searchview：%s"%d["parent"])
    if d["pos"]!="fixed": bad.append("position=%s"%d["pos"])
    if d["bg"] in ("rgba(0, 0, 0, 0)","transparent"): bad.append("卡面背景透明")
    if d["border"] in ("0px","0"): bad.append("无边框")
    if d["pad"] in ("0px","0"): bad.append("无内衬")
    if d["header"]<10: bad.append("表头未渲染")
    if d["chips"]<10: bad.append("渠道 chip 只有 %d"%d["chips"])
    if d["y"]<d["btnB"]+3: bad.append("浮层压在触发器上：y=%s btnB=%s"%(d["y"],d["btnB"]))
    if not d["inView"]: bad.append("浮层越出视口")
    return bad


def test_channel_picker_chrome_and_collapse(pg):
    page, errs = pg
    page.evaluate("switchView('search')")
    page.wait_for_timeout(900)
    page.evaluate("()=>{const p=document.getElementById('srxProbe');"
                  "if(p&&!p.classList.contains('open'))document.getElementById('srxProbeTool').click()}")
    page.wait_for_timeout(500)
    page.evaluate("()=>{const d=document.getElementById('srxPlatDD');"
                  "if(d&&!d.open)d.querySelector('summary').click()}")
    page.wait_for_timeout(500)
    d=page.evaluate(POP)
    assert not _pop_bad(d), (d, errs)
    # 负控：把浮层拉回触发器上方，必须判红
    page.evaluate("()=>{const p=document.getElementById('srxPlatPop');"
                  "p.style.setProperty('top','0px','important')}")
    assert _pop_bad(page.evaluate(POP)), "负控失败：浮层压触发器没被拦"
    page.evaluate("()=>{const p=document.getElementById('srxPlatPop');"
                  "p.style.removeProperty('top')}")
    # 收起探针 → 浮层必须关闭
    page.evaluate("()=>{const p=document.getElementById('srxProbe');"
                  "if(p.classList.contains('open'))document.getElementById('srxProbeTool').click()}")
    page.wait_for_timeout(500)
    d2=page.evaluate("()=>({open:document.getElementById('srxPlatDD').open,"
                      "disp:getComputedStyle(document.getElementById('srxPlatPop')).display})")
    assert d2["open"] is False and d2["disp"]=="none", d2


WAIT = """() => {
  const c=[...document.querySelectorAll('#cfgview .lgcard')]
    .find(x=>(x.innerText||'').includes('智行 App'));
  if(!c)return {exists:false};
  const b=c.querySelector('.btn2'); if(!b)return {exists:false};
  const cr=c.getBoundingClientRect(), br=b.getBoundingClientRect();
  return {exists:true, txt:b.textContent.trim(), title:b.title,
    sw:b.scrollWidth, cw:b.clientWidth, ell:getComputedStyle(b).textOverflow,
    inside:br.left>=cr.left-1&&br.right<=cr.right+1};
}"""


def _wait_bad(d):
    if not d.get("exists"): return ["卡片不存在"]
    bad=[]
    if d["sw"]>d["cw"]+1 and d["ell"]!="ellipsis": bad.append("按钮文字溢出且未省略")
    if not d["title"]: bad.append("长说明没有 title")
    if not d["inside"]: bad.append("按钮越出卡片")
    if "（" in d["txt"]: bad.append("长括注仍塞在按钮里")
    return bad


def test_login_wait_button_does_not_overflow(pg):
    page, _ = pg
    page.evaluate("switchView('cfg')")
    page.wait_for_timeout(900)
    page.evaluate("""()=>{const b=document.querySelector('#cfgview .cfgnav .cnav[data-p="login"]');
      if(b)b.click()}""")
    page.wait_for_timeout(700)
    page.evaluate("()=>{LOGIN_WAIT['app_zhixing']={t0:Date.now()-32000};renderLoginCards(true)}")
    page.wait_for_timeout(500)
    d=page.evaluate(WAIT)
    assert not _wait_bad(d), d
    # 负控：恢复旧长文案，必须判红
    page.evaluate("""()=>{const b=[...document.querySelectorAll('#cfgview .lgcard')]
      .find(x=>(x.innerText||'').includes('智行 App')).querySelector('.btn2');
      b.textContent='正在打开窗口… 32s（等采集让出该渠道）';
      b.style.overflow='visible';b.style.textOverflow='clip'}""")
    assert _wait_bad(page.evaluate(WAIT)), "负控失败：长文案溢出没被拦"
    page.evaluate("()=>{try{delete LOGIN_WAIT['app_zhixing']}catch(e){}}")


SEC = """() => {
  const h=[...document.querySelectorAll('#cfgview *')]
    .find(e=>e.children.length===0&&(e.textContent||'').includes('设备身份指纹'));
  if(!h)return {exists:false};
  const cell=h.closest('.glcell'); if(!cell)return {exists:false};
  const grid=cell.parentElement&&cell.parentElement.parentElement;
  const cr=cell.getBoundingClientRect(), gr=grid?grid.getBoundingClientRect():null;
  return {exists:true, w:+cr.width.toFixed(1), gw:gr?+gr.width.toFixed(1):0};
}"""


def test_config_nested_section_is_not_narrow_column(pg):
    page, _ = pg
    page.evaluate("switchView('cfg')")
    page.wait_for_timeout(900)
    page.evaluate("""()=>{const b=document.querySelector('#cfgview .cfgnav .cnav[data-p="globals"]');
      if(b)b.click()}""")
    page.wait_for_timeout(900)
    d=page.evaluate(SEC)
    assert d.get("exists"), "Android 参数格未渲染"
    assert d["w"] >= max(300, d["gw"] * 0.5), "Android 参数格被挤成窄柱：%s" % d
    # 负控：把参数格压回 60px，必须判红
    page.evaluate("""()=>{const h=[...document.querySelectorAll('#cfgview *')]
      .find(e=>e.children.length===0&&(e.textContent||'').includes('设备身份指纹'));
      h.closest('.glcell').style.width='60px'}""")
    d2=page.evaluate(SEC)
    assert d2["w"] < max(300, d2["gw"] * 0.5), "负控失败：60px 窄柱没被拦"
    page.evaluate("""()=>{const h=[...document.querySelectorAll('#cfgview *')]
      .find(e=>e.children.length===0&&(e.textContent||'').includes('设备身份指纹'));
      h.closest('.glcell').style.width=''}""")
