# -*- coding: utf-8 -*-
"""r317 WebUI 批（TDD 先行，审计报告 _scratch/r317_webui.md）：

P2-1 /api/state 半可信文本 10 个字段落点被当 HTML 解释——
    depTime/arrTime/dur/agePolicy/riskPolicy/plat/date/layoverT/
    lay2dep/transGoDate 裸插（明细表 td 与 chips onclick JS 串），
    注入 `<img src=x onerror=...>` 探针 10 旗标全亮、31 img 实体化。
    修复=文本落点 he() 统一 + 行实例键 plat 段入 fp() 同款源头清洗
    + chips/健康格/脉冲柱 onclick JS 串改 data-* + dataset 取值
    （值无损、无断串面）+ citydl esc。
P3-3 FLT.pmin/pmax 不入 saveUI/restoreUI——刷新后价格上下限静默
    丢失（同排搜索词/筛选/排序全恢复，粒度不一致）。
P3-4 打印形态：入场动画（.viewin/.rowin）在打印管线从 opacity:0
    起播 → 正文卡与整张明细表打印为零；@media print 全局禁动画
    （打印=静态快照，与 prefers-reduced-motion 同构）。
P3-5 读屏地标：无 <main>/role=main、#ftable 无 caption（视觉隐藏）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r317_webui_inject.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- 源码钉（轻量，防回退） ----------

def test_citydl_datalist_escapes_keys():
    """P3-1 城市键转义律（r320 随迁移改写）：native datalist 已退役
    （289 城自定义面板替代）——旧填充点禁复活；面板城市项经 esc()
    入 data-n（转义语义保留：`data-n="${esc(n)}"`）。"""
    src = _page_src()
    assert "citydl" not in src, "native datalist 复活（r320 已退役）"
    i = src.find('data-n="${esc(n)}"')
    assert i > 0, "面板城市项 esc 转义点不在场"
    assert src.count('data-n="${esc(n)}"') >= 1


def test_health_pulse_clicks_use_dataset_not_jsstring():
    """P3-2：健康格 showLog 与脉冲柱 gotoPulseHealth 的 onclick 不再
    拼 JS 串实参（'${p}'/'${r.ts}' 断属性族），改 data-* + this。"""
    src = _page_src()
    assert "showLog('${p}','${r.ts}')" not in src
    assert "gotoPulseHealth('${r.ts}','${bad}')" not in src
    assert "onclick=\"showLog(this)\"" in src
    assert "gotoPulseHealth(this)" in src


def test_main_landmark_and_table_caption_source_pin():
    """P3-5：main 地标与明细表 caption（视觉隐藏）在源码在场。"""
    src = _page_src()
    assert "<main" in src or 'role="main"' in src
    assert "ftable'）" in src or "ftable'" in src  # 表 id 既有
    i = src.find("<table id=\"ftable\"")
    if i < 0:
        i = src.find("id=\"ftable\"")
    assert i > 0, "#ftable 表标签不在场"
    seg = src[i:i + 400]
    assert "<caption" in seg, seg[:200]


# ---------- 行为钉（demo 实例） ----------

@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8797" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    base = None

    def _free_port():
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    for _attempt in (1, 2):
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
        else:
            continue
        break
    yield base
    try:
        proc.kill()
    except Exception:
        pass
    logf.close()


_POISON = '<img src=x onerror="window.__XSS_{f}=1">'
_FIELDS = ("depTime", "arrTime", "dur", "agePolicy", "riskPolicy",
           "plat", "date", "layoverT", "lay2dep", "transGoDate")


def _injected_state(base):
    """取真实 demo state，首航班 10 字段落毒值（探针同构 C1 报告）。"""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    raw = op.open(base + "/api/state", timeout=5).read().decode("utf-8")
    st = json.loads(raw)
    f0 = st["users"][0]["flights"][0]
    for fld in _FIELDS:
        f0[fld] = _POISON.format(f=fld)
    return st


def test_state_field_injection_never_executes(srv):
    """P2-1 行为钉：/api/state 毒字段渲染为文本——10 旗标全灭、
    明细表与三组 chips 内零实体化 img。"""
    from playwright.sync_api import sync_playwright
    st = _injected_state(srv)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/state", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(st)))
        pg.goto(srv)
        pg.wait_for_timeout(1200)
        # 进明细视图（行渲染发生）
        pg.evaluate("typeof showMonTab==='function'&&showMonTab('details')")
        pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                    "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
        pg.wait_for_timeout(600)
        flags = pg.evaluate(
            "Object.keys(window).filter(k=>k.indexOf('__XSS_')===0)")
        assert flags == [], ("注入串被当 HTML 解释执行，旗标点亮：%s" % flags)
        # 官方渠道图标是受控的内嵌 img.bic（非毒字段实体化）：排除后
        # 仍要求表内/chips 内零任意 img，XSS 意图不变。
        # 官方图标把 .bic 放在可信 wrapper span 上（渠道方形/航司圆形），
        # img 自身无类；按 closest('.bic') 排除受控图标后，毒字段仍须零 img。
        stray = pg.evaluate(
            "()=>[...document.querySelectorAll("
            "'#ftable img,#platchips img,#datechips img,#routechips img')]"
            ".filter(i=>!i.closest('.bic')).length")
        assert stray == 0, "表内/chips 内实体化 img=%d" % stray
        assert errs == [], "页面 JS 错误：%s" % errs[:3]
        br.close()


def test_row_expand_and_chip_toggle_still_work(srv):
    """防退化行为钉：转义/data-* 改造不破坏既有交互——行点击展开
    翻转、日期 chip 点击翻 on 且表格过滤生效。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(srv)
        pg.wait_for_timeout(1200)
        pg.evaluate("typeof showMonTab==='function'&&showMonTab('details')")
        pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                    "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
        pg.wait_for_timeout(600)
        # 行点击展开：xrow display none → 可见（tgrow 兼 xrow 类，
        # 断言「存在可见 xrow」而非第一条——首行带改期胶囊时第一条
        # xrow 是 tgrow，由 TGOPEN 控制不随 EXP 翻）
        row = pg.locator("#ftable tbody tr:not(.xrow)").first
        row.click()
        pg.wait_for_timeout(300)
        vis = pg.evaluate(
            "(()=>{const xs=[...document.querySelectorAll('#ftable tr.xrow')];"
            "return xs.length?xs.some(x=>getComputedStyle(x).display!=='none')"
            ":  'MISS';})()")
        assert vis is True, "行点击未展开（可见 xrow=%r）" % vis
        # 日期 chip 点击翻 on
        chip = pg.locator("#datechips .chip:not(.srtchip)").first
        if chip.count() > 0:
            chip.click()
            pg.wait_for_timeout(300)
            on = pg.evaluate(
                "document.querySelector('#datechips .chip:not(.srtchip)')"
                ".classList.contains('on')")
            assert on, "日期 chip 点击未翻 on（dataset 迁移破坏切换）"
        assert errs == [], "页面 JS 错误：%s" % errs[:3]
        br.close()


def test_price_bounds_persist_across_reload(srv):
    """P3-3 行为钉：价格上下限入 saveUI/restoreUI——设 fpmin=500 触发
    applyFlt 后刷新，FLT.pmin 与输入框均恢复 500。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(srv)
        pg.wait_for_timeout(1200)
        pg.evaluate("typeof showMonTab==='function'&&showMonTab('details')")
        pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                    "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
        pg.wait_for_timeout(400)
        pg.evaluate("$('fpmin').value='500';applyFlt();saveUI();")
        pg.wait_for_timeout(200)
        pg.reload()
        pg.wait_for_timeout(1200)
        got = pg.evaluate(
            "({pmin:FLT.pmin,inp:($('fpmin')||{}).value})")
        assert got["pmin"] == 500, "FLT.pmin 刷新后=%r（期望 500）" % got["pmin"]
        assert got["inp"] == "500", "输入框未回填：%r" % got["inp"]
        br.close()


def test_print_media_disables_entry_animations(srv):
    """P3-4 行为钉：print 媒体下入场动画（.viewin/.rowin）禁用——
    animationName 为 none（打印管线不再捕获 opacity:0 首帧）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(srv)
        pg.wait_for_timeout(1200)
        pg.evaluate("typeof showMonTab==='function'&&showMonTab('details')")
        pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                    "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
        pg.wait_for_timeout(600)
        pg.emulate_media(media="print")
        names = pg.evaluate(
            "(()=>{const v=document.querySelector('.viewin');"
            "const r=document.querySelector('#ftable tbody tr');"
            "return {v:v?getComputedStyle(v).animationName:'MISS',"
            "r:r?getComputedStyle(r).animationName:'MISS'};})()")
        pg.emulate_media(media="screen")
        assert names["v"] == "none", (
            ".viewin print 态 animationName=%r（期望 none）" % names["v"])
        assert names["r"] == "none", (
            "明细行 print 态 animationName=%r（期望 none）" % names["r"])
        br.close()


def test_main_landmark_and_caption_behavior(srv):
    """P3-5 行为钉：main 地标可达（读屏跳主内容）、#ftable caption
    在场（视觉隐藏形态允许）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(srv)
        pg.wait_for_timeout(1200)
        assert pg.evaluate(
            "!!(document.querySelector('main,[role=main]'))"), "无 main 地标"
        pg.evaluate("typeof showMonTab==='function'&&showMonTab('details')")
        pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                    "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "!!document.querySelector('#ftable caption')"), "明细表无 caption"
        br.close()
