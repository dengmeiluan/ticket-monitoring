# -*- coding: utf-8 -*-
r"""r638：节流参数必须独立成「渠道节流」分区，不再塞在「全局参数」里。

用户原话：「节流板块放在全局参数中的设定和设计也非常不合理，感觉跟整体
设计格格不入，放在渠道登录中或者渠道健康中不是更加合理？」

实测（拆分前）：22 个节流控件（静默窗、两级 TTL、限速、熔断、成功率保护、
预热、每渠道节奏）全部渲染在 `#cfgglobals` 里，和端口/路径/UA 混在一起。
用户找不到，也分不清「哪一项该为被限流负责」。

拆分后：独立分区「渠道节流」（`panel-pacing` / `#cfgpacing`），控件本体与
保存链路不变（同一批 GLB 键），并可从「监控 · 渠道健康」一键直达。

判据是**真渲染**：静态查字符串看不出控件落在哪个面板里。
负控：把 `gp` 改回拼进 `gh`，新分区分不到任何控件 → 本测试红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 拆到新分区的控件 id（一个都不能留在全局参数里）
PACING_IDS = (
    "glbQs", "glbQe", "glbFast", "glbSlow", "glbNear", "glbStg", "glbGap",
    "glbRpm", "glbBrk", "glbHpen", "glbHok", "glbHslow", "glbHsf",
    "glbHslf", "glbHms", "glbBbs", "glbBcs", "glbWarm", "glbWarmP",
    "glbLcd", "glbNearD",
)


_CACHE = {}


def _render():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1000})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(base)
                pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                     timeout=30000)
                pg.evaluate("()=>{switchView('cfg')}")
                pg.wait_for_timeout(1200)
                got = pg.evaluate("""()=>{
                  const navs=[...document.querySelectorAll('#cfgnav .cnav')]
                    .map(c=>c.dataset.p);
                  const ids=k=>[...new Set([...document.querySelectorAll(
                      '#panel-'+k+' input,#panel-'+k+' select')]
                    .map(e=>e.id).filter(Boolean))];
                  const pac=ids('pacing'), glb=ids('globals');
                  const c=document.querySelector(
                    '#cfgnav .cnav[data-p="pacing"]');if(c)c.click();
                  return {navs:navs, pac:pac, glb:glb,
                    pacDisp:getComputedStyle(
                      document.getElementById('panel-pacing')).display,
                    navN:(document.getElementById('navN-pacing')||{}).textContent,
                    grid:(()=>{const g=document.querySelector(
                       '#cfgpacing .glgrid');
                      return g?getComputedStyle(g).gridTemplateColumns:'';})()};
                }""")
                # 健康卡入口直达
                pg.evaluate("()=>{try{cfgGoThrottle()}catch(e){}}")
                pg.wait_for_timeout(600)
                after = pg.evaluate("""()=>({
                  panel:getComputedStyle(
                    document.getElementById('panel-pacing')).display,
                  on:(document.querySelector('#cfgnav .cnav.on')||{})
                      .dataset.p||''})""")
                b.close()
            finally:
                try:
                    b.close()
                except Exception:
                    pass
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    _CACHE["got"], _CACHE["after"], _CACHE["errs"] = got, after, errs
    return got, after, errs


def _once():
    if "got" not in _CACHE:
        _render()
    return _CACHE["got"], _CACHE["after"], _CACHE["errs"]


def test_pacing_lives_in_its_own_section_not_globals():
    got, after, errs = _once()
    assert not errs, "配置页抛错：%s" % errs[:3]
    assert "pacing" in got["navs"], (
        "导航里没有「渠道节流」分区：%s" % got["navs"])
    assert got["pacDisp"] == "block", (
        "渠道节流分区点开不可见：%s" % got["pacDisp"])
    # 23 个节流控件都在新分区
    missing = [i for i in PACING_IDS if i not in got["pac"]]
    assert not missing, "这些节流控件没进「渠道节流」分区：%s" % missing
    # 一个都不能留在「全局参数」
    leak = [i for i in got["glb"] if i in PACING_IDS]
    assert not leak, "这些节流控件仍留在「全局参数」：%s" % leak


def test_pacing_section_is_reachable_from_the_health_card():
    """健康卡「配置 · 渠道节流」按钮必须真的落到新分区。"""
    got, after, errs = _once()
    assert after["on"] == "pacing", (
        "点健康卡入口后没有切到「渠道节流」：on=%r" % after["on"])
    assert after["panel"] == "block", "新分区没有显示"


def test_pacing_grid_keeps_three_columns_at_1440():
    """三列网格样式必须覆盖到新容器（否则控件会挤成一列）。"""
    got, after, errs = _once()
    cols = got["grid"].split()
    assert len(cols) == 3, (
        "#cfgpacing 的 .glgrid 不是三列（CSS 选择器没覆盖新容器）：%r"
        % got["grid"])


def test_nav_count_is_derived_not_hardcoded():
    """导航计数必须按真实控件派生：写死数字在增删节流键后会静默说谎。"""
    got, after, errs = _once()
    n = len([i for i in got["pac"] if i.startswith("glb")])
    assert got["navN"].strip().endswith("项"), (
        "导航计数不是「N 项」：%r" % got["navN"])
    assert got["navN"].strip().startswith(str(n)), (
        "导航写着 %r，实际控件 %d 个——计数没派生" % (got["navN"], n))


def test_four_nav_items_stay_single_line_at_every_width():
    """四个分区名在任一宽度下都必须单行——增分区最容易踩的就是折行。

    实测（加「渠道节流」后，390px）：「用户与航线」5 字放不进 85px 的
    均分格，折成 2 行，同排四项高度不齐（50 vs 32）。导航整体也从 86px
    涨到 104px。修法：`.cnav` 加 `white-space:nowrap`。

    负控：去掉 nowrap → 该项 h=50 / lines=2，本测试红。
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    rows = {}
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                for w in (1440, 900, 700, 390):
                    pg = b.new_page(viewport={"width": w, "height": 900})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('cfg')}")
                    pg.wait_for_timeout(800)
                    rows[w] = pg.evaluate("""()=>({
                      items:[...document.querySelectorAll('#cfgnav .cnav')]
                        .map(e=>{const r=e.getBoundingClientRect();
                          let lines=1;const rg=document.createRange();
                          for(const n of e.childNodes){
                            if(n.nodeType!==3||!n.textContent.trim())continue;
                            rg.selectNodeContents(n);
                            lines=rg.getClientRects().length;}
                          return {p:e.dataset.p||'',h:Math.round(r.height),
                                  lines:lines};}),
                      over:document.documentElement.scrollWidth
                           >window.innerWidth+1})""")
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    bad = []
    for w, got in rows.items():
        for it in got["items"]:
            if it["lines"] > 1:
                bad.append((w, it["p"], it["lines"], it["h"]))
        if got["over"]:
            bad.append((w, "doc", "横向溢出", ""))
    assert not bad, (
        "这些宽度下分区名折行/溢出（同一排高度会不齐）：%s；实测 %s"
        % (bad, {w: r["items"] for w, r in rows.items()}))
