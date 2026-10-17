# -*- coding: utf-8 -*-
"""r244 WebUI 四案落地钉（_scratch/r244_webui.md 审计消化）：

- W-1 (P2-1) 移动首屏数据上移：opscard 四个日频级操作钮 + 提示行在
  ≤760 档占首屏 ~60% 高（390 实测），KPI/明细被推出首屏——按钮行
  收编单行横滚、提示行隐藏（桌面不变，.opsbtns 包裹层零行为差）。
- W-2 (P3-1) 走势稀疏系列（直挂航线中转仅 2 点的真实形态）只画点
  不连线：两点间平滑曲线+面积在右缘画成陡坡，读感「暴跌」；配
  ringNote 稀疏注（装饰信号不领先数据，二十三§6）。
- W-3 (P3-2) 非 JSON 响应体（502 错误页/网关截断）词面归「服务异常」
  档：JSON.parse 抛错曾落外层 catch 被当网络不可达误报「服务未启动」
  （服务明明应答了）；route.fulfill 模拟（不污染零 JS 错门，二十三§2）。
- W-4 (P3-4) 配置页 .grouplab .no 装饰蓝收中性灰：与监控页 .seclab .no
  同语义同谱（蓝只用于交互/数据锚点，.impeccable.md 令牌纪律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r244_webui.py -q
"""
import os
import re
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8798
BASE = "http://127.0.0.1:%d" % PORT


def _page_src():
    import webui as _w
    return _w.PAGE


def _wait_up():
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        import os as _os
        if not _os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    r = subprocess.run(["netstat", "-ano"], capture_output=True)
    for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
        if ("127.0.0.1:%d" % PORT) in ln and "LISTENING" in ln:
            subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                           capture_output=True)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_up(), "demo 启动失败"
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10000)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        yield page
        b.close()


# ---- W-1：移动首屏数据上移 ----

def test_opscard_mobile_single_row(pg):
    """≤760 档：opscard 压成单行横滚钮排 + 提示行隐藏——卡高 ≤110
    （旧行为四钮折行+提示行 ~200px+），按钮触控高 ≥36 保持。"""
    pg.set_viewport_size({"width": 390, "height": 740})
    pg.wait_for_timeout(300)
    m = pg.evaluate("""()=>{const c=$('opscard');
      const btns=[...c.querySelectorAll('.opsbtns>button')];
      const hint=c.querySelector('.row>.muted');
      const tops=btns.map(b=>b.getBoundingClientRect().top);
      return {h:c.offsetHeight,
              hintHidden:!hint||getComputedStyle(hint).display==='none',
              minBtnH:Math.min(...btns.map(b=>b.offsetHeight),999),
              oneRow:tops.length>0&&Math.max(...tops)-Math.min(...tops)<2};}""")
    pg.set_viewport_size({"width": 1280, "height": 900})
    assert m["h"] <= 110, m
    assert m["hintHidden"], m
    assert m["minBtnH"] >= 36, m
    assert m["oneRow"], m


def test_opscard_desktop_unchanged(pg):
    """桌面档回归：.opsbtns 包裹后四钮仍折行排布（wrapper 零行为差）、
    提示行在场。"""
    m = pg.evaluate("""()=>{const c=$('opscard');
      const btns=[...c.querySelectorAll('.opsbtns>button')];
      const hint=c.querySelector('.row>.muted');
      return {n:btns.length,
              hintShown:!!hint&&getComputedStyle(hint).display!=='none',
              wrap:getComputedStyle(c.querySelector('.opsbtns')).flexWrap};}""")
    assert m["n"] == 4, m
    assert m["hintShown"], m
    assert m["wrap"] == "wrap", m


# ---- W-2：稀疏系列只画点不连线 ----

_SPARSE = ("const cr=curRoute();cr.range='48h';cr.r.history="
           "{direct:[['10-01 08:00',1000,0],['10-01 20:00',1010,0],"
           "['10-02 08:00',1020,0]],"
           "transfer:[['10-02 04:00',900,0],['10-02 08:00',950,0]]};"
           "cr.r.th={direct:800,transfer:800};")


def test_sparse_series_no_line(pg):
    """折线：中转 2 点稀疏系列不画连线——直飞 3 点 2 段贝塞尔，
    中转若画线会 +1；修复后全程贝塞尔恒 2。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                + _SPARSE + "chart();")
    cap = pg.evaluate("""()=>{const cap={bz:0};
      const ob=CanvasRenderingContext2D.prototype.bezierCurveTo;
      CanvasRenderingContext2D.prototype.bezierCurveTo=function(){cap.bz++;};
      try{chart();}finally{CanvasRenderingContext2D.prototype.bezierCurveTo=ob;}
      return cap;}""")
    assert cap["bz"] == 2, "稀疏系列仍画连线（2 点系列 +1 段贝塞尔）: %s" % cap


def test_sparse_series_note_present(pg):
    """ringNote 稀疏注：稀疏系列「仅列点」留痕，注名带系列名。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                + _SPARSE + "chart();")
    note = pg.evaluate("()=>$('ringNote').textContent")
    assert "中转" in note and "仅列点" in note, note


def test_full_series_no_note_and_line_kept(pg):
    """满系列回归：双系列 ≥3 点时连线保留、稀疏注不在场。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                "const cr=curRoute();cr.range='48h';cr.r.history="
                "{direct:[['10-01 08:00',1000,0],['10-01 20:00',1010,0],"
                "['10-02 08:00',1020,0]],"
                "transfer:[['10-01 12:00',900,0],['10-01 20:00',930,0],"
                "['10-02 08:00',950,0]]};cr.r.th={direct:800,transfer:800};"
                "chart();")
    cap = pg.evaluate("""()=>{const cap={bz:0};
      const ob=CanvasRenderingContext2D.prototype.bezierCurveTo;
      CanvasRenderingContext2D.prototype.bezierCurveTo=function(){cap.bz++;};
      try{chart();}finally{CanvasRenderingContext2D.prototype.bezierCurveTo=ob;}
      return cap;}""")
    note = pg.evaluate("()=>$('ringNote').textContent")
    assert cap["bz"] == 4, cap          # 双系列各 2 段
    assert "仅列点" not in note, note


# ---- W-3：非 JSON 响应体词面归「服务异常」档 ----

def test_nonjson_body_reports_svc_error(pg):
    """502 HTML 响应体（冷启动 S=null 形态=缺陷真面）：服务应答了——
    词面必须落「服务异常」档，不得误报「服务未启动」（有旧数据时
    既有 catch 分支已报服务异常，本钉锁冷启动面）。"""
    pg.route("**/api/state", lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body>502 Bad Gateway</body></html>"))
    try:
        pg.evaluate("async()=>{S=null;LASTTXT='';_markStale();await load();}")
        st = pg.evaluate(
            "()=>({pill:$('pill').textContent,up:$('updated').textContent,"
            "tbl:$('ftable').textContent})")
        assert "服务异常" in st["pill"], st
        assert "服务未启动" not in st["pill"], st
        assert "服务未启动" not in st["up"], st
        assert "服务未启动" not in st["tbl"], "非 JSON 体不应按网络不可达落词面"
    finally:
        pg.unroute("**/api/state")


def test_nonjson_failure_recovery_round(pg):
    """失败体不入签名：冷启动非 JSON 失败后下一拍真实数据必须被处理
    （恢复轮同文本不被跳过——LESSONS 二十三§3 签名失效律）。"""
    pg.route("**/api/state", lambda r: r.fulfill(
        status=200, content_type="text/html", body="gateway timeout"))
    try:
        pg.evaluate("async()=>{S=null;LASTTXT='';await load();}")
    finally:
        pg.unroute("**/api/state")
    pg.evaluate("async()=>{await load();}")
    pill = pg.evaluate("()=>$('pill').textContent")
    assert "服务异常" not in pill and "服务未启动" not in pill, pill


# ---- W-4：配置页分区编号色统一 ----

def test_grouplab_no_color_unified():
    """源码钉：.grouplab .no 装饰蓝收 --mut（与监控页 .seclab .no
    同语义同谱；蓝只用于交互/数据锚点）。"""
    p = _page_src()
    assert re.search(r"\.grouplab \.no\{[^}]*color:var\(--mut\)", p), \
        "配置页分区编号仍用装饰蓝"
    assert re.search(r"\.seclab \.no\{[^}]*color:var\(--mut\)", p), \
        "监控页分区编号锚（同谱基准）"
