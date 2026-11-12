# -*- coding: utf-8 -*-
"""r719 手机宽度（390）下，所有展示渠道的地方都要把 7 家排进去且不越界。

用户原话：「多渠道接入进来各个页面的布局排版……例如渠道健康，渠道登录，
渠道配置，渠道的检索，实时检索页面等等各个页面渠道信息的展示」。
桌面档已由 r708/r709/r715 覆盖；这条守的是**手机宽度**——7 家比 5 家宽，
最容易在窄档挤出去或被裁。

逐个量渲染结果：配置页 chip、特价雷达查询渠道勾选、特价雷达渠道入口板、
检索台渠道快筛、登录弹窗。

判据都要求容器**确已可见**（getBoundingClientRect().width>0）——折叠容器
量出 0 会让「无溢出」恒真（本轮已在 #srxPlats 上踩过，必须先 SRX.ctx=true）。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="窄档普查依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, plat_cn

APPS = tuple(plat_cn(p) for p in APP_CHANNELS)
BROWSERS = tuple(plat_cn(p) for p in BROWSER_CHANNELS)
ALL_CN = BROWSERS + APPS


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r719_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
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


@pytest.fixture(scope="module")
def mobile_page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844},
                        is_mobile=True, has_touch=True, device_scale_factor=2)
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        yield pg
        b.close()


def test_config_channel_chips_fit_phone_width(mobile_page):
    mobile_page.evaluate("switchView('cfg');showCfgPanel('users')")
    mobile_page.wait_for_timeout(1800)
    out = mobile_page.evaluate("""(() => {
      const chips=[...document.querySelectorAll('#cfgform .pch')];
      return {n:chips.length,
        names:chips.map(c=>(c.textContent||'').trim()),
        clipped:chips.filter(c=>c.scrollWidth>c.clientWidth+1).length,
        outside:chips.filter(c=>{const r=c.getBoundingClientRect();
          return r.left<-1||r.right>window.innerWidth+1}).length};
    })()""")
    assert out["n"] >= len(ALL_CN), out
    for name in BROWSERS + APPS:
        assert any(t.startswith(name) for t in out["names"]), (
            "390 档配置页缺「%s」：%s" % (name, out["names"]))
    assert out["clipped"] == 0, "390 档渠道 chip 有裁切"
    assert out["outside"] == 0, "390 档渠道 chip 越出视口"


def test_radar_channel_toggles_fit_phone_width(mobile_page):
    mobile_page.evaluate("switchView('cfg');showCfgPanel('users')")
    mobile_page.wait_for_timeout(1500)
    out = mobile_page.evaluate("""(() => {
      const labels=[...document.querySelectorAll('#cfgform label.cwf-chip')]
        .filter(l=>l.querySelector('input[data-radch]'));
      return {n:labels.length,
        vals:labels.map(l=>l.querySelector('input').dataset.radch),
        clipped:labels.filter(l=>l.scrollWidth>l.clientWidth+1).length,
        outside:labels.filter(l=>{const r=l.getBoundingClientRect();
          return r.left<-1||r.right>window.innerWidth+1}).length};
    })()""")
    assert out["n"] >= len(ALL_CN), out
    for p in BROWSER_CHANNELS + APP_CHANNELS:
        assert p in out["vals"], "390 档特价雷达缺渠道 %s：%s" % (p, out["vals"])
    assert out["clipped"] == 0, "390 档雷达渠道勾选被裁"
    assert out["outside"] == 0, "390 档雷达渠道勾选越出视口"


def test_radar_entry_board_has_all_registered_at_phone_width(mobile_page):
    mobile_page.evaluate("switchView('mon');showMonTab('specials')")
    mobile_page.wait_for_timeout(3000)
    try:
        mobile_page.evaluate("srxSpLoad(true)")
    except Exception:
        pass
    # r1457：入口板由 /api 异步渲染。原来固定等 2200ms 就数量/几何，
    # 慢机上量到 0 条 band（假红）。改成等 band 出现（等不到就再驱动一次）。
    try:
        mobile_page.wait_for_function(
            "()=>document.querySelectorAll('#spentryboard .chband').length>=5",
            timeout=8000)
    except Exception:
        try:
            mobile_page.evaluate("srxSpLoad(true)")
        except Exception:
            pass
        mobile_page.wait_for_function(
            "()=>document.querySelectorAll('#spentryboard .chband').length>=5",
            timeout=20000)
    out = mobile_page.evaluate("""(() => {
      const b=document.getElementById('spentryboard');
      if(!b) return {exists:false};
      const bands=[...b.querySelectorAll('.chband')];
      return {exists:true, w:Math.round(b.getBoundingClientRect().width),
              bands:bands.length,
              over:b.scrollWidth>b.clientWidth+1,
              outside:bands.filter(x=>{const r=x.getBoundingClientRect();
                return r.right>window.innerWidth+1}).length,
              names:bands.map(x=>{const e=x.querySelector('.chband-name b');
                return e?(e.textContent||'').trim():null}).filter(Boolean)};
    })()""")
    if not out.get("exists"):
        pytest.skip("特价雷达入口板未渲染")
    assert out["w"] > 0, "入口板宽度 0，测量无效"
    assert out["bands"] == len(ALL_CN), out["names"]
    for name in APPS:
        assert name in out["names"], "390 档雷达入口板缺「%s」：%s" % (name, out["names"])
    assert not out["over"], "390 档雷达入口板横向溢出"
    assert out["outside"] == 0, "390 档雷达入口板越出视口"


def test_search_channel_chips_fit_phone_width(mobile_page):
    mobile_page.evaluate("switchView('search')")
    mobile_page.wait_for_timeout(2800)
    # 手机端的真实入口是移动栏的「展开筛选」：srxToggleMobile('filters')
    # 会加 show-filters 并同时置 SRX.ctx=true。只设 SRX.ctx 不够——
    # `#searchview:not(.show-filters) .srx-context{display:none}` 仍会藏住它，
    # 这样量出来的宽 0 与「无溢出」会一起变成假绿（本轮实测踩到）。
    opened = mobile_page.evaluate("""(() => {
      const v=document.getElementById('searchview');
      if(!v.classList.contains('show-filters')) srxToggleMobile('filters');
      const box=document.getElementById('srxPlats');
      return {showFilters:v.classList.contains('show-filters'),
              boxW:box?Math.round(box.getBoundingClientRect().width):0};
    })()""")
    mobile_page.wait_for_timeout(1200)
    assert opened["showFilters"], "手机端「展开筛选」没生效"
    assert opened["boxW"] > 0, "手机端展开筛选后渠道快筛仍不可见"
    # r1052：渠道快筛在窄档不再 10 家铺成 3~4 行，而是**单行横滑**
    # （轨内 overflow-x:auto + 右缘渐隐）。因此“无横向溢出”不再是正确判据——
    # 重要的是：单行、文字不裁、左端首家完整可见、滑到末尾末家完整可达、
    # 容器自身不出视口、容器高度只有一行。
    out = mobile_page.evaluate("""(() => {
      const box=document.getElementById('srxPlats');
      if(!box) return {exists:false};
      const chips=[...box.querySelectorAll('.srx-chip')];
      const cs=getComputedStyle(box);
      const tops=chips.map(c=>Math.round(c.getBoundingClientRect().top));
      const rows=new Set(tops).size;
      const boxR=box.getBoundingClientRect();
      const first=chips[0]?chips[0].getBoundingClientRect():null;
      const before={scrollW:box.scrollWidth,clientW:box.clientWidth,
        rows, h:Math.round(boxR.height),
        chipsH:chips.map(c=>Math.round(c.getBoundingClientRect().height)),
        overflowX:cs.overflowX, wrap:cs.flexWrap,
        mask:(cs.maskImage||cs.webkitMaskImage||'none')!=='none',
        boxL:Math.round(boxR.left),boxR:Math.round(boxR.right),
        firstL:first?Math.round(first.left):null};
      box.scrollLeft=box.scrollWidth;
      const last=chips.length?chips[chips.length-1].getBoundingClientRect():null;
      const lastVisible=last?(last.right<=Math.round(boxR.right)+1&&last.left>=Math.round(boxR.left)-1):false;
      box.scrollLeft=0;
      return {exists:true, boxW:Math.round(boxR.width),
        n:chips.length,
        labels:chips.map(c=>(c.textContent||'').trim()),
        clipped:chips.filter(c=>c.scrollWidth>c.clientWidth+1).length,
        before, lastVisible,
        scrollable:before.scrollW>before.clientW+1};
    })()""")
    if not out.get("exists"):
        pytest.skip("检索台未渲染渠道快筛")
    assert out["boxW"] > 0, "390 档快筛容器宽 0（折叠态），测量无效"
    for name in BROWSERS + APPS:
        assert any(t.startswith(name) for t in out["labels"]), (
            "390 档检索台缺「%s」：%s" % (name, out["labels"]))
    b = out["before"]
    assert b["rows"] == 1, "390 档渠道快筛应单行，实为 %s 行" % b["rows"]
    assert b["wrap"] == "nowrap", "390 档渠道快筛仍允许换行：%s" % b["wrap"]
    assert b["overflowX"] in ("auto", "scroll"), "390 档渠道快筛不是可横滑轨：%s" % b["overflowX"]
    # 单行高度：容器不高于一个 chip 太多（含内衬）
    assert b["h"] <= max(b["chipsH"]) + 16, (
        "390 档快筛容器高 %s 超过单行 chip 高 %s" % (b["h"], max(b["chipsH"])))
    assert b["mask"], "390 档快筛缺少右缘渐隐提示"
    assert b["boxL"] >= -1 and b["boxR"] <= 390 + 1, "390 档快筛容器越出视口：%s~%s" % (
        b["boxL"], b["boxR"])
    assert b["firstL"] is not None and b["firstL"] >= b["boxL"] - 1, "首家渠道被裁在左缘外"
    assert out["scrollable"], "390 档 10 家渠道应超出一行并可横滑"
    assert out["lastVisible"], "滑到末尾时末家渠道不可完整到达"
    assert out["clipped"] == 0, "390 档快筛文字被裁"
    # r1052b：渐隐随滚动位置换边——滑到末端必须撤掉右缘蒙层（否则最后
    # 一家 chip 的文字仍被淡化）、改在左缘提示「前面还有」。
    mobile_page.evaluate("""(() => {const b=document.getElementById('srxPlats');
      b.scrollLeft=b.scrollWidth})()""")
    mobile_page.wait_for_timeout(150)
    end = mobile_page.evaluate("""(() => {
      const b=document.getElementById('srxPlats');const cs=getComputedStyle(b);
      return {cls:b.className, atEnd:b.scrollLeft+b.clientWidth>=b.scrollWidth-1,
        mask:(cs.maskImage||cs.webkitMaskImage||'none')};
    })()""")
    assert end["atEnd"], "渠道快筛没能滑到末端"
    assert "rail-fade-left" in end["cls"], "末端缺少左缘渐隐提示"
    assert "rail-fade-right" not in end["cls"], "末端仍盖着右缘渐隐，最后一家文字会被淡化"
    assert end["mask"] != "none", "末端左缘渐隐没有真正生效"
    mobile_page.evaluate("""(() => {const b=document.getElementById('srxPlats');
      b.scrollLeft=0})()""")


def test_login_modal_fits_phone_viewport(mobile_page):
    mobile_page.evaluate("switchView('cfg');showCfgPanel('login')")
    mobile_page.wait_for_timeout(1800)
    mobile_page.evaluate("lgOpenFliggy()")
    mobile_page.wait_for_timeout(900)
    out = mobile_page.evaluate("""(() => {
      const m=document.getElementById('lgModal');
      if(!m||!m.classList.contains('open')) return {open:false};
      const r=m.getBoundingClientRect();
      return {open:true, w:Math.round(r.width), L:Math.round(r.left),
              R:Math.round(r.right),
              inside:r.left>=-1 && r.right<=window.innerWidth+1,
              over:m.scrollWidth>m.clientWidth+1};
    })()""")
    assert out["open"], "390 档登录弹窗没打开"
    assert out["inside"], out
    assert out["w"] >= 300, "390 档弹窗过窄：%s" % out
    assert not out["over"], "390 档弹窗横向溢出"
