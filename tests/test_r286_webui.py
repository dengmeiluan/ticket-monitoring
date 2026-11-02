# -*- coding: utf-8 -*-
"""r286 WebUI 审计落地三案（TDD 先行，审计报告 _scratch/r286_web_report.md）：

P2-1 [1440-1919 带 KPI 空腔] r285 W5 把 wrap 改 92vw 渐进后，.grid/.kpisum
    仍锁 --kpiw=1168 而 statline/pulsewrap 已解锁全宽——右缘错位随带宽
    连续放大（1440:32px → 1919:398px），≥1920 才有 grid 放宽处方。
    修法：≥1920 的 `.grid,.kpisum{max-width:min(1440px,100%)}` 下移到
    ≥1440 块（处方扩带，≥1920 块内原声明转同值 no-op 互指保留）。
    行为钉在病灶带 1700/1900 量 grid 右缘 vs statline 右缘差。
P2-2 [≤760 空态行 nowrap 裁切] .erow td 继承 th,td nowrap——390 视口
    空态提示句 td 宽 525px 被裁在 332px 容器外（词面是 ≤760 专属抽屉
    指引，恰写给被它裁伤的移动用户）。修法：基础规则补 white-space
    :normal（与 L242 xrow 同族同位）。
P2-3 [iPad 竖屏触控真空带] r285 W1 健康格 9px 只落 coarse+≤760，
    768/810/820 iPad 竖屏落在真空带仍 5px 基础宽（W1 立项判据下同族
    缺陷）。修法：W1 块扩带 ≤900（置尾块层叠地位不变，≤760 行为
    零变化）；r285 旧钉 760 字面同轮改写 900（钉面随行为演进改写，
    显式落位强度不降）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r286_webui.py -q
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r285_webui.py） ----------

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
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8796" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    base = "http://127.0.0.1:%d" % _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(base.rsplit(":", 1)[1])],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            op.open(base + "/api/state", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    assert proc.poll() is None, "demo 实例启动失败"
    from playwright.sync_api import sync_playwright as _sp
    with _sp() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/", wait_until="networkidle")
        try:
            yield (p, page)
        finally:
            browser.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


# ---------- P2-1: 1440 带 KPI 空腔（源码钉 + 病灶带行为钉） ----------

def test_kpi_widen_1440_source_pin():
    """源码钉：1280 解锁块承载 grid/kpisum 放宽处方（与 wrap 托底
    释放同拍，晚于 660 块 --kpiw 限宽声明，同特异性后者胜）；≥1920
    块互指注记在场（同值 no-op 保留先例，与 statline 形态同构）。"""
    src = _page_src()
    m = re.search(
        r"@media\(min-width:1280px\)\{\.statline,#pulseLegend,\.pulsewrap"
        r"\{max-width:min\(1440px,100%\)\}\s*\.grid,\.kpisum"
        r"\{max-width:min\(1440px,100%\)\}\}",
        src)
    assert m, "1280 解锁块内 grid/kpisum 放宽处方缺席（r302 W1 四族同上限）"
    i_660 = src.find(".grid{grid-template-columns:repeat(2,minmax(0,1fr))")
    assert 0 < i_660 < m.start(), \
        "放宽处方必须晚于 660 块 --kpiw 限宽声明（层叠序）"
    # 禁复活：1440 独占带形态=解锁与 wrap 渐进脱拍（带界空腔回潮）
    assert "min-width:1440px" not in src, \
        "1440 独占带复活（解锁断点须与 wrap 渐进带 1280 同拍）"
    # ≥1920 块互指注记（同值 no-op 保留，防单侧删改回插再限宽）
    assert re.search(
        r"min-width:1920px[\s\S]{0,900}?\.grid,\.kpisum"
        r"\{max-width:min\(1440px,100%\)\}", src), \
        "≥1920 块原声明退役（应转互指保留形态）"


def test_kpi_cavity_benchmark_band(srv):
    """行为钉（病灶带复测原症状指标，LESSONS 十六§10）：1700/1900
    视口下 .grid 右缘 vs .statline 右缘差 <200px（红态 256/398——
    KPI 区左贴 1168、脉冲区全宽，同屏双轴）。修复后 1700≈22px、
    1900≈164px（grid 1440 封顶 vs 全宽内容区）。几何取样走概览
    默认视图（statline 与 grid 同屏，LESSONS 十九§8）。"""
    pw, page = srv
    page.evaluate("switchView('mon')")
    page.evaluate("showMonTab('overview', true)")
    page.wait_for_timeout(400)
    for w in (1700, 1900):
        page.set_viewport_size({"width": w, "height": 900})
        page.wait_for_timeout(300)
        d = page.evaluate(
            """()=>{const g=document.querySelector('.grid'),
                     s=document.querySelector('.statline');
                if(!g||!s)return null;
                const gr=g.getBoundingClientRect(),
                      sr=s.getBoundingClientRect();
                return (gr.left+gr.width)-(sr.left+sr.width);}""")
        assert d is not None, "几何取样失败"
        assert abs(d) < 200, \
            "%d 档 grid-statline 右缘差 %.0fpx（KPI 空腔病灶带）" % (w, d)


# ---------- P2-2: 空态行 nowrap 裁切（源码钉 + 390 行为钉） ----------

def test_erow_nowrap_source_pin():
    """源码钉：.erow td 基础规则带 white-space:normal（与 .xrow td
    同族同位——th,td nowrap 基础规则特异度 (0,0,2) 低于 (0,1,1)，
    基础规则处补词即胜，无需置尾）。"""
    src = _page_src()
    m = re.search(r"\.erow td\{[^}]*\}", src)
    assert m, ".erow td 基础规则缺席"
    assert "white-space:normal" in m.group(0), \
        ".erow td 未补 white-space:normal（空态句仍被裁）"


def test_erow_empty_state_no_clip(srv):
    """行为钉：390 视口明细 tab 搜索无结果态，.erow td 宽 ≤ 容器宽
    （红态 td 525.1px > .tw 332px 横滚裁切，提示句尾部滚出视口）。"""
    pw, page = srv
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("switchView('mon')")
    page.evaluate("showMonTab('details', true)")
    page.evaluate("togFlt()")   # ≤760 筛选在抽屉里（#fq 隐藏时 fill 超时）
    page.wait_for_timeout(300)
    page.fill("#fq", "zzzz_no_match")
    page.dispatch_event("#fq", "input")
    page.wait_for_timeout(400)
    r = page.evaluate(
        """()=>{const td=document.querySelector('#ftable tr.erow td');
            const tw=document.querySelector('.tw');
            if(!td||!tw)return null;
            return {td:td.getBoundingClientRect().width,
                    tw:tw.clientWidth};}""")
    assert r is not None, "空态行取样失败（搜索无结果未触发 .erow？）"
    assert r["td"] <= r["tw"] + 1, \
        "空态 td %.0fpx 超容器 %.0fpx（提示句尾部裁出视口）" % (
            r["td"], r["tw"])
    page.fill("#fq", "")
    page.dispatch_event("#fq", "input")


# ---------- P2-3: 健康格触屏扩带 ≤900（源码钉 + 768 行为钉） ----------

def test_hc_coarse_band_extended_source_pin():
    """源码钉：W1 块媒体门扩带 ≤900（iPad 竖屏 768/810/820 真空带
    入覆写域）；覆写块位置晚于窄带 5px 基础声明（≤760 带层叠行为
    零变化：同特异性置尾胜）。"""
    src = _page_src()
    # r339d D5 起块内合法增厚（.rthead 36 地板同块）——匹配放宽到
    # 「块头到 .hc 声明」（窗口钉对插入敏感，LESSONS 卅一§3 同律），
    # 语义担保不变：扩带门 + .hc 9px 覆写声明在块内
    m = re.search(
        r"@media\(pointer:coarse\) and \(max-width:900px\)\{"
        r"[^@]*?\.hc\{width:9px;flex:none\}", src)
    assert m, "W1 块未扩带 ≤900（或块内声明形态漂移）"
    i_base = src.find(".hc{width:5px}")
    assert 0 < i_base < m.start(), "覆写块必须晚于窄带 5px 基础声明"


def test_hc_coarse_ipad_band_computed(srv):
    """行为钉：768×1024 coarse 仿真（CDP setTouchEmulationEnabled，
    二十三§4）健康 tab 下 .hc computed 宽 ≥9px（红态=真空带 5px
    基础宽仍胜出，W1 立项判据「点击格看该轮日志触屏不可用」同族）。"""
    pw, page = srv
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 5})
    try:
        page.set_viewport_size({"width": 768, "height": 1024})
        page.evaluate("switchView('mon')")
        page.evaluate("showMonTab('health', true)")
        page.wait_for_timeout(500)
        w = page.evaluate(
            """()=>{const e=document.querySelector('.hc');
                return e?e.getBoundingClientRect().width:null;}""")
        assert w is not None, "健康格取样失败（tab 未激活？）"
        assert w >= 9, \
            "768 coarse 格宽 %s px（真空带 5px 仍胜出=触控热区缺陷同族）" % w
        assert page.evaluate(
            "matchMedia('(pointer:coarse)').matches"), "触屏仿真未生效"
    finally:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
