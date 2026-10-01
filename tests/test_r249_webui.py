# -*- coding: utf-8 -*-
"""r249 WebUI 三案（TDD 先行，审计报告 _scratch/r249_webui_audit.md）：

P1-1 首列表头键盘焦点环被吸附列投影覆盖——.tw th:first-child 的
    box-shadow:2px 0 0 var(--line)（L966 族）与 th.srt:focus-visible 的
    inset 环（L583）同特异性 (0,2,1)，源码序后者在前被压制：col[0]
    （价格列=默认排序入口=最高频键盘排序入口）聚焦时蓝环缺失，探针
    实测 computed boxShadow 只剩吸附投影。修法：置尾复声明双影叠加
    （inset 环 + 吸附投影共存）。源码钉锁「新规则在场且 rindex 晚于
    投影声明」（同特异性层叠胜负由源码序决定，声明值钉锁不住）。
P2-1 输入焦点环 150ms 淡入——#fq(fbar)/#cfgSearch/srow 三基座
    transition:border-color .15s,box-shadow .15s 未豁免（th.srt 表头
    环 r221 P2-6 同族已修，输入族漏网）：focus 时环淡入 ~150ms，
    Tab 巡航滞后。修法：三处 focus 规则补 transition:box-shadow 0s
    （聚焦态即时，失焦淡出保留——表头先例同形态）。
P2-2 renderCal 达标格 fg 硬编码 '#fff' × bg 活变量 'var(--green)'：
    亮暗主题 --green 不同值（#0e8345/#43c072），绕过 applyTheme 直接
    翻 data-theme 时 CSS 变量联动而 JS 不重渲，白字衬亮绿 #43c072
    实测 2.33:1 欠 AA。修法：bg 写死运行时实色 'rgb('+CG+')'
    （渲染时刻 --green 实值，applyTheme 重渲后刷新为新主题实色）——
    现网靠重渲兜住的隐性契约消除，翻主题不重渲时白字衬旧主题深绿
    恒达标。行为钉读页面实际加载的函数体（toString）。

P2-3（srtchip 末行孤格）备案不修：margin-left:auto 把孤格推成右对齐
    孤格是换形态非消除，chips 折行本量内容自然结果。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r249_webui.py
"""
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


# ---------- P1-1: 首列表头焦点环（源码序层叠钉 + computed 行为钉） ----------

def test_firstcol_srt_focus_ring_source_pin():
    src = _page_src()
    ring = ".tw th.srt:first-child:focus-visible"
    assert ring in src, (
        "首列表头（价格列=默认排序入口）缺焦点环复声明：.tw th:first-child "
        "的吸附投影 (0,2,1) 源码序在后压制 th.srt:focus-visible 的 inset 环"
        "（同特异性后者胜），键盘聚焦首列时蓝环缺失")
    proj = ".tw th:first-child,.tw td:first-child{"
    assert src.index(proj) < src.index(ring), (
        "焦点环复声明必须置尾于吸附投影声明之后：同特异性层叠胜负由"
        "源码序决定，声明值钉锁不住层叠")
    m = src.index(ring)
    seg = src[m:m + 220]
    assert "2px var(--blue)" in seg and "2px 0 0 var(--line)" in seg, (
        "焦点环须双影叠加：inset 蓝环 + 吸附投影共存（单写 inset 环会"
        "反过来吃掉首列吸附投影）")


def test_firstcol_srt_focus_ring_computed(srv):
    """行为钉：首列 th 聚焦（focus-visible）时 computed boxShadow 含
    inset 蓝环与吸附投影。红态=只有投影无 inset。"""
    pw, page = srv
    got = page.evaluate("""() => {
      showMonTab('details');
      const th=document.querySelector('#ftable thead th.srt:first-child');
      if(!th)return 'NO_TH';
      th.focus({focusVisible:true});
      const bs=getComputedStyle(th).boxShadow;
      const hx=getComputedStyle(document.documentElement)
        .getPropertyValue('--blue').trim();
      const n=parseInt(hx.slice(1),16);
      const rgb='rgb('+((n>>16)&255)+', '+((n>>8)&255)+', '+(n&255)+')';
      return {inset: bs.indexOf('inset')>=0,
              blue: bs.indexOf(rgb)>=0,
              rgb: rgb,
              proj: /2px 0(px)? 0(px)?/.test(bs), bs: bs};
    }""")
    assert got != 'NO_TH', "明细表头未渲染（demo 数据缺表格）"
    assert got["inset"], "首列聚焦无 inset 环（被吸附投影压制） bs=%s" % got["bs"]
    assert got["blue"], "首列聚焦环非蓝（--blue 解析 %s 不在 %s）" % (
        got["rgb"], got["bs"])
    assert got["proj"], "修复吃掉首列吸附投影（双影须共存） bs=%s" % got["bs"]


# ---------- P2-1: 输入焦点环即时呈现（三基座源码钉 + #fq 行为钉） ----------

def test_input_focus_ring_zero_transition_pins():
    src = _page_src()
    for sel, name in (
        (".srow .sctl input:not(.switch):focus{", "srow 基座"),
        (".fbar select:focus,.fbar input:focus:not(.switch){", "fbar 基座"),
        (".cfgsearch:focus{", "cfgsearch 基座"),
    ):
        m = src.index(sel)
        seg = src[m:m + 260]
        assert "transition:box-shadow 0s" in seg, (
            "%s 焦点环仍随基座 .15s transition 淡入（th.srt 表头环 r221 "
            "P2-6 同族已修，输入族漏网）——focus 规则补 transition:"
            "box-shadow 0s" % name)


def test_input_focus_ring_zero_transition_computed(srv):
    """行为钉：#fq（fbar 基座代表件）聚焦态 computed transitionDuration
    为 0s（红态 '0.15s, 0.15s'）。"""
    pw, page = srv
    got = page.evaluate("""() => {
      showMonTab('details');
      const el=document.getElementById('fq');
      if(!el)return 'NO_FQ';
      el.focus();
      return getComputedStyle(el).transitionDuration;
    }""")
    assert got != 'NO_FQ', "明细筛选条未渲染"
    assert got == '0s', (
        "#fq 聚焦态 transitionDuration=%s（应 0s：环即时呈现，"
        ".15s 淡入让 Tab 巡航滞后）" % got)


# ---------- P2-2: renderCal 达标格 bg 运行时实色 ----------

def test_rendercal_no_live_green_var():
    src = _page_src()
    assert ":'var(--green)';fg=DK?" not in src, (
        "renderCal 达标格亮分支 bg 仍挂 var(--green) 活变量：亮暗主题 "
        "--green 不同值，绕过 applyTheme 直接翻 data-theme 时白字衬亮绿 "
        "2.33:1 欠 AA——bg 写死运行时实色消除隐性契约")
    assert "'rgb('+CG+')'" in src, (
        "达标格亮分支缺运行时实色形态 'rgb('+CG+')'（渲染时刻 --green "
        "实值，applyTheme 重渲后刷新为新主题实色）")


def test_rendercal_loaded_fn_no_live_var(srv):
    """行为钉：页面实际加载的 renderCal 函数体不含活变量（源码钉验
    磁盘、本钉验加载态——中间态 pyc 家族的双证）。"""
    pw, page = srv
    got = page.evaluate(
        "() => (typeof renderCal==='function') ? renderCal.toString()"
        ".indexOf('var(--green)') : 'NO_FN'")
    assert got != 'NO_FN', "renderCal 未定义"
    assert got < 0, (
        "页面加载的 renderCal 函数体仍消费 var(--green) 活变量"
        "（磁盘源码钉过而加载态不过=中间态产物）")


# ---------- playwright srv fixture（demo 实例，行为钉共用；r245 加固版） ----------

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
            if "127.0.0.1:8798" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    base = None
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
    with sync_playwright() as p:
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
