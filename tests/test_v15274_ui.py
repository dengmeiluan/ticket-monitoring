# -*- coding: utf-8 -*-
"""1.5.274 chart-domain and mobile-detail pins."""
import os
import sys

import pytest

import webui

SRC = open(webui.__file__, encoding="utf-8").read()

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
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
    global BASE
    import subprocess
    import tempfile
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    priv_tmp = tempfile.mkdtemp(prefix="v15274_")
    render_tmp = tempfile.mkdtemp(prefix="v15274_render_")
    env = dict(os.environ, TEMP=priv_tmp, TMP=priv_tmp, TMPDIR=priv_tmp,
               TM_RENDER_DIR=render_tmp)
    proc = None
    for _attempt in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if _wait_up(proc):
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" else None)
        pg.errs = errs
        yield pg
        assert not errs, errs
        ctx.close()
        browser.close()


def _boot(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")


def test_chart_domain_follows_observed_span(page):
    _boot(page)
    page.evaluate("switchView('mon');showMonTab('watch')")
    page.wait_for_timeout(1200)
    page.evaluate("()=>{const b=document.querySelector('[data-wsrange=\"30\"]');"
                  "if(b)b.click()}")
    page.wait_for_timeout(900)
    got = page.evaluate("""()=>{const ci=WS.chartInfo;const s=(ci&&ci.series||[])[0];
      const pts=(s&&s.pts||[]).filter(p=>p.t>=ci.x0);
      const first=Math.min(...pts.map(p=>p.t));
      return {range:WS.range,left:(first-ci.x0)/(ci.x1-ci.x0),
              span:ci.x1-ci.x0};}""")
    assert got["range"] == 30
    assert got["left"] < 0.15, got
    assert got["span"] <= 30 * 864e5 + 36e5, got


def test_source_contracts():
    assert "let x0=Math.max(win,first), x1=Math.min(now,last+_obs*.02)" in SRC
    assert "grid-template-areas:\"price price price\" \"flight flight flight\" \"dep arr arr\"" in SRC
    assert "#tablecard .tw{overflow:visible" in SRC
    # ≤1100 的横滚渐隐同特异性后置，必须显式 !important 收口
    assert "@media(max-width:900px){#tablecard .tw{-webkit-mask-image:none!important" in SRC


def test_768_tablet_uses_cards(page):
    """761-900 带不再拿 971px 的 9 列表硬塞 672px 容器。"""
    page.set_viewport_size({"width": 768, "height": 900})
    _boot(page)
    page.evaluate("switchView('mon');showMonTab('details')")
    page.wait_for_timeout(900)
    got = page.evaluate("""()=>{const tw=document.querySelector('#tablecard .tw');
      const tr=document.querySelector('#ftable tbody tr[data-k]');
      const hint=document.querySelector('.tw-hint');
      return {cw:tw.clientWidth,sw:tw.scrollWidth,disp:getComputedStyle(tr).display,
              th:getComputedStyle(document.querySelector('#ftable thead')).display,
              hint:hint?getComputedStyle(hint).display:null,
              ow:document.documentElement.scrollWidth-window.innerWidth};}""")
    assert got["sw"] <= got["cw"], got
    assert got["disp"] == "grid", got
    assert got["th"] == "none", got
    assert got["hint"] == "none", got
    assert got["ow"] <= 0, got


def test_empty_filter_row_keeps_height_and_width(page):
    page.set_viewport_size({"width": 390, "height": 844})
    _boot(page)
    page.evaluate("switchView('mon');showMonTab('details')")
    page.wait_for_timeout(800)
    page.click("#fltBtn")
    page.fill("#fq", "ZZZZ")
    page.wait_for_timeout(500)
    got = page.evaluate("""()=>{const tr=document.querySelector('#ftable tr.erow');
      if(!tr)return {found:false};
      const td=tr.querySelector('td'),r=tr.getBoundingClientRect(),
            t=td.getBoundingClientRect();
      return {found:true,h:Math.round(r.height),td:Math.round(t.width),
              row:Math.round(r.width),disp:getComputedStyle(td).display,
              of:td.scrollWidth>td.clientWidth+1};}""")
    assert got["found"], got
    assert got["disp"] == "block", got
    assert got["h"] > 40, got
    # 行身有 12px 左右内边距：单元格铺满内容盒（row-24）即为对称
    assert abs(got["td"] - (got["row"] - 24)) < 6, got
    assert not got["of"], got


def test_config_footer_static_and_symmetric_at_390(page):
    page.set_viewport_size({"width": 390, "height": 844})
    _boot(page)
    page.evaluate("switchView('cfg');showCfgPanel('watch')")
    page.wait_for_timeout(1200)
    page.evaluate("document.querySelector('[data-cwact=add]')?.click()")
    page.wait_for_timeout(700)
    got = page.evaluate("""()=>{const f=document.querySelector('.cwf-foot'),
        s=document.querySelector('.cwf-switches');
      if(!f||!s)return {found:false};
      const fr=f.getBoundingClientRect(),sr=s.getBoundingClientRect();
      const bs=[...f.querySelectorAll('.btn2')].map(b=>Math.round(b.getBoundingClientRect().width));
      return {found:true,pos:getComputedStyle(f).position,overlap:fr.top<sr.bottom-1,
              bs};}""")
    assert got["found"], got
    assert got["pos"] == "static", got
    assert not got["overlap"], got
    assert got["bs"][0] >= got["bs"][1] * 1.8, got
    assert got["bs"][1] == got["bs"][2], got


def test_health_tab_reveals_newest_round(page):
    page.set_viewport_size({"width": 390, "height": 844})
    _boot(page)
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_timeout(900)
    got = page.evaluate("""()=>[...document.querySelectorAll('#hbody .hcells')]
      .map(x=>({max:Math.round(x.scrollWidth-x.clientWidth),
                sl:Math.round(x.scrollLeft)}))""")
    assert got, "health cells missing"
    for x in got:
        assert x["sl"] >= x["max"] - 2, x


def test_palette_single_source_and_control_baseline():
    assert "qunar:['去哪儿','var(--c-qunar)']" in SRC
    assert "--c-qunar:#0f9aa9" in SRC
    assert "--c-ctrip:#2f6fe4" in SRC
    assert 'style="--pc:var(--c-qunar)"' in SRC
    assert "#opscard .opsbtns>button{height:32px;padding:0 13px" in SRC
    assert "#searchview .srx-probeform>label input," in SRC


def test_config_mobile_rules_are_scoped():
    """防 v1.5.274 回归：页脚三等分必须留在 ≤700 媒体块内，
    块外泄漏会把桌面保存条也撑成全宽。"""
    i = SRC.index("@media(max-width:700px){.cwf-targetrow")
    j = SRC.index("@media(max-width:540px){.cwf-cands", i)
    seg = SRC[i:j]
    assert ".cwf-foot .btn2{min-width:0;height:38px" in seg
    assert ".cwf-chip{min-height:36px}" in seg
    assert SRC.count("@media(max-width:700px){.cwf-targetrow") == 1


def test_city_picker_offers_full_list():
    assert "data-cwshowall" in SRC
    assert "浏览全部 '+list.length+' 个城市" in SRC
    assert "const RR={'国内':0" in SRC
    assert "delete inp.dataset.cwall" in SRC


def test_data_honesty_pins():
    # 移动卡补时效与衔接；CSV 补仅观察；日历不落 near/brk；
    # 关注卡 DB 端点过 6h 时效门；镜像 +1 不再双加号
    assert 'class="mdat stale"' in SRC
    assert "f.layoverT?' · 衔接'" in SRC
    assert "f.cal?'日历价不参与'" in SRC
    assert "not qual and not is_cal and not f.get(\"_stale_h\")" in SRC
    assert "if(h>6)q.stale=Math.max(1,Math.round(h))" in SRC
    assert "['到达',(f.arrTime||'—')+he(f.cross?String(f.cross)" in SRC
    assert "['到达',(f.arrTime||'—')+he(f.cross?String(f.cross).replace(/\\s*天/g,'').trim():'')]" in SRC


def test_mobile_details_are_cards_not_horizontal_scroll(page):
    page.set_viewport_size({"width": 390, "height": 844})
    _boot(page)
    page.evaluate("switchView('mon');showMonTab('details')")
    page.wait_for_timeout(800)
    got = page.evaluate("""()=>{const tw=document.querySelector('#tablecard .tw');
      const tr=document.querySelector('#ftable tbody tr[data-k]');
      const vis=[...tr.children].filter(td=>getComputedStyle(td).display!=='none');
      const hint=document.getElementById('twHint');
      return {cw:tw.clientWidth,sw:tw.scrollWidth,
              rowW:Math.round(tr.getBoundingClientRect().width),
              rowH:Math.round(tr.getBoundingClientRect().height),
              vis:vis.length,hint:getComputedStyle(hint).display,
              ow:document.documentElement.scrollWidth-window.innerWidth};}""")
    assert got["sw"] <= got["cw"], got
    assert got["rowW"] <= 340 and got["rowH"] < 280, got
    assert got["vis"] == 4, got
    assert got["hint"] == "none", got
    assert got["ow"] <= 0, got
    assert page.evaluate(
        "getComputedStyle(document.querySelector('#ftable thead')).display") == "none"
