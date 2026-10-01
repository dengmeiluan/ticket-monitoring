# -*- coding: utf-8 -*-
"""r259 WebUI 精细化（TDD 先行，r259_webui_audit P2-1 + 备案①收口）：

U1 交互控件边界族专档令牌 --ctlbd——表单件边界/开关 off 轨借容器
hairline 令牌（--line/--line2）作「可填哪里/可开哪边」的唯一边界，
双主题对实际衬底 1.08-1.66 全 <3:1（WCAG 1.4.11 非文字图形档；
继 --tgbar 之后第三盲区家族扫的主发现：fbar 输入/下拉、.srow/.glcell
输入、.btn2、.switch off 轨、.cfgsearch、改期胶囊 .tg）→ 双主题专档
令牌（亮 #7d8fa0 对 rowalt ≈3.2 / 暗 #56718c 对 card ≈3.1），
hover 现有 --mut 提档语义不变（--mut 双主题均比 --ctlbd 更强）。
U2 前端 TIER 值域注释收口（audit 备案①）：三重不可达的防御性分支
以注释锚定值域与协议变化联动条件，防后续维护者误判死代码。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r259_webui.py
"""
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

_LOG = logging.getLogger("t259w")


def _page_src():
    import webui
    return webui.PAGE


def _block(src, sel):
    """选择器所在规则块文本（到首个 '}'，窗口随块体合法增厚）。"""
    i = src.index(sel)
    return src[i:src.index("}", i)]


# ---------- U1: 交互控件边界族专档令牌 ----------

def test_control_boundary_uses_dedicated_token():
    src = _page_src()
    import re as _re
    # 双主题定义恰 2：亮色 :root + 暗色块各一处（单主题定义=另一主题
    # var() 塌陷；第三处误增定义=旁路真值源）
    assert len(_re.findall(r"--ctlbd:\s*#", src)) == 2, (
        "--ctlbd 定义须亮/暗恰两处（少=塌陷、多=旁路真值源）")
    # 七消费点逐点锚（规则块切片，块体合法增厚不红）
    assert "background:var(--ctlbd)" in _block(src, ".switch{appearance"), (
        ".switch off 轨仍借 --line2（1.3/1.66 双主题 <3:1）：轨是开关"
        "状态指示唯一载体（开态绿轨与白钮对比随轨加深自然升档）")
    assert "border:1px solid var(--ctlbd)" in _block(
        src, ".btn2{background:var(--card)"), (
        ".btn2 边框仍借 --line2（1.3/1.66 <3:1）")
    assert "border:1px solid var(--ctlbd)" in _block(
        src, ".fbar select,.fbar input[type=text]"), (
        ".fbar 输入/下拉边界仍借 --line（1.12/1.32，白底本体对 rowalt "
        "仅 1.08 双弱）——「可填哪里」的边界在弱视/强光/低端屏消失")
    assert "border:1px solid var(--ctlbd)" in _block(
        src, ".srow .sctl input:not(.switch){"), (
        ".srow 输入边界仍借 --line2（1.3/1.66 <3:1）")
    assert "border-bottom:1px dashed var(--ctlbd)" in _block(
        src, ".glcell input:not(.switch){"), (
        ".glcell 输入下划线仍借 --line2（1.3/1.66 <3:1）")
    assert "border:1px solid var(--ctlbd)" in _block(
        src, ".cfgnav .cfgsearch{"), (
        ".cfgnav .cfgsearch 边界仍借 --line（1.12/1.32 <3:1）")
    assert "border:1px solid var(--ctlbd)" in _block(
        src, ".cfgsearch{width:100%"), (
        ".cfgsearch 边界仍借 --line2（1.3/1.66 <3:1）")
    assert "border:1px solid var(--ctlbd)" in _block(src, ".tg{"), (
        "改期胶囊 .tg 边界仍借 --line2（族内最轻，有文字冗余；随族"
        "同令牌防半深半浅）")
    # 描边钮语法族（白底蓝字边界钮）与 .btn2 同族并档：收编后留 --line2
    # 即同屏边界深浅双档
    assert "box-shadow:inset 0 0 0 1px var(--ctlbd)" in _block(
        src, "button.warn{"), "button.warn 描边仍借 --line2（与 .btn2 同屏双档）"
    assert "border:1px solid var(--ctlbd)" in _block(src, ".ropbtn{"), (
        ".ropbtn 边框仍借 --line2（与 .btn2 同屏双档）")


def test_control_boundary_contrast_computed(srv):
    """行为钉：亮色主题下 fbar 输入边界 computed 色对 fbar 行实际
    衬底 ≥3:1（非文字图形档）；修复前 --line 对 rowalt 1.12。"""
    pw, page = srv
    page.evaluate("showMonTab('details')")
    page.wait_for_timeout(120)
    got = page.evaluate("""() => {
      const el=document.querySelector('.fbar select,.fbar input[type=text]');
      if(!el)return -1;
      function lum(c){const m=c.match(/\\d+(\\.\\d+)?/g).map(Number);
        const a=[m[0],m[1],m[2]].map(v=>{v/=255;
          return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});
        return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];}
      const bd=getComputedStyle(el).borderTopColor;
      let row=el.closest('.fbar');
      let bg=row?getComputedStyle(row).backgroundColor:'';
      let node=row;
      while((!bg||bg==='transparent'||/rgba\\([^)]*,\\s*0\\)/.test(bg))&&node){
        node=node.parentElement;
        bg=node?getComputedStyle(node).backgroundColor:'';}
      if(!bg||bg==='transparent')bg='rgb(255,255,255)';
      const l1=lum(bd),l2=lum(bg);
      return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
    }""")
    assert got >= 3.0, (
        "fbar 输入边界对比度 %.2f <3:1（非文字图形档）：" % got)


# ---------- U2: 前端 TIER 值域注释收口（audit 备案①） ----------

def test_tier_value_domain_note():
    src = _page_src()
    i = src.index("const TIER=")
    seg = src[max(0, i - 1500):i]
    assert "TIER 值域" in seg and "语义分叉" in seg, (
        "前端 TIER 值域 {2,1,-1,0} 注释缺位：q===0∧v≤tv 落 2 的分支"
        "与服务端语义分叉且现三重不可达（纯防御性冗余），无值域注释"
        "会被误判死代码删除；后端旗标协议变化时此处必须改出 1 的"
        "联动条件须随注释在场")


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
