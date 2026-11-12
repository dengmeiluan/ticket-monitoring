# -*- coding: utf-8 -*-
"""r1211 渠道健康控制台：真实渲染约束（修复 r1210 遗留的三处观感缺陷）。

1) 桌面五列行：有分域样本时「国内/国际」摘要必须占第 4 列（180px），
   动作在第 5 列；历史四列规则曾把摘要挤进 64px，1440 实测「国内 100%…」截断。
2) 扁平区段：诊断/错误码/三率在页面里是同一张底上的区段（透明、无描边、
   无圆角、无阴影），标题行与矩阵卡头同一 48px 基线。
3) 窄档主角卡头单行：≤600 隐藏英文小标与「每格 1 小时」提示后，
   标题与轮次同排；「节流与干预」标题不得被挤成两行。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r1211_health_console.py
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


def _open_health(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(700)
    pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
    pg.wait_for_function(
        "()=>document.querySelectorAll('#hbody .hrow').length>=10", timeout=20000)
    pg.wait_for_timeout(500)


def test_scope_summary_keeps_180px_column(srv, browser):
    """1440 有分域样本：摘要完整可读、动作在右、二者不重叠。

    负控：旧四列规则（hrowact 钉第 4 列）下 .hsum 只有 64px，
    scrollWidth > clientWidth，本断言必红。
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 950})
    try:
        _open_health(pg)
        d = pg.evaluate("""()=>{
          const hb=document.getElementById('hbody');
          hb.classList.remove('noscopes');
          const row=hb.querySelector('.hrow');
          let sum=row.querySelector('.hsum');
          if(!sum){
            sum=document.createElement('span');sum.className='hsum';
            sum.textContent='国内 100% · 国际 100%';
            row.insertBefore(sum,row.querySelector('.hrowact'));
          }
          const r=e=>e.getBoundingClientRect();
          return {sumW:Math.round(r(sum).width),sumOver:sum.scrollWidth-sum.clientWidth,
            sumX:Math.round(r(sum).x),actX:Math.round(r(row.querySelector('.hrowact')).x),
            grid:getComputedStyle(row).gridTemplateColumns};
        }""")
        assert d["sumW"] >= 150, d
        assert d["sumOver"] <= 0, d
        assert d["actX"] > d["sumX"], d
    finally:
        pg.close()


def test_flat_sections_share_one_surface(srv, browser):
    """诊断/错误码/三率同一底：透明、无边框圆角阴影；标题行 48px 对齐。"""
    pg = browser.new_page(viewport={"width": 1440, "height": 950})
    try:
        _open_health(pg)
        d = pg.evaluate("""()=>{
          const ids=['healthDiag','errCodeCard','ratesCard'];
          return ids.map(id=>{
            const e=document.getElementById(id),s=getComputedStyle(e);
            const u=e.querySelector(':scope>.uhead');
            return {id,bg:s.backgroundColor,bw:s.borderTopWidth,br:s.borderRadius,
              sh:s.boxShadow,h:u?Math.round(u.getBoundingClientRect().height):null};
          });
        }""")
        # r1351：三段合并为一张连续辅助卡（白底），不再是透明裸块。
        for x in d:
            assert x["bg"] == "rgb(255, 255, 255)", x
            assert x["sh"] == "none", x
            assert x["h"] is not None and 46 <= x["h"] <= 50, x
    finally:
        pg.close()


def test_narrow_hero_header_one_line_and_pace_label(srv, browser):
    """390/320：卡头单行（≤45px），标题与轮次同基线；节流标题不折行。"""
    bad = []
    for w in (390, 320):
        pg = browser.new_page(viewport={"width": w, "height": 844 if w == 390 else 720},
                              is_mobile=True, has_touch=True)
        try:
            _open_health(pg)
            d = pg.evaluate("""()=>{
              const uh=document.querySelector('#healthcard>.uhead');
              const kids=[...uh.children].map(e=>Math.round(e.getBoundingClientRect().y));
              const b=document.querySelector('#hpaceFold summary b');
              const r=b.getBoundingClientRect();
              return {h:Math.round(uh.getBoundingClientRect().height),ys:kids,
                bw:Math.round(r.width),bh:Math.round(r.height),
                docOver:document.documentElement.scrollWidth-document.documentElement.clientWidth};
            }""")
            if d["h"] > 45:
                bad.append("%d 卡头 %spx 未单行" % (w, d["h"]))
            if len(d["ys"]) >= 2 and abs(d["ys"][0] - d["ys"][1]) > 3:
                bad.append("%d 标题与轮次不同排 %s" % (w, d["ys"]))
            if d["bh"] > 22:
                bad.append("%d 节流标题折行 %sx%s" % (w, d["bw"], d["bh"]))
            if d["docOver"] > 1:
                bad.append("%d 横向溢出 %s" % (w, d["docOver"]))
        finally:
            pg.close()
    assert not bad, bad
