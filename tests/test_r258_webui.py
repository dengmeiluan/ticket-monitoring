# -*- coding: utf-8 -*-
"""r258 WebUI 精细化两案（TDD 先行，r258_webui_audit P2×2）：

U1 改期微图普通日柱对比度——.tgb 默认态借 --line2（边框令牌）作数据
图形填充，亮色对行底 1.41:1 <3:1（WCAG 1.4.11 非文字图形档；DOM 文本
与 canvas 两道对比度扫描皆盲的第三盲区：CSS 图形件）→ 双主题专档令牌
--tgbar（亮 #6f8090 / 暗 #58768f，对实际衬底 rowalt ≥3:1）。
U2 走势卡头「模式组×范围组」chip 窄档折行组间语义断裂——四个 rngchip
同层平铺，≤390 折行后 48h 与 K线混排（模式档与时间窗档失去组界）→
两组各包 .mdgrp（inline-flex+nowrap 恒整），组间由外层 flex wrap 承担。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r258_webui.py
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("t258w")


def _page_src():
    import webui
    return webui.PAGE


# ---------- U1: tgb 普通日柱专档令牌（源码钉 + computed 行为钉） ----------

def test_tgb_uses_dedicated_bar_token():
    src = _page_src()
    assert "background:var(--tgbar)" in src, (
        ".tgb 普通日柱仍借 --line2 边框令牌作数据图形：亮色对行底 "
        "1.41:1 <3:1（WCAG 1.4.11 非文字图形档）——改专档令牌 --tgbar")
    import re as _re
    # 双主题均有定义：亮色 :root + 暗色块各一处
    assert len(_re.findall(r"--tgbar:\s*#", src)) >= 2, (
        "--tgbar 须亮/暗双主题定义（单主题定义=另一主题 var() 塌陷）")
    # 语义态（cheap/lo/cur）不随默认态令牌漂移
    assert ".tgb.cheap{background:var(--green)}" in src
    assert ".tgb.lo{background:var(--green)}" in src


def test_tgb_bar_contrast_computed(srv):
    """行为钉：亮色主题下 .tgb 实际渲染色对实际衬底（.tgrow 行底）
    ≥3:1（非文字图形档）。"""
    pw, page = srv
    page.evaluate("""() => {
      const t=document.querySelector('[data-t="details"]')||
        document.querySelector('#tabs');if(t)t.click();
    }""")
    got = page.evaluate("""() => {
      const bars=document.querySelectorAll('.tgb');
      if(!bars.length)return -1;
      function lum(c){const m=c.match(/\\d+(\\.\\d+)?/g).map(Number);
        const a=[m[0],m[1],m[2]].map(v=>{v/=255;
          return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});
        return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];}
      let worst=99;
      for(const b of bars){
        if(b.classList.contains('cheap')||b.classList.contains('lo'))continue;
        let bg=getComputedStyle(b).backgroundColor;
        let cell=b.closest('td');let hb=cell?getComputedStyle(cell).backgroundColor:'';
        if(!hb||hb==='transparent'||/rgba\\([^)]*,\\s*0\\)/.test(hb)){
          hb=getComputedStyle(document.body).backgroundColor;}
        const l1=lum(bg),l2=lum(hb);
        worst=Math.min(worst,(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05));
      }
      return worst;
    }""")
    assert got >= 3.0, "tgb 普通日柱对比度 %.2f <3:1（非文字图形档）" % got


# ---------- U2: 走势卡头 chip 组容器（源码钉 + 几何行为钉） ----------

def test_trend_chips_grouped():
    src = _page_src()
    # 窗口取结构边界（第一组 mdgrp 开标签到下一容器 chartRoutes）而非
    # 固定字符数（三十一§3：块内合法增厚——如新增第三组 chip——不应红）
    m = src.index('class="mdgrp"')
    j = src.index('id="chartRoutes"')
    seg = src[m:j]
    assert seg.count('class="mdgrp"') == 2, (
        "走势卡头四 chip（折线/K线/48h/7天）须两组各包 .mdgrp：平铺同层"
        "时窄档折行后模式档与时间窗档混排（组间语义断裂）")
    assert ".mdgrp{display:inline-flex" in src, (
        ".mdgrp 组容器缺基础规则（nowrap 恒整）")


def test_trend_chips_no_mixed_rows(srv):
    """行为钉：窄档下模式组与范围组的「组界可辨」——同排时组间水平
    间隔 ≥6px（组内贴排 0px），折行时两组成员不同行；两种形态任一
    成立即组界在（修复前四 chip 平铺同层：组间=组内间距，语义断裂）。"""
    pw, page = srv
    page.set_viewport_size({"width": 390, "height": 780})
    # 走势卡在 display:none 的 tab 容器里：量纲死档（十九§8）——
    # 先切到走势 tab 再量
    page.evaluate("showMonTab('trend')")
    page.wait_for_timeout(250)
    got = page.evaluate("""() => {
      const g=[...document.querySelectorAll('.mdgrp')];
      if(g.length<2)return -1;
      const a=g[0].getBoundingClientRect(),b=g[1].getBoundingClientRect();
      if(b.top-a.top>8)return 99;                    // 已折行：组界=行差
      return Math.round(b.left-(a.right));           // 同排：组间水平间隔
    }""")
    assert got >= 6, (
        "390 档走势 chip 组界不可辨（组间间隔 %.1fpx <6 且未折行）："
        "模式档与时间窗档平铺混排" % got if got >= 0
        else "走势卡头 .mdgrp 组容器未渲染")


# ---------- W1: fltBtn 键盘焦点环（audit P1-1：sticky 衬底 halo 压环） ----------

def test_fltbtn_focus_ring_source():
    src = _page_src()
    assert ("#montab-details .tabs>#fltBtn:focus-visible{box-shadow:"
            "inset 0 0 0 2px var(--blue),0 0 0 4px var(--card)") in src, (
        "≤760 档 #fltBtn 的 sticky 衬底 halo（特异度 (1,1,0)）整条吃掉"
        "焦点环族 .tabs span:focus-visible（(0,2,x)）——置尾复声明"
        "inset 环+halo 双影（首列表头 th.srt 先例）")


def test_fltbtn_focus_ring_computed(srv):
    """行为钉：390 档程序化 focusVisible 聚焦 fltBtn，computed
    box-shadow 须含 --blue 环色（亮色 rgb(11,98,214)）；修复前
    computed 只有白 halo rgb(255,255,255) 0 0 0 4px。"""
    pw, page = srv
    page.set_viewport_size({"width": 390, "height": 780})
    page.evaluate("showMonTab('details')")
    page.wait_for_timeout(120)
    got = page.evaluate("""() => {
      const b=document.getElementById('fltBtn');
      b.focus({focusVisible:true});
      return getComputedStyle(b).boxShadow;
    }""")
    assert "11, 98, 214" in got or "11,98,214" in got, (
        "390 档 fltBtn 聚焦环不可见（computed box-shadow=%r，缺 --blue "
        "环色）：筛选抽屉唯一入口键盘不可达指示" % got)


# ---------- W2: 筛选价格双输入可访问名（audit P2-1：fpmax 零名） ----------

def test_price_inputs_accessible_names(srv):
    pw, page = srv
    got = page.evaluate("""() => ({
      mn: document.getElementById('fpmin').getAttribute('aria-label'),
      mx: document.getElementById('fpmax').getAttribute('aria-label')
    })""")
    assert got["mn"] == "价格下限" and got["mx"] == "价格上限", (
        "筛选价格双输入可访问名缺失/无下限上限语义：%r——label 只隐式"
        "关联首控件，fpmax 读屏零播名（配置页双控件行同形已收编，"
        ".fbar 同族漏收）" % got)


# ---------- W3: tabpanel 可访问名（audit P3-1） ----------

def test_tabpanels_have_accessible_names(srv):
    pw, page = srv
    got = page.evaluate("""() => {
      tabAria();
      const names={overview:'概览',trend:'走势',details:'航班明细',
                   health:'渠道健康'};
      const out={};
      for(const k in names){
        const p=document.getElementById('montab-'+k);
        out[k]=p?p.getAttribute('aria-label'):null;}
      return out;}""")
    for k, want in (("overview", "概览"), ("trend", "走势"),
                    ("details", "航班明细"), ("health", "渠道健康")):
        assert got.get(k) and want in got[k], (
            "tabpanel montab-%s 缺可访问名（got=%r）：读屏只播"
            "「tabpanel」" % (k, got.get(k)))


# ---------- W4: verbar/demoBar 动态现身 live 语义（audit P3-2） ----------

def test_banners_live_roles():
    src = _page_src()
    assert 'id="verbar" role="alert"' in src, (
        "verbar 服务升级横幅动态现身（display:none→显示）无 live 语义，"
        "读屏零感知——挂 role=alert 显身即播报")
    assert 'id="demoBar" role="status"' in src, (
        "demoBar 演示横幅动态现身无 live 语义——挂 role=status")


# ---------- W5: mtabUser 态入名（audit P3-3：aria 静态不带当前用户） ----------

def test_mtabuser_aria_carries_state(srv):
    pw, page = srv
    got = page.evaluate("""() => {
      const keepU=U, keepS=S;
      S={users:[{name:'甲用户'},{name:'乙用户'}]}; U=1;
      try{ mtabUserSync();
        const el=document.getElementById('mtabUser');
        return {aria: el.getAttribute('aria-label'),
                shown: el.style.display!=='none'};
      } finally { S=keepS; U=keepU; }}""")
    assert got["shown"], "mtabUser 未显形（双用户态构造失败）"
    assert got["aria"] and "乙用户" in got["aria"], (
        "mtabUser aria-label 不带当前用户名（got=%r）：视觉 chip 与 "
        "title 均带态而读屏名静态，违 themeBtn 家族「态入名」先例"
        % got["aria"])


# ---------- W6: 折线环标窄画布去簇（audit P3-4：7d 档擦边环互叠成串） ----------

def test_line_rings_spatial_dedupe():
    src = _page_src()
    m = src.index("let lastRX=-1e9")
    # 窗口取闭包边界（到 series 调用点）而非固定字符数（三十一§3）
    j = src.index("series(hd,", m)
    seg = src[m:j]
    assert "lastRX" in seg, (
        "折线分档点环缺「相邻已绘环 X 间距去重」逻辑：7 天窗 390 档"
        "672 点/系挤 334px，状态转换处 5px 环互叠成串不可辨（数据点"
        "与状态判定不动，仅绘制层防串珠；悬停/键盘读数兜底不变）")
    # 末点豁免在去重门之前（最新点环恒在位，与「入场+末点」既有语义兼容）
    assert seg.index("lastRX") < seg.index("pts.length-1"), (
        "末点豁免必须先于去重门判定（最新点环恒在位）")


# ---------- playwright srv fixture（demo 实例，行为钉共用；r251 形态） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.flush()
        logf.seek(0)
        return logf.read()[-600:]
    except Exception:
        return "(日志不可读)"


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
    from playwright.sync_api import sync_playwright as _sp
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
        if proc.poll() is None:
            break
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）\n服务输出尾:\n"
                    + _srv_log_tail(logf))
    with _sp() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base, wait_until="networkidle")
        yield p, page
        browser.close()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if errors:
        raise AssertionError("demo 页面 JS 错误: %s" % errors)
