# -*- coding: utf-8 -*-
"""r1351：用户点名的五处观感/交互缺陷（真实渲染钉）。

1) 版本更新：无更新时「下载并升级」必须禁用并写「已是最新」；
   展开更新面板底边不得穿出视口（旧实现按高度反推 top，展开后底部 −72px）。
2) 检索页进入时组合队列默认收起（只保留「组合 N/4」入口）。
3) 渠道健康底部诊断/错误码/三率是一张连续辅助卡，与主角卡同宽同边。
4) 三率表的渠道名带官方渠道图标。
5) 筛选 popover 1440 宽 960（旧 760），仍贴触发按钮。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r1351_user_report_five.py
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
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2); break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill(); pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def pg():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
        page.wait_for_timeout(600)
        yield page
        b.close()


def test_search_queue_collapsed_by_default(srv, pg):
    pg.evaluate("()=>switchView('search')"); pg.wait_for_timeout(800)
    d = pg.evaluate("()=>({open:!!SRX.batchOpen,"
                    "dock:getComputedStyle(document.getElementById('srxBatchDock')).display})")
    assert d["open"] is False and d["dock"] == "none", d


def test_filter_popover_wider(srv, pg):
    pg.evaluate("()=>switchView('search')"); pg.wait_for_timeout(700)
    pg.evaluate("()=>{SRX.ctx=true;srxRenderCtx()}"); pg.wait_for_timeout(500)
    d = pg.evaluate("""()=>{const f=document.getElementById('srxCtxFly'),
      r=f.getBoundingClientRect();return {w:Math.round(r.width),l:Math.round(r.left),
      right:Math.round(r.right),vw:innerWidth}}""")
    assert d["w"] >= 940, d
    assert 12 <= d["l"] <= d["right"] <= d["vw"] - 12, d


def test_health_auxiliary_one_continuous_card(srv, pg):
    pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
    # /api/health 在 demo 首取实测 1.5–2.1s（并发门禁下更久）。固定 1s 会在
    # 数据未回来、健康卡仍隐藏时量到 x=0/w=0，读成「三张辅卡没对齐主卡」。
    pg.wait_for_function(
        "()=>{const e=document.getElementById('healthcard');if(!e)return false;"
        "const r=e.getBoundingClientRect();"
        "return getComputedStyle(e).display!=='none'&&r.width>200&&r.height>100}",
        timeout=30000)
    d = pg.evaluate("""()=>{const R=id=>{const e=document.getElementById(id);
      const r=e.getBoundingClientRect(),s=getComputedStyle(e);
      return {x:Math.round(r.x),y:+r.y.toFixed(1),b:+r.bottom.toFixed(1),w:Math.round(r.width),bg:s.backgroundColor,
              rt:s.borderTopLeftRadius,rb:s.borderBottomLeftRadius}};
      return {hero:R('healthcard'),diag:R('healthDiag'),err:R('errCodeCard'),rates:R('ratesCard')}}""")
    for k in ("diag", "err", "rates"):
        assert d[k]["bg"] == "rgb(255, 255, 255)", d
        assert d[k]["x"] == d["hero"]["x"], d
        assert d[k]["w"] == d["hero"]["w"], d
    # r1455：主矩阵与诊断/错误码/三率合为同一张长卡——外轮廓只在最上/最下
    # 两端收圆角，中间接缝零缝隙；旧实现四张独立卡各带 14px 圆角，读作
    # 「块块自洽、页不成立」。
    assert d["hero"]["rt"] != "0px" and d["rates"]["rb"] != "0px", d
    for k in ("diag", "err"):
        assert d[k]["rt"] == "0px" and d[k]["rb"] == "0px", d
    assert abs(d["diag"]["y"] - d["hero"]["b"]) <= 0.6, d
    assert abs(d["err"]["y"] - d["diag"]["b"]) <= 0.6, d
    assert abs(d["rates"]["y"] - d["err"]["b"]) <= 0.6, d


def test_rates_table_has_channel_icons(srv, pg):
    pg.evaluate("()=>{switchView('mon');showMonTab('health');loadRates()}")
    pg.wait_for_function("()=>document.querySelectorAll('#ratesBody .rt-row').length>0", timeout=30000)
    pg.wait_for_timeout(300)
    d = pg.evaluate("()=>({rows:document.querySelectorAll('#ratesBody .rt-row').length,"
                    "icon:!!document.querySelector('#ratesBody .rt-name img,#ratesBody .rt-name svg')})")
    assert d["rows"] > 0 and d["icon"], d


def test_update_latest_is_disabled_and_popover_fits(srv, pg):
    pg.evaluate("()=>loadUpdate()"); pg.wait_for_timeout(900)
    d = pg.evaluate("""()=>{const b=[...document.querySelectorAll('#updateBody .up-row button')]
      .find(x=>/下载并升级|已是最新/.test(x.textContent));
      return {txt:b?b.textContent:null,dis:b?b.disabled:null}}""")
    assert d["dis"] is True and "已是最新" in (d["txt"] or ""), d
    # 固定一颗版本钮在视口底，展开面板后必须完整留在视口内
    pg.evaluate("""()=>{const b=document.createElement('button');b.className='verchip';
      b.id='verChip';b.textContent='v1.6.0';b.style.cssText='position:fixed;left:700px;bottom:10px;z-index:99';
      b.onclick=updPopToggle;document.body.appendChild(b);updPopToggle(true)}""")
    pg.wait_for_timeout(500)
    pg.evaluate("()=>toggleUpdate()"); pg.wait_for_timeout(700)
    r = pg.evaluate("""()=>{const p=document.getElementById('updPop'),b=p.getBoundingClientRect();
      return {top:Math.round(b.top),bottom:Math.round(b.bottom),vh:innerHeight,
              over:p.scrollHeight-p.clientHeight}}""")
    assert r["top"] >= 12 and r["bottom"] <= r["vh"] - 12, r
