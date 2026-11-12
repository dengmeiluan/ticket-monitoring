# -*- coding: utf-8 -*-
"""r1352：用户点名「最新版仍要升级 + 渠道图标没贯彻」的回归钉。

覆盖三层：
1. core.update.download() 在 has_update=false 时必须拒绝下载（不再把当前包重下一遍）；
2. core.update._invalidate_cache() 在 apply/rollback 成功后清 6h 缓存（否则状态接口
   会继续回答“有新版本”）；
3. 真实渲染：健康矩阵/诊断卡/三率表/筛选渠道 chips/探针状态 chip 都必须带官方
   渠道图标；筛选弹层 1440 宽 1280（用户明确说 960 仍“太小气”）。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_download_refuses_when_latest(monkeypatch):
    from core import update as U
    monkeypatch.setattr(U, "check", lambda *a, **k: {
        "ok": True, "has_update": False, "latest": "v1.6.0", "local": "1.6.0"})
    r = U.download()
    assert r["ok"] is False and "已是最新" in r["err"], r


def test_apply_and_rollback_invalidate_cache():
    i = WEBUI.find("def _update_start_async(")
    assert i > 0
    # 后端必须在进入下载状态前确认 has_update（最新版不再起任务）
    seg = WEBUI[i:i + 1500]
    assert "has_update" in seg and "已是最新版本" in seg, seg[:600]
    # download/apply/rollback 三处语义在 core 内；扫描源码里的失效调用
    src = io.open(os.path.join(ROOT, "core", "update.py"), encoding="utf-8").read()
    assert "def _invalidate_cache(" in src
    assert src.count("_invalidate_cache()") >= 3  # 定义之外，apply + rollback 各一次


def test_cache_file_really_removed(tmp_path, monkeypatch):
    from core import update as U
    p = tmp_path / "update_check.json"
    p.write_text('{"ok":true,"has_update":true}', encoding="utf-8")
    monkeypatch.setattr(U, "_cache_path", lambda: str(p))
    U._invalidate_cache()
    assert not p.exists()


pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")


def _free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import time
    import urllib.request
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(base + "/api/state", timeout=2); break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill(); pytest.fail("demo 未启动")
    yield base
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
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.goto(srv + "/", wait_until="load")
        page.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
        page.wait_for_timeout(600)
        yield page
        b.close()


def test_filter_is_1280_at_1440(srv, pg):
    pg.evaluate("()=>{switchView('search')}")
    pg.wait_for_timeout(700)
    pg.evaluate("()=>{SRX.ctx=true;srxRenderCtx()}")
    pg.wait_for_function("()=>document.getElementById('srxCtxFly')", timeout=8000)
    pg.wait_for_timeout(500)
    d = pg.evaluate("""()=>{const f=document.getElementById('srxCtxFly'),r=f.getBoundingClientRect();
      const b=document.querySelector('#srxFilterBtn').getBoundingClientRect();
      return {w:Math.round(r.width),l:Math.round(r.left),right:Math.round(r.right),br:Math.round(b.right),vw:innerWidth}}""")
    assert 1240 <= d["w"] <= 1280, d
    assert 12 <= d["l"] <= d["right"] <= d["vw"] - 12, d
    assert abs(d["right"] - d["br"]) <= 1, d


def test_update_popover_is_compact_and_reopen_collapsed(srv, pg):
    pg.evaluate("()=>{switchView('mon');loadUpdate()}")
    pg.wait_for_timeout(700)
    pg.evaluate("""()=>{if(!document.getElementById('verChip')){
      const b=document.createElement('button');b.className='verchip';b.id='verChip';b.textContent='v1.6.0';
      b.style.cssText='position:fixed;left:700px;bottom:10px;z-index:99';b.onclick=updPopToggle;document.body.appendChild(b);}
      updPopToggle(true)}""")
    pg.wait_for_timeout(400)
    d1 = pg.evaluate("""()=>{const p=document.getElementById('updPop'),r=p.getBoundingClientRect();
      return {w:Math.round(r.width),body:getComputedStyle(document.getElementById('updateBody')).display}}""")
    assert d1["w"] <= 430 and d1["body"] == "none", d1
    # 展开后关闭，再打开必须回到收起态（用户报的“点击后弹窗展开遮挡”）
    pg.evaluate("()=>toggleUpdate()"); pg.wait_for_timeout(300)
    pg.evaluate("()=>updPopToggle(false)"); pg.wait_for_timeout(200)
    pg.evaluate("()=>updPopToggle(true)"); pg.wait_for_timeout(300)
    d2 = pg.evaluate("()=>getComputedStyle(document.getElementById('updateBody')).display")
    assert d2 == "none", d2


def test_health_and_filter_channel_icons(srv, pg):
    pg.evaluate("()=>{switchView('mon');showMonTab('health');loadRates()}")
    pg.wait_for_function("()=>document.querySelectorAll('#ratesBody .rt-row').length>0", timeout=30000)
    pg.wait_for_timeout(300)
    d = pg.evaluate("""()=>{
      const bad=[];
      const has=(el)=>!!el.querySelector('img.bic[data-plat],span.bic[data-plat]');
      document.querySelectorAll('#hbody .hrow').forEach((el,i)=>{if(!has(el))bad.push('hrow'+i)});
      document.querySelectorAll('#healthDiag .hdiag-card').forEach((el,i)=>{if(!has(el))bad.push('diag'+i)});
      document.querySelectorAll('#ratesBody .rt-row').forEach((el,i)=>{if(!has(el))bad.push('rate'+i)});
      return {rows:document.querySelectorAll('#ratesBody .rt-row').length,bad};
    }""")
    assert d["rows"] > 0 and not d["bad"], d

    pg.evaluate("()=>{switchView('search')}")
    pg.wait_for_timeout(700)
    pg.evaluate("()=>{SRX.ctx=true;srxRenderCtx()}")
    pg.wait_for_timeout(600)
    q = pg.evaluate("""()=>{
      const chips=[...document.querySelectorAll('#srxPlats button[data-plat]')]
        .filter(el=>el.getBoundingClientRect().width>2
          && String(el.getAttribute('data-plat')||'').trim()!==''
          && !el.textContent.trim().startsWith('全部'));
      const bad=chips.filter(el=>!el.querySelector('img.bic[data-plat],span.bic[data-plat]')).map(el=>el.textContent.trim().slice(0,12));
      return {n:chips.length,bad};
    }""")
    assert q["n"] >= 10 and not q["bad"], q
    # 探针状态 chip（不是当前页面初始 DOM，直接走渲染函数）
    probe = pg.evaluate("""()=>{const d=document.createElement('div');
      d.innerHTML=srxProbeChHTML('app_qunar',{status:'ok',n:3});
      return !!d.querySelector('img.bic[data-plat="app_qunar"]')}""")
    assert probe is True
