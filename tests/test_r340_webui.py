# -*- coding: utf-8 -*-
"""r340 WebUI 审计落地（_scratch/r340_webui_audit.md P3-1）：

390 带配置页日期工具组（.dwrap .dline）flex-wrap 回绕后，
[范围起 date 输入] →(.sunit) [范围止 date 输入] 三件在控制列内
各自成行——箭头独占一行夹在两个日期输入之间（出发/返程两行同构）。
根因：三件之间无 nowrap 绑组，回绕粒度停在"件"不在"组"。
修法（两段式）：三件包进 .dspan 绑组；宽带（>540，控制列充裕）
横排同线 nowrap 同进退；窄带（≤540，控制列实宽 ~148px，横排绑组
min-content ~243px 几何不可达——实测整列被顶到 270px 全面越界、
r339 D3 钉连红后改判）纵向栈组 [起]↓[止]（箭头旋转 90° 居中），
组 min-content 回落单输入宽，D3 收缩空间恢复。
不复用 .wingrp（其 ≤760 媒体块放开 wrap，webui.py :874 判例在案）。

行为钉采样环境：demo 实例（POST 只读拦截）、Chromium headless、
390×844 与 1440×900 视口显式声明（r300 判例：语境 A 假绿）、展开态
量纲（display:none 容器量纲全零，LESSONS 十九§8）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r340_webui.py -q
"""
import os
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
def page390(srv):
    """390×844 移动档 context + 零 JS 错收集。"""
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


@pytest.fixture()
def page(srv):
    """1440×900 桌面档 context + 零 JS 错收集。"""
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


def _open_dtools(pg, fid):
    """r345：区间面板是模式条默认页；若会话记忆停在指定日则切回区间。
    保留旧名供调用点最小改动。"""
    pg.evaluate("""(fid)=>{
      const inp=document.getElementById(fid);
      const row=inp&&inp.closest('.srow');
      const tab=row&&row.querySelector('.dctab[data-dm="range"]');
      if(tab&&!tab.classList.contains('on'))tab.click();
    }""", fid)
    pg.wait_for_timeout(150)


def _open_route_card(pg):
    """进配置 users 面板→展开 0:0 航线卡（真实点击路径）。"""
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.locator("#navCfg").click()
    pg.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    pg.locator('.cnav[data-p="users"]').click()
    pg.wait_for_timeout(250)
    pg.evaluate("""()=>{const h=document.querySelector(
        '.rline[data-rk="0:0"] .rhead');
      if(h&&h.getAttribute('aria-expanded')==='false')h.click();}""")
    pg.wait_for_timeout(400)
    _open_dtools(pg, "dfrom-0-0")


def _open_rt(pg):
    """0:0 开往返（返程日期行的渲染前置）。幂等：已开不重复点击
    （非幂等点击在 module 级夹具下会二犯翻转，r339 同款修法）。"""
    pg.evaluate("""()=>{const chip=[...document.querySelectorAll(
        '.rline[data-rk="0:0"] .schip')]
        .find(c=>c.textContent.indexOf('往返票')>=0);
      if(chip&&!chip.classList.contains('on'))chip.click();}""")
    pg.wait_for_timeout(400)
    _open_dtools(pg, "rfrom-0-0")


# ---- P3-1：日期区间三件同组回绕（出发/返程两行） ----
# 390 带控制列实宽 ~148px，横排三件绑组 min-content ~243px 几何不可达
# （实测证伪审计横排修法：整列被 min-content 顶到 270px 全面越界，
# r339 D3 钉连红）——窄带唯一可达形态是纵向栈组 [起]↓[止]；
# 宽带（≥540 控制列 ≥319px）保持横排同线。

def _trio_state(pg, fid, tid):
    return pg.evaluate("""([fid,tid])=>{
      const a=document.getElementById(fid), b=document.getElementById(tid);
      if(!a||!b)return {missing:true};
      const grp=a.closest('.dpanel-row');
      const arr=grp?grp.querySelector('.darr'):null;
      if(!grp||!arr)return {missing:'dpanel-row/darr'};
      const cs=getComputedStyle(grp);
      const ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect(),
            rr=arr.getBoundingClientRect();
      const cy=r=>r.top+r.height/2;
      const dl=a.closest('.dcompose');
      const dlv=dl?{sw:dl.scrollWidth,cw:dl.clientWidth}:null;
      return {display:cs.display,
              gridCols:cs.gridTemplateColumns,
              sameLine: Math.abs(cy(rr)-cy(ra))<4 && Math.abs(cy(rb)-cy(rr))<4,
              gapL:+(rr.left-ra.right).toFixed(1),
              gapR:+(rb.left-rr.right).toFixed(1),
              wA:+ra.width.toFixed(0), wB:+rb.width.toFixed(0),
              wGrp:+grp.getBoundingClientRect().width.toFixed(0),
              grp:!!grp, dl:dlv};
    }""", [fid, tid])


def test_departure_range_trio_wraps_as_group_390(page390):
    _open_route_card(page390)
    out = _trio_state(page390, "dfrom-0-0", "dto-0-0")
    assert not out.get("missing"), out
    assert out["grp"], "区间三件未绑组（.dpanel-row 缺席）"
    assert out["display"] == "grid", f"窄带三件应同栅格：{out}"
    assert out["sameLine"], f"390 起→箭头→止应同线对称：{out}"
    assert out["wA"] > 80 and abs(out["wA"] - out["wB"]) <= 2, \
        f"390 两输入应等宽可读：{out}"
    assert out["dl"] and out["dl"]["sw"] <= out["dl"]["cw"] + 1, \
        f"日期编排横向溢出：{out['dl']}"
    assert not page390._errs, page390._errs


def test_return_range_trio_wraps_as_group_390(page390):
    _open_route_card(page390)
    _open_rt(page390)
    out = _trio_state(page390, "rfrom-0-0", "rto-0-0")
    assert not out.get("missing"), out
    assert out["grp"], "返程区间三件未绑组（.dpanel-row 缺席）"
    assert out["display"] == "grid", f"返程窄带三件应同栅格：{out}"
    assert out["sameLine"], f"390 返程 起→箭头→止应同线对称：{out}"
    assert out["wA"] > 80 and abs(out["wA"] - out["wB"]) <= 2, \
        f"390 返程两输入应等宽可读：{out}"
    assert out["dl"] and out["dl"]["sw"] <= out["dl"]["cw"] + 1, \
        f"返程日期编排横向溢出：{out['dl']}"
    assert not page390._errs, page390._errs


def test_range_trio_same_line_wide(page):
    """宽带（1440）：起→箭头→止同线对称，输入等宽。"""
    _open_route_card(page)
    out = _trio_state(page, "dfrom-0-0", "dto-0-0")
    assert not out.get("missing"), out
    assert out["grp"], "区间三件未绑组（.dpanel-row 缺席）"
    assert out["display"] == "grid", f"宽带三件应同栅格：{out}"
    assert out["sameLine"], f"宽带箭头与两侧输入不同线：{out}"
    assert abs(out["wA"] - out["wB"]) <= 2, f"宽带输入不等宽：{out}"
    assert not page._errs, page._errs
