# -*- coding: utf-8 -*-
"""r339 WebUI 审计落地（_scratch/r339d_report.md 九案 TDD）：

D1(P1)+D2(P2) 日期片 inline 排版族——.chip 基类无 display（默认
inline）：片内日期 token 断行（「2026-」/「11-08」拆两行）+ 换行片
垂直叠压 -5~-37px（inline 纵向 padding 不撑行盒）+ 桌面档相邻片零
间距（.chip+.chip margin 只在触控块）使 ✕ 热区 -14px 左向侵入邻片。
一处收口：.dchips flex wrap gap + .dchip inline-flex。
D3(P2) 390 档 sctl flex:none 不可收缩 → 行尾控件越界被 .rline
overflow:hidden 裁 17px（含 Bark Key 输入 126px 收窄=D8 同根）。
D4(P2) 通路验证按钮出卡 44px（chcard overflowX visible）。
D5(P3) rthead 触控 36 地板缺 ≤900coarse/≤760 两块（三触控块互指
纪律）。D6(P3) chhead 命中 35<36（::after 纵向 -10px）。
D7(P3) 返程「去程起30天」恒死钮（上限 8 恒拒）——截断+明示。
D9(P3) 重复加返程只 toast 不刷新 cfgmsg（页顶陈旧硬错误句）。

行为钉采样环境：demo 实例（POST 只读拦截）、Chromium headless、
1440/390 两视口独立 context；几何断言在展开态+7 片在场条件下量
（display:none 容器量纲全零，LESSONS 十九§8）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339_webui.py -q
"""
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

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
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
        if _wait_up(proc):
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture()
def page(srv):
    """每用例独立 context + 零 JS 错收集（teardown 统一裁决）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg._errs = errs
        yield pg
        browser.close()


@pytest.fixture()
def page390(srv):
    """390×844 移动档 context（D3/D4 几何）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg._errs = errs
        yield pg
        browser.close()


def _to_cfg(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.locator("#navCfg").click()
    pg.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    pg.locator('.cnav[data-p="users"]').click()
    pg.wait_for_timeout(250)


def _open_rt_with_7(pg):
    """进配置 users 面板→展开 0:0→开往返→快速选 7 天（D1/D3 共同
    前置；折叠展开走真实点击路径）。"""
    _to_cfg(pg)
    pg.evaluate("""()=>{const h=document.querySelector('.rline[data-rk="0:0"] .rhead');
      if(h&&h.getAttribute('aria-expanded')==='false')h.click();}""")
    pg.wait_for_timeout(400)
    pg.evaluate("""()=>{const chip=[...document.querySelectorAll(
        '.rline[data-rk="0:0"] .schip')]
        .find(c=>c.textContent.indexOf('往返')>=0);
      /* 幂等开：toggleRT 是开合开关，前序测试残留开态时再点=关闭
         （n=1 实录）——chip.on 态才是真实语义位 */
      if(chip&&!chip.classList.contains('on'))chip.click();}""")
    pg.wait_for_timeout(400)
    pg.evaluate("""()=>{const inp=document.getElementById('rfrom-0-0');
      const row=inp&&inp.closest('.srow');
      const dt=row&&row.querySelector('.dline.dtools');
      /* ce35272 渐进披露：工具组折叠 display:none 后 D3 的裁切缘
         断言对零几何恒绿（死钉化）——先真实展开「＋ 添加」恢复牙齿 */
      if(dt&&!dt.classList.contains('open')){
        const t=row.querySelector('.dtools-t');if(t)t.click();}}""")
    pg.wait_for_timeout(300)
    pg.evaluate("""()=>{const q=[...document.querySelectorAll(
        '.rline[data-rk="0:0"] .schip')]
        .find(c=>c.textContent==='去程起7天');if(q)q.click();}""")
    pg.wait_for_timeout(500)


# ---- D1+D2：日期片 flex 排版 ----

def test_dchips_flex_no_token_break_no_overlap(page):
    _open_rt_with_7(page)
    out = page.evaluate("""(()=>{
      const box=document.getElementById('rdchips-0-0');
      if(!box)return {missing:true};
      const cs=getComputedStyle(box);
      const chips=[...box.querySelectorAll('.dchip')];
      const chipCs=chips[0]?getComputedStyle(chips[0]):null;
      const rects=chips.map(c=>{const r=c.getBoundingClientRect();return {t:r.top,b:r.bottom,l:r.left,w:r.width};});
      const gaps=[];
      for(let i=1;i<rects.length;i++){
        if(Math.abs(rects[i].t-rects[i-1].t)<2)gaps.push(rects[i].l-rects[i-1].l-rects[i-1].w);}
      const vover=[];
      for(let i=1;i<rects.length;i++){
        if(rects[i].t>rects[i-1].t+2)vover.push(+(rects[i-1].b-rects[i].t).toFixed(1));}
      return {display:cs.display,chipDisplay:chipCs?chipCs.display:null,
              gaps,vover,n:chips.length};})()""")
    assert not out.get("missing"), "返程片群未渲染"
    assert out["display"] == "flex", out
    # 断裂根因=inline：片挂盒化 display 后日期 token 不可断行
    # （flex 容器子项的 inline-flex computed 按规范块化为 flex，
    # 两态均合格，唯一坏态=inline）
    assert out["chipDisplay"] in ("inline-flex", "flex"), out
    assert out["n"] == 7, out
    assert all(abs(g - 6) < 1.5 for g in out["gaps"]), f"相邻片间距破 6px：{out['gaps']}"
    assert all(v <= 0.5 for v in out["vover"]), f"换行片垂直叠压：{out['vover']}"
    assert not page._errs, page._errs


# ---- D3：390 档行尾控件不越裁切缘 ----

def test_rtrow_controls_not_clipped_390(page390):
    _open_rt_with_7(page390)
    out = page390.evaluate("""(()=>{
      const rl=document.querySelector('.rline[data-rk="0:0"]');
      const rr=rl.getBoundingClientRect();
      const clipR=rr.right-1;   // .rline padding-box 右缘-border（审计口径）
      const ctl=[...rl.querySelectorAll('.sctl button,.sctl input,.sctl .chip')];
      const over=ctl.map(el=>{const r=el.getBoundingClientRect();
        return {tag:el.tagName,txt:(el.textContent||el.value||'').slice(0,10),
                poke:+(r.right-clipR).toFixed(1)};})
        .filter(x=>x.poke>1);
      return {clipR:+clipR.toFixed(1),over};})()""")
    assert not out["over"], f"390 档控件越裁切缘：{out['over']}"
    assert not page390._errs, page390._errs


# ---- D4：通路验证钮不出卡（390） ----

def test_bark_verify_btn_inside_card_390(page390):
    _to_cfg(page390)
    page390.evaluate("""()=>{const h=document.querySelector('.chcard[data-ch="bark"] .chhead');
      if(h&&h.getAttribute('aria-expanded')==='false')h.click();}""")
    page390.wait_for_timeout(400)
    out = page390.evaluate("""(()=>{
      const card=document.querySelector('.chcard[data-ch="bark"]');
      if(!card)return {missing:true};
      const cr=card.getBoundingClientRect();
      const btn=[...card.querySelectorAll('button')]
        .find(b=>/测试 Bark/.test(b.textContent));
      if(!btn)return {noBtn:true};
      const br=btn.getBoundingClientRect();
      return {poke:+(br.right-cr.right).toFixed(1)};})()""")
    assert not out.get("missing"), "Bark 卡未渲染"
    assert not out.get("noBtn"), "验证钮未渲染"
    assert out["poke"] <= 1, f"验证钮出卡 {out['poke']}px"
    assert not page390._errs, page390._errs


# ---- D5/D6：触控地板声明（源码钉，块归属断言） ----

def test_rthead_touch_floor_in_both_touch_blocks():
    mod = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    needle = ".rthead{min-height:36px}"
    assert mod.count(needle) >= 2, "rthead 36 地板声明 <2（触控地板缺块）"
    # 按声明归属的最近 @media 条件定性（对子句换序/块重组免疫；
    # 固定窗/固定块序锚都会随合法增厚假红，LESSONS 卅一§3）。
    # 近似盲区备案：嵌套块结束后同层的基础规则会误归属到嵌套条件——
    # 方向安全（多报不漏报），声明迁移出触控块仍会被 any 断言抓住
    ctxs = []
    for m in re.finditer(re.escape(needle), mod):
        ctx = mod[:m.start()]
        i = ctx.rfind("@media")
        ctxs.append(ctx[i: ctx.find("{", i)] if i >= 0 else "")
    assert any("coarse" in c for c in ctxs), f"无 coarse 块承载 36 地板：{ctxs}"
    assert any("760" in c for c in ctxs), f"无 760 块承载 36 地板：{ctxs}"


def test_chhead_after_inset_reaches_36():
    mod = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert ".chhead[role=button]::after{content:'';position:absolute;inset:-10px -8px}" in mod


# ---- D7：快速选 30 天截断+明示 ----

def test_quick_ret_30_truncates_to_cap8(page):
    """r345：UI 只给合法 7/8 天档；底层 quickRet 仍硬封顶 8（防脚本/旧链）。"""
    _open_rt_with_7(page)
    assert page.evaluate("""()=>[...document.querySelectorAll(
      '.rline[data-rk="0:0"] .schip')].some(c=>c.textContent==='去程起30天')""") is False
    out = page.evaluate("""(()=>{quickRet(0,0,30);
      return {n:(CFG[0].routes[0].ret_dates||[]).length};})()""")
    page.wait_for_timeout(300)
    assert out["n"] == 8, f"quickRet 未按上限截断：{out['n']} 片"
    assert not page._errs, page._errs


# ---- D9：重复加返程刷新 cfgmsg ----

def test_dup_add_refreshes_cfgmsg(page):
    _open_rt_with_7(page)
    out = page.evaluate("""()=>{
      const ds=CFG[0].routes[0].ret_dates;
      const inp=document.getElementById('radd-0-0');
      inp.value=ds[0];
      retAdd(0,0);
      const m=document.getElementById('cfgmsg');
      return {cfgmsg:m?m.textContent:''};}""")
    assert "已在列表" in out["cfgmsg"], \
        f"页顶 cfgmsg 未随 dup 刷新（陈旧硬错误句）：{out['cfgmsg']!r}"
    assert not page._errs, page._errs
