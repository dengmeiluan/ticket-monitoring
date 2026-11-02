# -*- coding: utf-8 -*-
"""r293 WebUI 审计 P2-1（TDD 先行，审计报告 _scratch/worker_r293_webui.md）：

健康格纵向热区互叠——.hc::after 纵向 -11px（名义 37px）大于 .hrow
行距（margin 7px 折叠后 pitch ~26px），相邻行热区重叠、后行绘制序恒
胜：中行格下缘 +9px 起命中**下一行同列格**（跨渠道错轮——用户点去
哪儿行看到飞猪行该轮日志），有效纵向热区 26-27px < 36 地板。r285 W1
只解了横向串格与容器裁剪，行间纵向重叠面未覆盖。

修法：#hbody .hrow 行距拉到 ≥37px 热区高（margin 22px 折叠后
pitch = 行高 19 + 22 = 41px，行=渠道仅 5 行，总代价 ~75px；全指针
生效——桌面同带同样存在错轮命中面，且 65-75px 在健康 tab 无布局压
力）。作用域限 #hbody：#pushhl .hrow 是文本行（无格子）不随迁
（uitest 钉 #pushhl .hrow==2 不受扰）。

钉面（行为级，源码钉锁不住层叠胜负——LESSONS 二十一§1）：
- 机理钉：中行与首行 pitch ≥ 37（热区高=互叠消除的结构前提）；
- 行为钉：coarse 仿真+390 视口下，中行格下缘 +10px（互叠带内、
  自区 11px 内）elementFromPoint 命中**本格**（红态=下一行格胜出）。
  弹层「点得开」面由既有 uitest 首行下缘命中钉承担，此处不重复。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r293_webui.py -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


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


def test_hc_row_pitch_no_cross_row_hit(srv):
    """行为钉（P2-1）：coarse 仿真+390 视口健康 tab——中行格下缘
    +10px elementFromPoint 命中本格（红态=下一行格绘制序胜出=跨渠道
    错轮）；行距 ≥37px 热区高（机理前提）。健康格在健康 tab 容器
    （display 切换架构下非活动量纲全零，LESSONS 十八§8——先真实切换
    再取样；触屏仿真走 CDP setTouchEmulationEnabled，二十三§4）。"""
    pw, page = srv
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 5})
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("switchView('mon')")
        page.evaluate("showMonTab('health', true)")
        page.wait_for_timeout(500)
        st = page.evaluate(
            """()=>{
            const rows=document.querySelectorAll('#hbody .hrow');
            if(rows.length<2)return {err:'rows<2'};
            const a=rows[0].getBoundingClientRect(),
                  b=rows[1].getBoundingClientRect();
            const cells=rows[1].querySelectorAll('.hc');
            if(!cells.length)return {err:'row2 no cells'};
            const c=cells[Math.floor(cells.length/2)];
            c.scrollIntoView({block:'center'});
            return new Promise(res=>setTimeout(()=>{
              const r=c.getBoundingClientRect();
              const el=document.elementFromPoint(
                  r.x+r.width/2, r.bottom+10);
              res({pitch:b.top-a.top,
                   own:!!el&&(el===c||c.contains(el)),
                   tag:el?el.tagName+'.'+el.className:''});
            },300));}""")
        assert "err" not in st, "健康格取样失败：%s" % st
        assert st["pitch"] >= 37, \
            "行距 %.0fpx < 37px 热区高（互叠前提仍在）" % st["pitch"]
        assert st["own"], \
            "中行格下缘 +10px 命中 %s（下一行绘制序胜出=跨渠道错轮）" \
            % st.get("tag")
        match_media = page.evaluate(
            "matchMedia('(pointer:coarse)').matches")
        assert match_media, "触屏仿真未生效（CDP 形态核对）"
    finally:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
