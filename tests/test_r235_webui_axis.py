# -*- coding: utf-8 -*-
"""走势图共享时间轴（r235 UI P1-1）：X 坐标原为纯索引式 i/(N-1)
（N=双系列点数最大值），某系列因「宁漏不虚报」过滤变稀疏（仅窗尾
2 点）时整条系列被压到画布左缘，且 hover/键盘按同索引取两系列跨
时刻错配读数。修复语义：双系列全部时刻排序去重建轴，每点按自身
时刻落位；钉面用真实渲染管线（demo 实例 + chart() + HPTS 像素
坐标），稀疏系列点必须落在其时刻对应的轴位（右带）而非索引位
（左缘）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r235_webui_axis.py -q
"""
import os
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8797
BASE = "http://127.0.0.1:%d" % PORT


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
    # CI 缺 chromium 二进制（playwright 包装了但没 install 浏览器）：
    # importorskip 防不住「包在二进制缺」形态，launch 探测缺则 SKIP
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


# 样本：直飞 3 点（窗头→窗中→窗尾），中转 2 点仅在窗尾。
# 时刻并集 5 个：中转首点 '10-02 04:00' 的轴位 = 3/4（右带），
# 索引式旧码会把它画在 i=0/(N-1)=0（左缘）。
_SPARSE = ("const cr=curRoute();cr.range='48h';cr.r.history="
           "{direct:[['10-01 08:00',1000,0],['10-01 20:00',1010,0],"
           "['10-02 08:00',1020,0]],"
           "transfer:[['10-02 04:00',900,0],['10-02 08:00',950,0]]};"
           "cr.r.th={direct:800,transfer:800};")


def test_sparse_transfer_series_lands_on_time_axis(pg):
    """折线：稀疏中转系列按自身时刻落右带，不再压左缘。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                + _SPARSE + "chart();")
    h = pg.evaluate("()=>({d:HPTS.d,t:HPTS.t,N:HPTS.N,L:HPTS.L,Rx:HPTS.Rx})")
    assert h["N"] == 4, "共享轴点数=双系列时刻并集(10-02 08:00 共享)"
    band = h["L"] + (h["Rx"] - h["L"]) * 0.6
    assert h["t"], "中转点在场"
    for pt in h["t"]:
        assert pt[0] > band, "稀疏系列点压左缘（索引位而非时刻位）: %s" % h
    # 中转首点 '10-02 04:00' 的轴位=2/3，落在右带精确位（旧码压左缘 0）
    exact = h["L"] + (h["Rx"] - h["L"]) * (2.0 / 3)
    assert abs(h["t"][0][0] - exact) < 2.0, h
    # 直飞首点仍在窗头（同一映射对满系列无回归）
    assert h["d"][0][0] < h["L"] + (h["Rx"] - h["L"]) * 0.2
    # 同刻对齐：直飞末点与中转末点同在 '10-02 08:00'，x 必须相等
    assert abs(h["d"][-1][0] - h["t"][-1][0]) < 0.5


def test_kline_buckets_carry_axis_index(pg):
    """K线：桶带 _ax 轴索引（hover 按轴位反查），稀疏中转簇锚窗尾。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('kline');"
                + _SPARSE + "chart();")
    k = pg.evaluate("()=>({axd:HPTS.cd.map(c=>c._ax),"
                    "axt:HPTS.ct.map(c=>c._ax),N:HPTS.N})")
    assert k["N"] == 4
    assert all(isinstance(a, int) for a in k["axd"] + k["axt"]), k
    assert sorted(k["axd"]) == [0, 1, 3], k
    assert sorted(k["axt"]) == [2, 3], k
    assert min(k["axt"]) > min(k["axd"]), "中转簇轴位靠后（窗尾）"


def test_hover_crosshair_reads_both_series_at_own_time(pg):
    """hover 十字线：十字落在中转首点轴位（'10-02 04:00'），读数只含
    中转——直飞该时刻无点，不得按同索引错配直飞邻近点（旧码在左缘
    读出直飞窗头价=时刻+档位双重误读）。钩 fillText 抓 tooltip 文本。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                + _SPARSE + "chart();")
    xt = pg.evaluate("()=>HPTS.t[0][0]")   # 中转首点像素 x（轴位 3/4）
    txts = pg.evaluate(
        """(x)=>{const cap=[];
        const orig=CanvasRenderingContext2D.prototype.fillText;
        CanvasRenderingContext2D.prototype.fillText=function(s){cap.push(String(s));};
        try{drawHover(x);}finally{
        CanvasRenderingContext2D.prototype.fillText=orig;}
        return cap.join('｜');}""", xt)
    assert "中转最低" in txts, txts
    assert "直飞最低" not in txts, "同索引错配直飞邻近点: " + txts


def test_empty_series_hides_legend_and_cluster_note(pg):
    """图例-数据一致性（r235 P2-1 数据维度）：中转 0 点时「中转最低」
    色票隐藏、K线单簇时簇位句不提「右簇」；恢复条件=chart() 每次重算
    无条件重写（满系列样本色票回场）。"""
    # 空中转系列 → lgTrans 隐藏
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                "const cr=curRoute();cr.range='48h';cr.r.history="
                "{direct:[['10-01 08:00',1000,0],['10-02 08:00',1010,0]],"
                "transfer:[]};cr.r.th={direct:800,transfer:800};chart();")
    st = pg.evaluate(
        "()=>({t:$('lgTrans').style.display,d:$('lgDirect').style.display,"
        "note:$('ringNote').textContent})")
    assert st["t"] == "none", st
    assert st["d"] == "", "满系列色票应回场"
    # K线单簇 → 簇位句无「右簇」
    pg.evaluate("setMode('kline');")
    note = pg.evaluate("()=>$('ringNote').textContent")
    assert "右簇" not in note, note
    # 双簇样本 → 簇位句回场
    pg.evaluate("const cr2=curRoute();cr2.r.history.transfer="
                "[['10-02 04:00',900,0],['10-02 08:00',950,0]];chart();")
    note2 = pg.evaluate("()=>$('ringNote').textContent")
    assert "左簇=直飞 · 右簇=中转" in note2, note2


def test_shared_axis_year_boundary_order(pg):
    """跨年窗时间轴（Soldier P1-1）：时刻串「MM-DD HH:MM」无年份，
    字典序排序在 12-31→01-01 窗把新年排前=整轴时间流向反转。
    直调排序键 axTKey（nowMs 参数注入，免环境 mock）断言时间序；
    并以源码钉锁 tset 排序消费。"""
    r = pg.evaluate(
        """(()=>{const now=new Date('2027-01-02T10:00:00').getTime();
        const ka=axTKey('12-31 23:00',now),kb=axTKey('01-01 08:00',now);
        const naive=['12-31 23:00','01-01 08:00'].sort()[0];
        return {ka,kb,naive,
                cmp:ka<kb?-1:(ka>kb?1:0)};})()""")
    # 时间序：去年 12-31 键 < 今年 01-01 键（字典序旧码 naive 排前 01-01）
    assert r["cmp"] < 0, f"跨年窗时间轴反向: {r}"
    assert r["naive"].startswith("01-01"), "钉面前提：字典序确把 01-01 排前"


def test_tset_sort_consumes_axtkey():
    """消费点锁（变异验证补钉）：直调钉只证排序键函数正确，
    tset 排序必须真实消费 axTKey——还原字典序变异时本钉红。"""
    import os as _os
    import pathlib as _pl
    src = _pl.Path(_os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "webui.py")).read_text(encoding="utf-8")
    assert "axTKey(a,Date.now())" in src and "axTKey(b,Date.now())" in src,         "tset 排序未消费跨年感知排序键"


def test_hover_crosshair_vline_reaches_plot_bottom(pg):
    """r242 P2-1 十字线纵轴残段：HPTS 曾把底边距 B(52)当底坐标存，
    lineTo(ax,HPTS.B) 只画到 y=52——绘图区底在 H-B（demo 实测画布
    H=358、底 306），竖参考线 254px 行程只剩 38px 残段且大半被
    tooltip 覆盖。修复=两处 B:B→B:H-B（T/B 成对还原坐标语义）；
    本钉钩 lineTo 断言纵线终点达绘图区底（既有 fillText 钉锁不到
    线体几何——canvas 几何盲区家族，LESSONS 四§6）。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('line');"
                + _SPARSE + "chart();")
    xt = pg.evaluate("()=>HPTS.t[0][0]")
    cap = pg.evaluate(
        """(x)=>{const cap={ln:[],ch:0,x0:null};
        const ol=CanvasRenderingContext2D.prototype.lineTo;
        CanvasRenderingContext2D.prototype.lineTo=function(a,b){
            cap.ln.push([a,b]);cap.ch=this.canvas.offsetHeight;
            if(cap.x0===null)cap.x0=a;};
        try{drawHover(x);}finally{
        CanvasRenderingContext2D.prototype.lineTo=ol;}
        return cap;}""", xt)
    assert cap["ln"], cap
    # 纵参考线是 drawHover 唯一线体：终点 y 必须达绘图区底 H-B（B=52）
    y_end = max(p[1] for p in cap["ln"])
    assert y_end >= cap["ch"] - 52 - 2, (
        f"纵线止于 {y_end}, 绘图区底 {cap['ch'] - 52}", cap)


def test_hover_crosshair_vline_kline_same_geometry(pg):
    """K 线分支同律（r242 Soldier 观察-1）：HPTS B:H-B 与折线同形
    改动、竖线消费点共用 drawHover 管线尾段——折线单边锁不住
    K 线回归面。x=HPTS.L 命中轴位 0 桶（cd[0] _ax=0 恒在）。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setMode('kline');"
                + _SPARSE + "chart();")
    cap = pg.evaluate(
        """(x)=>{const cap={ln:[],ch:0};
        const ol=CanvasRenderingContext2D.prototype.lineTo;
        CanvasRenderingContext2D.prototype.lineTo=function(a,b){
            cap.ln.push([a,b]);cap.ch=this.canvas.offsetHeight;};
        try{drawHover(x);}finally{
        CanvasRenderingContext2D.prototype.lineTo=ol;}
        return cap;}""", pg.evaluate("()=>HPTS.L"))
    assert cap["ln"], cap
    y_end = max(p[1] for p in cap["ln"])
    assert y_end >= cap["ch"] - 52 - 2, (
        f"K线纵线止于 {y_end}, 绘图区底 {cap['ch'] - 52}", cap)
