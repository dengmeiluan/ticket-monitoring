# -*- coding: utf-8 -*-
"""1.5.273 UI honesty/interaction pins.

Covers the second-wave fixes that neither 1.5.271 nor 1.5.272 shipped:
demo surface must never read LIVE, matrix header/identity column,
calendar rows must not enter same-flight compare, unfollow needs a
confirm layer, and the watch form must not fight the global savebar.
"""
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
    priv_tmp = tempfile.mkdtemp(prefix="v15273_")
    render_tmp = tempfile.mkdtemp(prefix="v15273_render_")
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


def _open_search(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.evaluate("switchView('search')")
    pg.wait_for_selector("#searchview .srx-row", timeout=15000)
    pg.wait_for_function(
        "typeof SRX_WATCH !== 'undefined' && SRX_WATCH.loadedFor",
        timeout=15000)


# ---------- source pins（渲染态另有行为钉兜底） ----------

def test_demo_honesty_labels_present():
    assert "live.innerHTML='<i></i>'+(demo?'DEMO':'LIVE')" in SRC
    assert "演示数据 · 合成" in SRC
    assert "五渠道合成演示行" in SRC
    assert "演示库不含真实报价" in SRC


def test_matrix_sticky_header_and_first_column():
    assert "position:sticky;top:0;z-index:3" in SRC
    assert "th:first-child{text-align:left;min-width:140px;position:sticky;left:0" in SRC
    assert "td:first-child{text-align:left;font-family:inherit;position:sticky;left:0" in SRC
    assert "SRX.view==='matrix'?'none':''" in SRC


def test_calendar_rows_never_enter_compare():
    assert "(f.cal?'':xrowHtml" in SRC


def test_unfollow_requires_confirm():
    assert "取消关注该航班？" in SRC
    assert "function srxWatchToggleDo" in SRC


def test_savebar_yields_to_watch_form():
    assert "body.cwform-open .savebar{display:none}" in SRC
    assert "cwform-open',!!(CFG_WATCH.addOpen||CFG_WATCH.edit)" in SRC


def test_note_shows_full_text_and_two_lines():
    assert "esc(String(w.note).slice(0,16))" not in SRC
    assert "-webkit-line-clamp:2" in SRC


def test_mobile_and_responsive_contracts():
    assert "grid-template-columns:26px minmax(0,1fr) auto 118px" in SRC
    assert "左右滑动查看更多日期" in SRC
    assert "@media(max-width:760px){#searchview .srx-mrail{flex-wrap:wrap" in SRC
    assert ".monwatch:last-child:nth-child(odd)" in SRC
    assert "bottom:calc(18px + env(safe-area-inset-bottom))" in SRC


def test_mobile_inputs_avoid_ios_focus_zoom():
    assert ("#cwForm select,.ws-filterbar input,.ws-filterbar select"
            "{font-size:16px!important}") in SRC


def test_no_threshold_rows_never_claim_miss():
    # v1.5.274: CSV 状态列补「仅观察」语义后 +1；v1.5.278 CSV/证据 JSON
    # 各再补一处状态/onlyObserve = 6 处消费同一判据
    assert SRC.count("!Number(f.th)") == 6
    assert "未设心理线，不作达标判断" in SRC
    assert "仅观察 · 未设心理线" in SRC


def test_compare_groups_are_cabin_and_stale_aware():
    assert "function srxCabinClass(f)" in SRC
    assert "function srxCompareKey(f)" in SRC
    assert "srxCompareKey(x)===k" in SRC
    assert "!srxIsCal(x)&&!srxIsStale(x)&&srxCompareKey(x)===k" in SRC
    assert "if(srxIsCal(f)||srxIsStale(f))continue" in SRC
    assert "'票种:'+s.slice(0,16)" in SRC


def test_legacy_fp_uses_real_flight_code_and_cabin():
    assert "(f.code||f.flightNo||f.name||'')" in SRC
    # v1.5.274: 舱位段改走 srxCabinClass（同班键与看板/走势共用语义类），
    # 原直接拼 cabinT 会在「经济舱」与「经济」间产生假分组
    assert "typeof srxCabinClass==='function'?srxCabinClass(f):(f.cabinT||f.cabinCode||'')" in SRC


def test_cross_day_arrival_date_in_detail():
    assert "function srxArrDate(f)" in SRC
    assert "'（到达 '+srxArrDate(f)+'）'" in SRC


def test_health_login_action_keeps_channel():
    assert 'onclick="srxGoLogin(this.dataset.p)"' in SRC
    assert "String(x.getAttribute('onclick')||'').includes(\"'\"+p+\"'\")" in SRC


def test_overlay_and_input_ime_contracts():
    assert "#toasts{position:fixed;bottom:78px;right:18px;z-index:300" in SRC
    assert SRC.count("ev.isComposing||ev.keyCode===229") == 3
    assert "window.open(url,'_blank','noopener')" not in SRC
    assert "a.target='_blank';a.rel='noopener'" in SRC
    assert 'data-citytoggle="1"' in SRC
    assert "e.target.closest('[data-citytoggle]')" in SRC
    assert "if(!inp||_cpClosing)return;" in SRC
    assert "aria-expanded=\"'+(SRX.exp===srxKey(f))" in SRC
    assert "const _wasExp=!!(_ae&&_ae.closest&&_ae.closest('[data-expbtn]'))" in SRC


def test_health_calendar_only_hidden_from_detail_rate():
    from core.health import parse_health

    def line(ts, msg):
        return "%s [INFO] t: %s" % (ts, msg)

    lines = []
    for i, body in enumerate((
        "[qunar] 2026-10-04 日历最低价 ￥1526",
        "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条）",
        "[qunar] 2026-10-04 达到最大重试圈数 5 仍未拿到价格",
    )):
        lines.append(line("2026-09-09 0%d:00:00" % i,
                          "===== 开始一轮扫描 ====="))
        lines.append(line("2026-09-09 0%d:00:30" % i, body))
        lines.append(line("2026-09-09 0%d:01:00" % i,
                          "===== 本轮扫描结束 ====="))
    st = parse_health("\n".join(lines), now="2026-09-09 04:00:00")["stats"]["qunar"]
    assert st["cal_only"] == 1
    assert st["detail_ok"] == 1
    assert abs(st["rate"] - 2 / 3) < 1e-6
    # v1.5.275：日历-only 轮没有机会产出航班明细，不进明细分母
    assert abs(st["detail_rate"] - 1 / 2) < 1e-6
    assert ".hc.cal{background:var(--warn);opacity:.55}" in SRC


# ---------- rendered behavior ----------

def test_demo_hero_reads_demo_not_live(page):
    _open_search(page)
    got = page.evaluate("""(() => ({
      live: document.getElementById('srxLiveTag').textContent.trim(),
      mode: document.getElementById('srxModeLabel').textContent.trim(),
      sub: document.getElementById('srxHeroSub').textContent.trim(),
      demoClass: document.getElementById('srxLiveTag').classList.contains('demo')
    }))()""")
    assert got["live"] == "DEMO", got
    assert got["mode"] == "演示数据 · 合成", got
    assert "演示库不含真实报价" in got["sub"], got
    assert got["demoClass"] is True, got


def test_matrix_hides_list_header_and_keeps_identity_column(page):
    _open_search(page)
    page.click("#srxViewBtn")
    page.wait_for_selector("#searchview .srx-mx", timeout=10000)
    got = page.evaluate("""(() => {
      const thd = document.querySelector('#searchview .srx-thead');
      const th = document.querySelector('#searchview .srx-mx th');
      const td = document.querySelector('#searchview .srx-mx td');
      const cs = getComputedStyle(th), cd = getComputedStyle(td);
      return {thd: thd && getComputedStyle(thd).display,
              thPos: cs.position, thTop: cs.top, thZ: cs.zIndex,
              tdPos: cd.position, tdLeft: cd.left};
    })()""")
    assert got["thd"] == "none", got
    assert got["thPos"] == "sticky" and got["thTop"] == "0px", got
    assert got["tdPos"] == "sticky" and got["tdLeft"] == "0px", got


def test_unfollow_opens_confirm_and_cancel_keeps_watch(page):
    _open_search(page)
    # 演示库预置关注；先切到该关注所在航线/日期，走真实行内星标入口
    page.evaluate("""(() => {
      const w = (SRX_WATCH.list || [])[0];
      SRX.pair = (w.from || '') + '|' + (w.to || '');
      SRX.date = w.date || '';
      SRX._init = false; srxSave(); renderSearch();
    })()""")
    page.wait_for_function(
        "!!document.querySelector(\"#searchview [data-watchbtn][aria-pressed='true']\")",
        timeout=10000)
    btn = page.locator("#searchview [data-watchbtn][aria-pressed='true']").first
    before = page.evaluate("(SRX_WATCH.list||[]).length")
    btn.click()
    page.wait_for_selector("#confirmMask.on", timeout=5000)
    assert "取消关注该航班？" in page.evaluate(
        "document.getElementById('cmTitle').textContent")
    page.click("#cmCancel")
    page.wait_for_function(
        "!document.getElementById('confirmMask').classList.contains('on')")
    assert page.evaluate("(SRX_WATCH.list||[]).length") == before
    assert page.get_attribute(
        "#searchview [data-watchbtn][aria-pressed='true']", "aria-pressed") == "true"


def test_watch_form_hides_savebar_and_cancel_restores(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("switchView('cfg');showCfgPanel('users',true);"
                  "if(OPEN_USER<0)document.querySelector('.uhead2').click()")
    page.wait_for_selector("#uwatch-0 [data-cwact='add']", timeout=10000)
    page.click("#uwatch-0 [data-cwact='add']")
    page.wait_for_selector("#cwForm", state="visible", timeout=5000)
    assert page.evaluate(
        "document.body.classList.contains('cwform-open')") is True
    assert page.evaluate(
        "getComputedStyle(document.querySelector('.savebar')).display") == "none"
    page.click("#cwCancel")
    page.wait_for_function(
        "!document.body.classList.contains('cwform-open')", timeout=5000)
    assert page.evaluate(
        "getComputedStyle(document.querySelector('.savebar')).display") != "none"


def test_mobile_row_action_column_is_action_sized(page):
    page.set_viewport_size({"width": 390, "height": 844})
    _open_search(page)
    got = page.evaluate("""(() => {
      const r = document.querySelector('#searchview .srx-row');
      const cs = getComputedStyle(r);
      const note = document.getElementById('srxBandNote');
      return {cols: cs.gridTemplateColumns,
              overflow: document.documentElement.scrollWidth - window.innerWidth,
              band: getComputedStyle(note, '::after').content};
    })()""")
    assert got["cols"].endswith("118px"), got
    assert got["overflow"] <= 0, got
    assert "左右滑动查看更多日期" in got["band"], got
