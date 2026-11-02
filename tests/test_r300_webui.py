# -*- coding: utf-8 -*-
"""r300 WebUI 审计三案（TDD 先行，审计报告 _scratch/r300_webui.md）：

P1-1 配置页「监控渠道」选中胶囊亮色不可读（1.5.206 W1 回归）——
    .chip.pch.p-*.on 换 14% 渠道色浅底时只覆写 background 未覆写
    color，继承 .chip.on{color:#fff}：亮色白字压浅 tint ≈1.17~1.21:1
    （AA 需 4.5）；暗色 13.8~14.5:1 通过故被「暗色常态」掩盖。修法：
    每颗 on 规则补 color:color-mix(in srgb,var(--c-*) 60%,var(--tx))
    （亮色复算 5.96~6.96:1、暗色 7.1:1 双过；color-mix 不支持内核
    整条塌回 .chip.on 蓝底白字=原成立档，回退自洽）。
P3-1 行尾末片日期 ✕ 实效命中 23~28px（r294 P3-2 适用域外残留）——
    ::after inset:-14px 的右向扩展只在「同行右缘有后续行内件」语境
    兑现；行尾悬空态（单日期路由=演示默认态）+10 即失效。修法：
    实体盒承载（display:inline-block + padding:0 14px 0 0 +
    margin-right:-14px 净布局零位移），::after 右向收敛 inset 为 0
    防 padding 撑盒后双倍越界（邻片侵入），左向/纵向维持 -14px。
    实体盒命中不受行尾片段边界影响（+0 中心实证），::after 仍兜
    左向与纵向。r294 源码钉随形态改写（双段断言：新实体盒在场 +
    旧四面 inset 禁复活）；computed 钉（::after ≥36）在新几何下
    37×43 依旧成立不改。
P3-2 五颗渠道胶囊 title 无差别挂「携程需本机已建立登录态」——
    buildForm 公共片段写死。修法：title 按渠道条件化（ctrip 保留
    登录提示词面，其余「开箱即用」，与shint 产品文案同语言）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r300_webui.py -q
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHANS = ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu")


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（形态同 test_r294_webui.py，端口 8801） ----------

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
            if "127.0.0.1:8801" in ln and "LISTENING" in ln:
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


def _open_cfg_users_light(page):
    """亮色语境 + 390 窄视口进入 cfg-users 面板并展开全部航线卡
    （display 切换架构，十八§8：先真实展开再取样；390 是语境 B 的
    必要条件——宽视口下行尾悬空形态不成立，探针假绿教训同日双踩；
    demo 路由=单日期形态，日期片 ✕ 恒处行尾悬空位）。fresh 页面
    theme=auto 跟随 media，emulate light 即亮色主题。"""
    page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("switchView('cfg')")
    page.evaluate("showCfgPanel('users')")
    page.wait_for_timeout(300)
    page.evaluate("""()=>{
      document.querySelectorAll('#cfgform .rline[data-rk]').forEach(rl=>{
        FOLD.route[rl.dataset.rk]=false;});
      applyFolds();
    }""")
    page.wait_for_timeout(300)


def _srgb_lum(c):
    """WCAG 相对亮度：c=(r,g,b) 0~1。"""
    def lin(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def _parse_color(s):
    """解析 computed 颜色为 (r,g,b) 0~1 三元组。支持 rgb()/rgba() 与
    color(srgb ...)（color-mix 的 computed 序列化形态——审计假阳2 的
    采样器缺口：不认 color(srgb) 会回溯合成假底，本案 P1 恰在其下）。"""
    s = s.strip()
    m = re.match(r"color\(\s*srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return tuple(float(x) for x in m.groups())
    m = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", s)
    if m:
        return tuple(int(x) / 255.0 for x in m.groups())
    raise ValueError("unparsed color: %r" % s)


def _wcag_ratio(fg, bg):
    l1, l2 = _srgb_lum(fg), _srgb_lum(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ---------- P1-1: 渠道胶囊选中态亮色对比度 ----------

def test_pch_on_text_color_source_pin():
    """源码钉：五颗 .chip.pch.p-*.on 规则各自带 color 混色声明——
    亮色文字档与浅底同轮落（W1 只换底不换字=白字压浅 tint 1.2:1
    的根因面）；计数钉防姊妹块漏改（「同值补档的声明族全族清点」
    十六§1 姊妹律）。"""
    src = _page_src()
    for ch in CHANS:
        decl = "color:color-mix(in srgb,var(--c-%s) 60%%,var(--tx))" % ch
        assert decl in src, "p-%s 选中态缺文字色覆写（亮色白字压浅底回归）" % ch
    n = src.count(" 60%,var(--tx))")
    assert n == 5, "渠道文字色混色声明族计数=%d（应恰 5，姊妹块漂移）" % n


def test_pch_on_light_contrast_behavior(srv):
    """行为钉：亮色主题 cfg-users 面板，选中渠道胶囊 文字/底 computed
    对比度 ≥4.5（AA，12px 文字档）。解析器认 color(srgb) 形态。
    亮色语境显式断言 data-theme==='light'（app 无 matchMedia change
    监听，emulate 不驱动切换——语境漂移到暗色档时钉必须响红而非
    在暗色对比度同样达标的档位静默假绿）；逐颗采样全部 on 胶囊
    （最差档与典型档同测，单发只测首颗会漏最差渠道）。"""
    _pw, page = srv
    _open_cfg_users_light(page)
    r = page.evaluate("""(()=>{
      const th=document.documentElement.dataset.theme||'auto';
      const els=[...document.querySelectorAll('.chip.pch.on')];
      if(!els.length)return {err:'no .on pch chip'};
      return {th, chips:els.map(el=>{
        const cs=getComputedStyle(el);
        return {txt:el.textContent.trim(), col:cs.color, bg:cs.backgroundColor};
      })};
    })()""")
    assert "err" not in r, "取样失败（%s）" % r.get("err")
    assert r["th"] == "light", \
        "亮色语境未成立（data-theme=%s）——钉面语境显式化" % r["th"]
    assert len(r["chips"]) >= 2, \
        "on 胶囊 %d 颗（<2，逐颗采样面不足）" % len(r["chips"])
    worst = None
    for c in r["chips"]:
        ratio = _wcag_ratio(_parse_color(c["col"]), _parse_color(c["bg"]))
        if worst is None or ratio < worst[0]:
            worst = (ratio, c["txt"])
    assert worst[0] >= 4.5, \
        "选中胶囊亮色对比度最差档 %.2f:1（%s 白/彩底 <4.5，渠道名不可读）" % worst


# ---------- P3-1: 行尾末片 ✕ 实体命中（语境 B） ----------

def test_dx_entity_box_source_pin():
    """源码钉（双段，十八§9）：新实体盒三声明在场 + 旧四面 inset
    禁复活（inset:-14px 四向等值形态会随 padding 撑盒右向双倍越界
    侵入邻片命中区——退役的是形态不是能力，左/纵向由三值档承载）。"""
    src = _page_src()
    assert re.search(r"\.dchip \.dx\{[^}]*display:inline-block", src), \
        ".dx 实体盒形态缺失（行尾命中回退 inline 片段边界）"
    assert re.search(r"\.dchip \.dx\{[^}]*padding:0 14px 0 0", src), \
        ".dx 右向实体 padding 缺失（语境 B 右向 +10 失效残留）"
    assert re.search(r"\.dchip \.dx\{[^}]*margin-right:-14px", src), \
        ".dx 负 margin 对消缺失（净布局零位移破坏）"
    assert ".dchip .dx::after{content:'';position:absolute;inset:-14px 0 -14px -14px}" in src, \
        ".dx ::after 三值档缺失（左/纵扩展丢失或右向双倍越界）"
    assert "inset:-14px}" not in src, \
        "旧四面 inset:-14px 形态复活（padding 撑盒后右向双倍越界）"


def test_dx_trailing_hit_behavior(srv):
    """行为钉（语境 B 采样，r294 适用域外残留面）：demo 全部路由为
    单日期形态=每颗 ✕ 都在行尾悬空位。逐颗实测 elementFromPoint：
    中心 +0 恒命中（实体盒既有事实），字形右缘 +9px（旧缺陷带 +4~+10
    五连点全落空的区间中点）必须命中 ✕ 本体。"""
    _pw, page = srv
    _open_cfg_users_light(page)
    r = page.evaluate("""()=>{
      const dxs=[...document.querySelectorAll('.dchip .dx')];
      if(!dxs.length)return {err:'no dx'};
      const out=[];
      for(const dx of dxs){
        dx.scrollIntoView({block:'center'});
        const rng=document.createRange();
        rng.selectNodeContents(dx);
        const g=rng.getBoundingClientRect();
        if(g.width===0)continue;
        const cy=g.top+g.height/2;
        const at=x=>{
          const el=document.elementFromPoint(x,cy);
          return el===dx||(el&&dx.contains(el));
        };
        out.push({center:at(g.left+g.width/2), right9:at(g.right+9)});
      }
      return {n:out.length, out};
    }""")
    assert "err" not in r, "取样失败（%s）" % r.get("err")
    assert r["n"] >= 3, "日期片样本 %d 颗（demo 态异常）" % r["n"]
    bad = [i for i, s in enumerate(r["out"]) if not s["center"]]
    assert not bad, "中心命中失败样本 %s（实体盒本体被挡？）" % bad
    bad9 = [i for i, s in enumerate(r["out"]) if not s["right9"]]
    assert not bad9, \
        "字形右缘 +9px 命中失败样本 %s/%d（行尾悬空语境 B 残留未修）" % (
            bad9, r["n"])


# ---------- P3-2: 渠道胶囊 title 条件化 ----------

def test_plat_chip_title_source_pin():
    """源码钉：title 按渠道条件化（ctrip/qunar 需登录，其余开箱即用）；
    写死公共片段形态禁复活（title=\"携程…\" 带属性前缀的精确形态——
    shint 帮助文本里同词面是合法在场，不误伤）。"""
    src = _page_src()
    assert ("title=\"${(p==='ctrip'||p==='qunar')?'需本机已建立登录态'"
            ":'开箱即用'}\"") in src, "渠道胶囊 title 未按渠道条件化"
    assert 'title="携程需本机已建立登录态"' not in src, \
        "写死 title 公共片段复活（五颗全挂携程词面）"


def test_plat_chip_title_behavior(srv):
    """行为钉：qunar/ctrip 胶囊 title=需本机已建立登录态，fliggy
    保持开箱即用（2026-10 去哪儿 H5 登录门）。"""
    _pw, page = srv
    _open_cfg_users_light(page)
    r = page.evaluate("""()=>{
      const get=p=>{const el=document.querySelector('.chip.pch.p-'+p);
        return el?el.getAttribute('title'):null;};
      return {qunar:get('qunar'), ctrip:get('ctrip'),
              fliggy:get('fliggy')};
    }""")
    assert r["qunar"] is not None, "qunar 胶囊未渲染（面板态异常）"
    assert r["qunar"] == "需本机已建立登录态", (
        "qunar title=%r（H5 登录门）" % r["qunar"])
    assert r["fliggy"] == "开箱即用", "fliggy title=%r" % r["fliggy"]
    assert r["ctrip"] == "需本机已建立登录态", (
        "ctrip title=%r（登录提示丢失）" % r["ctrip"])
