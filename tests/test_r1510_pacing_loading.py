# -*- coding: utf-8 -*-
"""r1510：配置 › 策略控制首开的等待/失败态（真实渲染 + 负控）。

背景：`/api/strategy` 真实环境要跑十五轴矩阵（实测 ~6.2s），旧占位只有
一行「加载中…」：不知道在等什么、没有进展证据，失败也没动作。本门禁：
1. 请求未返回时必须出现等待卡：在办事项 + 秒级计时 + 骨架行，且 aria-busy。
2. 计时真的在走（≥1.0s），不是静止文案。
3. 失败时同一位置给原因 + 「重新读取」；按钮真能恢复出策略行。
4. 负控：把等待卡换回旧的裸「加载中…」，等待卡判据必须红。
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


def free_port():
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
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
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
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_pacing(browser, width=1440):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
    # 演示 /api/strategy 本机串行 ~6s；8 worker + 2 片 UI 并发时 gate20 gw5
    # 实测 25s 仍未出首行（同用例串行 3/3 通过）。等待预算放宽到 45s，
    # 判据不变：仍必须真的出现策略行，超时依旧红。
    page.wait_for_function("typeof switchView==='function'", timeout=45000)
    page.evaluate("switchView('cfg');showCfgPanel('pacing')")
    page.wait_for_selector("#cfgpacingRows", state="attached", timeout=45000)
    page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
    page.wait_for_timeout(300)
    return ctx, page


LOADING_PROBE = r"""
() => {
  const b=document.getElementById('cfgpacingRows');
  const card=b.querySelector('.sload');
  const r=card?card.getBoundingClientRect():null;
  const br=b.getBoundingClientRect();
  return {
    loading:b.dataset.loading||'', busy:b.getAttribute('aria-busy')||'',
    hasCard:!!card, text:card?card.innerText.replace(/\s+/g,' '):'',
    elapsed:(b.querySelector('.selapsed')||{}).textContent||'',
    skel:b.querySelectorAll('.slskel i').length,
    cardW:r?+r.width.toFixed(1):0, boxW:+br.width.toFixed(1),
    rows:b.querySelectorAll('.srow').length,
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""

ERROR_PROBE = r"""
() => {
  const b=document.getElementById('cfgpacingRows');
  const e=b.querySelector('.slerr');
  return {hasErr:!!e, text:e?e.innerText.replace(/\s+/g,' '):'',
          retry:e?e.querySelector('button').textContent.trim():'',
          rows:b.querySelectorAll('.srow').length,
          docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


def _install_fetch(page, mode):
    """把 /api/strategy 的 fetch 换成可控桩；返回恢复脚本。"""
    page.evaluate(
        """(mode)=>{
          if(!window.__ofetch)window.__ofetch=window.fetch;
          window.__stratMode=mode;
          window.fetch=function(u,o){
            if(String(u).indexOf('/api/strategy')>=0){
              if(window.__stratMode==='stall')return new Promise(function(){});
              if(window.__stratMode==='fail')return Promise.resolve({ok:true,json:function(){
                return Promise.resolve({ok:false,err:'矩阵计算超时'});}});
            }
            return window.__ofetch.apply(window,arguments);
          };
          const b=document.getElementById('cfgpacingRows');
          b.dataset.painted='0';STRATPAY=null;loadStrategyPanel(true);
        }""", mode)


def _restore_fetch(page):
    page.evaluate("()=>{if(window.__ofetch)window.fetch=window.__ofetch;}")


def test_loading_card_and_live_timer(srv, browser):
    ctx, page = open_pacing(browser, 1440)
    try:
        _install_fetch(page, "stall")
        page.wait_for_selector("#cfgpacingRows .sload", timeout=10000)
        d = page.evaluate(LOADING_PROBE)
        assert d["loading"] == "1" and d["busy"] == "true", d
        assert "正在读取策略目录" in d["text"], d["text"]
        assert "逐项参数" in d["text"], "loading copy must point at the usable fallback"
        assert d["skel"] == 3, d["skel"]
        assert d["rows"] == 0, "rows rendered while strategy payload pending"
        assert abs(d["cardW"] - d["boxW"]) <= 2, d
        assert d["docDx"] <= 0, d
        # 计时真在走：同一次 page.evaluate 内隔 1.2s 读两次
        pair = page.evaluate("""async()=>{
          const g=()=>document.querySelector('#cfgpacingRows .selapsed').textContent;
          const a=g(); await new Promise(r=>setTimeout(r,1200)); return [a,g()];
        }""")
        assert pair[0].endswith("s") and pair[1].endswith("s"), pair
        assert float(pair[1].rstrip("s")) >= float(pair[0].rstrip("s")) + 1.0, pair
        # 负控：换回旧占位，等待卡判据必须红
        page.evaluate("()=>{document.getElementById('cfgpacingRows').innerHTML='<span class=\"muted\">加载中…</span>'}")
        d3 = page.evaluate(LOADING_PROBE)
        assert not d3["hasCard"] and d3["elapsed"] == "", "negative control did not break the loading predicate"
        _restore_fetch(page)
        page.evaluate("()=>loadStrategyPanel(true)")
        page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
        d4 = page.evaluate(LOADING_PROBE)
        assert d4["loading"] == "0" and d4["busy"] == "false", d4
        assert d4["rows"] >= 25, d4["rows"]
        assert not d4["hasCard"], "loading card stayed after rows arrived"
    finally:
        ctx.close()


def test_failed_strategy_shows_reason_and_retry(srv, browser):
    ctx, page = open_pacing(browser, 390)
    try:
        _install_fetch(page, "fail")
        page.wait_for_selector("#cfgpacingRows .slerr", timeout=10000)
        d = page.evaluate(ERROR_PROBE)
        assert d["hasErr"], "no error card"
        assert "策略目录读取失败" in d["text"], d["text"]
        assert "矩阵计算超时" in d["text"], "reason not surfaced: %s" % d["text"]
        assert d["retry"] == "重新读取", d["retry"]
        assert d["rows"] == 0
        assert d["docDx"] <= 0, d
        _restore_fetch(page)
        page.evaluate("()=>document.querySelector('#cfgpacingRows .slerr button').click()")
        page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
        d2 = page.evaluate(ERROR_PROBE)
        assert not d2["hasErr"], "error card stayed after successful retry"
        assert d2["rows"] >= 25, d2["rows"]
    finally:
        ctx.close()
