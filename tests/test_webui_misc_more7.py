# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r244_webui.py
- tests/test_v15131_webui.py
- tests/test_v199_webui.py
- tests/test_v200_webui.py
- tests/test_v295_tokens.py
- tests/test_v299_state_ui.py
- tests/test_v302_ui_consistency.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src
import io

import inspect
import os
import pytest
import re
import socket
import subprocess
import sys
import time
import urllib.request
import webui


# ---- merged from tests/test_r244_webui.py ----

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 现取空闲端口：固定 8798 与 r330 同口，并发全量必抢
PORT = None
BASE = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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






# ---- W-1：移动首屏数据上移 ----





# ---- W-2：稀疏系列只画点不连线 ----

# r244b：数据必须用**真实形态**——航线图按 2h 分桶（48h→BUCKET=120min），
# 缺口下限是 120×1.2=144min。旧样例直飞每 12h 一点（720min > 144），
# 在分桶语义下**本来就是真断档**，断言「3 点必连线」与实际设计冲突，
# 误报成「线没画出来」。真实数据是每 2h 一个点，故直飞给 25 点、
# 中转保持 2 点（稀疏系列的原始意图不变）。
_MK = "window._mk=(n,base)=>{const a=[];for(let i=0;i<n;i++){const d=new Date(Date.UTC(2026,9,1,0,0,0)+i*2*3600e3);const p=x=>String(x).padStart(2,'0');a.push([p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':00',base+i,0]);}return a;};"
_SPARSE = ("const cr=curRoute();cr.range='48h';"
           + _MK + 
           # 中转价位必须落在直飞的价格窗内：原先用 900/950，比直飞
           # 1000 低太多，被 _keep 的异常价过滤整段剔除（_outHidden+2），
           # ht 变空 → 稀疏注不出现，测试误判成「注丢了」。
           "cr.r.history={direct:window._mk(25,1000),"
           "transfer:[['10-02 04:00',1005,0],['10-02 08:00',1010,0]]};"
           "cr.r.th={direct:800,transfer:800};")








# ---- W-3：非 JSON 响应体词面归「服务异常」档 ----





# ---- W-4：配置页分区编号色统一 ----

def test_grouplab_no_color_unified():
    """源码钉：.grouplab .no 装饰蓝收 --mut（与监控页 .seclab .no
    同语义同谱；蓝只用于交互/数据锚点）。"""
    p = _page_src()
    assert re.search(r"\.grouplab \.no\{[^}]*color:var\(--mut\)", p), \
        "配置页分区编号仍用装饰蓝"
    assert re.search(r"\.seclab \.no\{[^}]*color:var\(--mut\)", p), \
        "监控页分区编号锚（同谱基准）"


# ---- merged from tests/test_v15131_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


def test_canvas_mintag_orange_uses_text_token():
    s = src()
    assert "(cssv('--orange-txt')||'#a45508')" in s, \
        "canvas「低」标注橙支路未消费文字级令牌（图形档 3.78 欠 AA）"


def test_canvas_mintag_text_token_exactly_two_modes():
    body = re.search(r"const chartDraw=", src())
    assert body, "chartDraw 不在源码"
    seg = src()[body.start():body.start() + 30000]
    assert seg.count("cssv('--orange-txt')") == 2, \
        "折线/K线两模式「低」标注橙支路须恰两处挂文字级令牌（计数钉）"


# ---- merged from tests/test_v199_webui.py ----

def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


class TestMarkMinEscapeRows:
    """P1-1：标注互避算法候选表含错行出口，横向判定外扩。"""

    def test_escape_rows_present(self):
        src = _src()
        m = re.search(r"const markMin=\(pts,color,bandY\)=>\{.*?"
                      r"markMin\(HPTS\.d[^\n]*\);", src, re.S)
        assert m, "markMin 函数锚丢失（应带 bandY 专属带参）"
        seg = m.group(0)
        assert "for(const dy of [-10,16,42])" in seg, "近点行缺第三档错行出口"
        assert "cands.push([x+dx,bandY])" in seg, "顶带候选未改专属带形态"
        assert ",T+12);" in seg and ",T+44);" in seg, "双系列异带实参缺"

    def test_overlap_margin_expanded(self):
        src = _src()
        assert "!(cx+tagW+6<b[0]||b[2]<cx-6||cy+4<b[1]||b[3]<cy-12)" in src, \
            "互叠判定未横向外扩 6px（同带贴邻漏罚）"

    def test_clamp_bottom_is_plot_bottom(self):
        """钳位下界=H-B-6（B 是底边距非底坐标——旧 B-6 在高画布把
        全部候选钳进顶部 20px 窄带=同带互叠真根因）。"""
        src = _src()
        assert "const cy=Math.min(Math.max(c[1],T+12),H-B-6);" in src, \
            "标注 y 钳位仍用 B-6（边距当坐标）"


class TestScrollPaddingMidBand:
    """P2-1：761-900 带锚点滚动补偿。"""

    def test_900_band_declared_after_base(self):
        src = _src()
        base = src.index("html{scroll-padding-top:72px")
        i900 = src.rindex(
            "@media(max-width:900px){html{scroll-padding-top:"
            "calc(var(--hdh,54px) + 34px)}}")
        assert base < i900, "≤900 补偿块未置尾（层叠被基础块反杀）"


class TestSetFltOpenSingleSource:
    """P2-2：抽屉开合三口单源。"""

    def test_helper_and_three_callers(self):
        src = _src()
        assert "function setFltOpen(open){" in src
        m = re.search(r"function togFlt\(\)\{[^}]*setFltOpen\(", src, re.S)
        assert m, "togFlt 未走 setFltOpen"
        # r302 W4：Esc 收抽屉前焦点归还 fltBtn（closePv 先例同款，
        # contains 守卫防误移）——裸关闭形态（焦点坠 body）禁复活
        assert ("if(fb){const _ff=document.activeElement;"
                in src), "Esc 旁路焦点归还缺失"
        assert re.search(
            r"if\(fb\)\{const _ff=document\.activeElement;\s*"
            r"if\(_ff&&fb\.contains\(_ff\)&&\$\('fltBtn'\)\)"
            r"\$\('fltBtn'\)\.focus\(\);\s*setFltOpen\(false\);return;\}", src), \
            "Esc 旁路收口形态漂移"
        assert "getComputedStyle(fb).display==='none')setFltOpen(true)" in src, \
            "`/` 旁路未收口"
        # 旁路直改 .fbar 开合清零：抽屉开合只经 setFltOpen 的
        # toggle('open',open) 单源（fb 语境的 add/remove 直改必红；
        # .chev 折叠组件同名类不在此守卫面）
        scripts = "".join(re.findall(r"<script>(.*?)</script>", src, re.S))
        assert "fb.classList.add('open')" not in scripts, \
            "旁路直改 .fbar 开合残留（绕过 setFltOpen 单源）"
        assert "fb.classList.remove('open')" not in scripts, \
            "旁路直改 .fbar 开合残留（绕过 setFltOpen 单源）"
        assert "classList.toggle('open',open)" in src


class TestCfgMultiControlAria:
    """P2-3：配置页行内全量控件挂 aria-label。"""

    def test_query_selector_all_with_suffix(self):
        src = _src()
        m = re.search(r"querySelectorAll\('\.srow,\.glcell'\)\.forEach"
                      r"\(r=>\{.*?inps\.forEach", src, re.S)
        assert m, "配置行 aria 后处理未改全量控件形态"
        assert "querySelectorAll('input,select')" in src, "仍取单控件"
        assert "inps.length>1?' '+(i+1):''" in src, "多控件缺序号后缀"


class TestTabsCfgnavAriaPressed:
    """P2-4：#tabs/#cfgnav 选中态 aria-pressed。"""

    def test_sync_in_tabaria_and_switch_points(self):
        src = _src()
        seg = src[src.index("function tabAria()"):src.index("/* 选择器说明")]
        assert "aria-pressed" in seg, "tabAria 缺 pressed 尾随同步"
        i = src.index("$('tabs').onclick")
        assert "saveUI();table();tabAria();}" in src[i:i + 300], \
            "#tabs 切换点缺一拍"
        m = re.search(r"function showCfgPanel\(id,silent\)\{.*?aria-pressed",
                      src, re.S)
        assert m, "cfgnav 切换点缺一拍"


class TestMonTabDomOrder:
    """P2-5：明细块先于健康块（键盘 Tab 序=DOM 序对齐视觉 tab 序）。"""

    def test_details_before_health(self):
        src = _src()
        assert src.index('<div id="montab-details"') < \
            src.index('<div id="montab-health"'), \
            "montab 块序未对齐（details 应在前）"


class TestDetailRowRoving:
    """P2-6：明细行首行 0 余 -1 + ↑/↓ 族移动。"""

    def test_row_tabindex_and_arrow_handler(self):
        src = _src()
        assert 'tabindex="${i===0?0:-1}"' in src, "行 tabindex 未改族形态"
        assert "else if(event.key==='ArrowDown'||event.key==='ArrowUp')" \
            in src, "行键盘缺 ↑/↓ 分支"
        assert "_rowRoving(event,this)" in src

    def test_row_roving_helper_scoped(self):
        src = _src()
        m = re.search(r"function _rowRoving\(e,el\)\{.*?\}", src, re.S)
        assert m, "_rowRoving helper 缺失"
        assert "tr[data-k]" in m.group(0), "选择器未限定数据行" \
            "（xrow/tgrow 无 data-k 天然排除）"


class TestPretaxWrapMobile:
    """P2-7：≤760 价格格退改徽标折行。"""

    def test_media_rule_present(self):
        src = _src()
        base = src.index("html{scroll-padding-top:72px")
        i = src.index("#ftable td.price .pretax{display:block;font-size:10px}")
        assert i > base, "≤760 折行规则未置尾（层叠风险）"
        seg = src[src.rindex("@media(max-width:760px)", 0, i):i]
        assert "max-width:760px" in seg


# ---- merged from tests/test_v200_webui.py ----

def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


class TestChheadTouchTarget:
    """P2-1：chhead 折叠头触控热区外扩（::after 族同 .dx/.hc/.tj 先例）。"""

    def test_hotzone_after_present(self):
        src = _src()
        assert ".chhead[role=" in src, "chhead 触控热区规则缺失"
        m = re.search(r"\.chhead\[role=.?button.?\]\{position:relative\}"
                      r"[^\n]*\n[^\n]*\.chhead\[role=.?button.?\]::after"
                      r"\{content:'';position:absolute;inset:[^}]+\}", src)
        assert m, "chhead 热区需 position:relative + ::after inset 外扩成对"

    def test_after_family_block_updated(self):
        """热区族注释块（::after 外扩）应提及 chhead 收编。"""
        src = _src()
        i = src.index("触控热区扩展")
        seg = src[i:i + 2000]
        assert "chhead" in seg, "触控热区扩展块未收编 chhead（清单漂移）"


class TestSrowInputHeight:
    """P2-2：srow 行内输入 coarse 高度 38px，三处触控清单同步。"""

    def test_three_coarse_blocks(self):
        src = _src()
        n = src.count(".srow .sctl input:not(.switch){height:38px}")
        assert n >= 3, f"srow 输入 38px 应在三处触控块各一份（现 {n}）"


class TestMobileCatDateColumns:
    """P2-3：≤760 类别/日期列收进航班格 mmeta。"""

    def test_th_classes_generated(self):
        src = _src()
        assert "k==='cat'?' catt'" in src and "k==='date'?' datd'" in src, \
            "thead 列头未挂 catt/datd 类"

    def test_td_classes_and_mmeta(self):
        src = _src()
        assert '<td class="catt">' in src, "类别 td 未挂 catt"
        assert '<td class="datd">' in src, "日期 td 未挂 datd"
        m = re.search(r'<div class="mmeta">.*?</div>', src, re.S)
        assert m, "航班格 mmeta 预置容器缺失"
        seg = m.group(0)
        assert "t-t" in seg and "t-d" in seg, "mmeta 缺类别 tag 双态"
        assert "mdat" in seg, "mmeta 缺日期小字"

    def test_css_hide_and_show(self):
        src = _src()
        base = src.index("#ftable .mmeta{display:none}")
        i760 = src.rindex("#ftable .mmeta{display:flex")
        assert base < i760, "mmeta 显示块未置尾（层叠被 display:none 反杀）"
        m = re.search(
            r"#ftable th\.catt,#ftable td\.catt,#ftable th\.datd,"
            r"#ftable td\.datd\{display:none\}", src)
        assert m, "≤760 类别/日期列隐藏规则缺失"


class TestXrowWrapMobile:
    """P2-4：xrow 比价链 ≤760 折行（结论句进首屏）。"""

    def test_wrap_rule_after_nowrap_base(self):
        src = _src()
        m = re.search(
            r"#ftable tr\.xrow:not\(\.tgrow\) td\{white-space:normal", src)
        assert m, "xrow ≤760 折行规则缺失"
        # 只认「基础规则是 nowrap」这个意图，不绑死具体 padding 数值：
        # 字号/间距尺度的统一（r473）改过 7px 10px → 8px 12px，
        # 绑死数值会让「折行规则必须在基础规则之后」这条守卫假红。
        base = re.search(
            r"th,td\{[^}]*text-align:left;white-space:nowrap", src)
        assert base, "表格基础规则不再是 nowrap"
        assert base.start() < m.start(), "折行规则须在 nowrap 基础规则之后"

    def test_conclusion_nowrap(self):
        """结论句「（可省 ￥N）/（差…）/（仅一渠道报价）」整体 nowrap——
        折行断点曾把结论腰斩成「￥1)」孤行（决策语义被拆）。"""
        src = _src()
        assert '<span style="white-space:nowrap">（换最低渠道可省 ￥${save}）</span>' in src
        assert 'white-space:nowrap">（本行较最低高 ￥${save}' in src
        assert '<span style="white-space:nowrap">（仅一渠道本轮有价）</span>' in src
        assert '（本行已是同班最低）' in src

    def test_conclusion_before_chain(self):
        """结论句前置于渠道链（真机 390 实测：colspan td 宽=全表宽，
        white-space:normal 只在链长超过全表宽时才折行——三渠道链
        ~470px < 690px 单行放得下，结论句仍藏视口外 ~200px 须横滚；
        前置后结论句恒贴链头（xrow 已退出首列吸附，链头=滚动零位）。"""
        src = _src()
        m = re.search(r"同班比价.{0,600}?\$\{chain\}", src, re.S)
        assert m, "xrow 模板「同班比价…${chain}」结构不在"
        seg = m.group(0)
        assert '<span style="white-space:nowrap">（' in seg, \
            "结论句须前置于渠道链（同班比价 与 ${chain} 之间）"
        assert "同班比价：" not in seg, "旧序「同班比价：链」残留"


class TestScrollPaddingNarrow:
    """P2-5：≤760 档 scroll-padding 三段式动态补偿（390 实测 header
    134px + 吸顶切换器/筛选条双条让位）。"""

    def test_narrow_compensation_is_cascade_winner(self):
        src = _src()
        # ≤760 带内该选择器的层叠胜者=三段式实效档（hdh+mtabsh+tabsh+4
        # 过吸顶三件）；中带 hdh+34 固定系数档已退役（r262，被本档按
        # 源码序覆盖的死代码），复活即回归
        m = re.search(
            r"html\{scroll-padding-top:calc\(var\(--hdh,134px\) \+ var\(--mtabsh\)"
            r" \+ var\(--tabsh,0px\) \+ 4px\)\}",
            src)
        assert m, "窄档动态补偿块缺失"
        assert "hdh,76px) + 34px" not in src, \
            "中带 hdh+34 固定系数档复活（三段式覆盖下的死代码）"


class TestMicroTypography:
    """P2-7：图例括注孤行与配置标题计数断行（nowrap 包裹）。"""

    def test_cal_legend_nowrap(self):
        src = _src()
        assert src.count('<span style="white-space:nowrap">红=超线（格底）</span>') == 2, \
            "图例「红=超线（格底）」须整体 nowrap（stats 版+空态版两处）"

    def test_cfg_title_count_nowrap(self):
        src = _src()
        # r348：重复的「用户与航线配置（N 个用户）」标题条已撤，计数改由
        # 概览卡/用户胶囊承担；工具条动作标签仍须整体 nowrap，不得逐字折行
        assert 'class="rline cfgtoolbar"' in src, "配置工具条缺失"
        i = src.index(".cfgtoolbar-act .btn2{")
        assert "white-space:nowrap" in src[i:i + 220], \
            "配置动作标签须整体 nowrap"


# ---- merged from tests/test_v295_tokens.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_tokens_are_single_sourced():
    """价格三档必须单源定义，且严格递减。

    原断言把 `24/19/16` 写死——并行会话调成 `22/18/16` 后门禁就红，
    但它守的其实是「三档字号只有一个出处、且大>中>小」。
    改为读实际声明值做序关系校验，不再钉死具体像素。
    """
    import re
    src = _src()
    for token in ("--r-card:14px", "--r-container:12px", "--r-ctl:8px"):
        assert token in src, token
    px = {}
    for k in ("--price-lg", "--price-md", "--price-sm"):
        m = re.search(re.escape(k) + r":\s*(\d+)px", src)
        assert m, k + " 未在 :root 单源定义"
        px[k] = int(m.group(1))
    assert px["--price-lg"] > px["--price-md"] > px["--price-sm"] > 0, px
    assert ".ws-card{border-radius:var(--r-card)!important" in src
    assert "#loginRows .lgslot{background:transparent" in src


def test_watch_has_one_visible_title():
    src = _src()
    assert '<h2 class="ws-title" id="wsTitle">关注航班</h2>' not in src
    assert '<h2 class="ws-title sr-only" id="wsTitle">关注航班</h2>' in src
    assert 'aria-labelledby="wsTitle"' not in src


# ---- merged from tests/test_v299_state_ui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_stale_fallback_window_follows_schedule_interval():
    import webui
    old = webui._State.cfg
    try:
        webui._State.cfg = {"schedule": {"interval_minutes": 30}}
        assert webui._state_stale_hours() == 6
        webui._State.cfg = {"schedule": {"interval_minutes": 10080}}
        assert webui._state_stale_hours() == 168
    finally:
        webui._State.cfg = old
    src = _src()
    assert "hours=_state_stale_hours()" in src
    assert "补位窗口随调度周期" in src


def test_login_status_is_a_row_accent_not_a_misaligned_dot():
    src = _src()
    for s in (
        "#loginRows .lgdot{display:none!important}",
        "#loginRows .lgcard{border-left:3px solid var(--r-hair)!important}",
        "#loginRows .lgcard:has(.lgdot.on){border-left-color:var(--r-green)!important}",
        "#loginRows .lgcard:has(.lgdot.stale),#loginRows .lgcard:has(.lgdot.mid){border-left-color:var(--warn)!important}",
    ):
        assert s in src, s


def test_radar_chart_controls_match_trend_chart_capabilities():
    src = _src()
    for s in (
        'id="spMonRange"',
        'data-spmrange="2">48h',
        'data-spmrange="7"',
        'data-spmrange="30"',
        'data-spmrange="90"',
        'data-spmrange="180"',
        'id="spMonMode"',
        'data-spmmode="kline"',
        "function spMonSetRange(",
        "function spMonSetMode(",
        "localStorage.setItem('jpspmrange'",
        "localStorage.setItem('jpspmmode'",
        "K线=",
        "监控快照按日聚合",
        ".spmon-chartwrap{overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;overscroll-behavior-x:contain;touch-action:pan-x;-webkit-overflow-scrolling:touch}",
        "#spMonChart{max-width:none}",
        "const units=SPMON.mode==='kline'?candles.length:times.length",
        # r850：上限改为 60000（原 2.4×可视宽会把密集采样压在同一像素）；
        # 取大结构不变：点数多时可横向滚动，点数少时仍铺满可视宽。
        "const W=Math.max(baseW,Math.min(units*MINPX,",
        "c.style.width=W+'px'",
        "p.p>0&&(!rangeMs||p.t>=cutoff)",
        "[mx>0?Math.max(0,mn-p):mn-p,mx+p]",
        # r374：非聚焦日期线不再用 .55 透明度（叠成浅灰斑，读作白色遮挡），
        # 改中性墨色 + .7 保持层级且可辨。
        "alpha:low||sel?1:.7",
        "if(left<lastR+8)return;",
        "#searchview .srx-src+.srx-src{border-left:1px solid var(--r-hair)!important;",
        "#searchview .srx-capbar{background:transparent!important;border:0!important;",
    ):
        assert s in src, s


# ---- merged from tests/test_v302_ui_consistency.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_radar_hover_tracks_nearest_time_across_plot_width():
    src = _src()
    for s in (
        'id="spMonCross"',
        ".spmon-cross{position:absolute",
        "if(mx<gg.padL||mx>gg.W-gg.padR||my<gg.padT||my>gg.H-gg.padB)",
        # r373：命中按横轴取最近点（X 主键、Y 次键），
        # 二维最近点在曲线稀疏/鼠标离点较远时会漏选；r374 收敛进 PCHART.pick。
        "const d=dx*1000+dy;",
        "const x=$('spMonCross');if(x)x.style.display='none'",
    ):
        assert s in src, s
    assert "d<=441" not in src
    # 十字线左缘＝画布偏移 + 绘图内 x，且两条分支（K 线桶 / 折线）都必须
    # 跟变量而不是常量。变量名随实现变化过（gx → x0/mx），所以这里断
    # 言结构而非名字；负控实测：改成 `cross.style.left='626px'` 必须变红
    # （曾用前缀断言 `offsetLeft+`，常量写法照样通过 → 空转）。
    import re as _re
    _lhs = _re.findall(r"cross\.style\.left=Math\.round\(c\.offsetLeft\+([A-Za-z_$][\w$]*)\)", src)
    assert len(_lhs) >= 2, "十字线定位分支少于 2 处（K 线/折线）：%r" % (_lhs,)
    assert "cross.style.left='" not in src, "十字线位置被写成了常量"


def test_search_kpi_facet_and_date_filters_are_idempotent():
    src = _src()
    for s in (
        "const on=!SRX.f.onlyQual;",
        "SRX.f.missing=!SRX.f.missing",
        "const same=Array.isArray(cur)?false:(String(cur)===''?false:String(cur)===String(v));",
        "SRX.date=(dv&&SRX.date===dv)?'':dv;",
        "SRX.f[k]=Array.isArray(SRX_DEFAULT_F[k])?[]:(typeof SRX_DEFAULT_F[k]==='boolean'?false:'')",
        "background:var(--r-blue-soft)!important;box-shadow:inset 0 -2px 0 var(--r-blue)!important",
    ):
        assert s in src, s


def test_search_header_is_compact_and_source_strip_is_a_table():
    src = _src()
    for s in (
        '<div class="srx-hero-copy" id="srxHeroCopy">',
        "let po='1';try{po=localStorage.getItem('jpsrx_probeopen2')||'1'}",
        "#searchview .srx-capbar{display:flex!important;background:transparent!important;border:0!important;",
        "#searchview .srx-probe:not(.open) .srx-probeacts>*:not(.srx-probe-toggle){display:none!important}",
        "#searchview .srx-kpi{display:inline-flex!important",
        "#searchview .srx-src+.srx-src{border-left:1px solid var(--r-hair)!important",
        "grid-auto-flow:column!important",
        "#searchview .srx-src-a{display:none!important}",
    ):
        assert s in src, s


def test_watch_uses_the_same_compact_summary_and_no_duplicate_routewatch():
    src = _src()
    for s in (
        "#montab-watch .ws-kpi{flex:1 1 0!important",
        "#montab-watch .ws-kpi .f{display:none!important}",
        "#montab-watch .ws-routewatch{display:none!important}",
        # r374：三处走势画布统一 240（原独立 200/178，同一产品三种高度）
        "#montab-watch .ws-chartwrap{height:clamp(240px,max(38vh,28vw),360px)!important;min-height:160px!important}",
        "#montab-watch .ws-route{min-height:44px!important",
    ):
        assert s in src, s


def test_search_overview_summary_bar_is_desktop_only_and_collapsible():
    """r374：概览收成「标题行摘要 + 唯一开合钮 + 正文」一个区块。

    窄屏不再用 show-overview 第二套开关（两套状态必然漂移），
    移动栏「概览」改为调同一个 srxToggleOverview，正文由
    srx-ov-collapsed 单点控制显隐。
    """
    src = _src()
    for s in (
        'id="srxOvSum"',
        'id="srxOvHero"',
        "function srxRenderOv()",
        "function srxToggleOverview()",
        # r433：概览开合只管自己。原先这里还写 localStorage 记「上次是否收起」，
        # 但全仓没有任何读取方（每次加载都从默认态起），是一次空写入；
        # 更关键的是同函数里还调 srxRenderCtx()，开合概览会连带重算下方
        # 筛选区的折叠态——保留这条断言守的是「互不越权」而不是持久化。
        "const on=v.classList.contains('srx-ov-collapsed')",
        # 2026-10-31：价带改为可选——收起整条（不再保留 46px 标题行），
        # 入口移到工具区 #srxOvTool，与价带内触发器共用 srxToggleOverview。
        "#searchview.srx-ov-collapsed #srxOverview{display:none!important}",
        'id="srxOvTool"',
        # 内层四条作为双保险仍在（防止只改了外层、内层漏出正文）
        "#searchview.srx-ov-collapsed #srxBandBody,",
        "hb.textContent=on?'收起概览':'展开概览'",
        "#searchview #srxOvSum{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis",
    ):
        assert s in src, s
    # 第二套窄屏开关必须彻底退场
    assert "show-overview" not in src


def test_mobile_search_toolbar_is_one_scrollable_row_not_a_two_column_grid():
    src = _src()
    for s in (
        "@media(max-width:560px){\n #searchview .srx-hero{padding:2px 2px 4px!important",
        "#searchview .srx-hero-act{display:flex!important;grid-template-columns:none!important;flex-wrap:nowrap!important",
        "#searchview .srx-hero-act:not(.open) .srx-btn[data-sec].srx-keep{display:none!important}",
        "#searchview .srx-hero-act.open .srx-btn.srx-keep[data-sec]{display:inline-flex!important}",
        "@media(max-width:360px){",
    ):
        assert s in src, s


def test_mobile_watch_gives_first_screen_to_the_chart_and_empty_filter_bar_stays_hidden():
    src = _src()
    for s in (
        "#montab-watch .ws-sub{display:none!important}",
        "#montab-watch .ws-routebar-h{display:none!important}",
        "#montab-watch .ws-chart-foot{display:none!important}",
        "if(!head&&!chips){el.innerHTML='';return}",
    ):
        assert s in src, s


def test_narrow_watch_kpi_values_never_wrap():
    """320 档四格 KPI 值必须单行：守 nowrap、单位不参与收缩、字号低于桌面三条。

    原断言把 15px 写死；字号阶统一后该档随七阶走 16px。
    nowrap 只写容器还不够——单位 `<span>` 是 flex 子项，被压窄后在内部
    折行（实测 320 档「3.5 /」+「5」两行、单元格 18→30px），所以
    `flex:none` 也是本契约的一部分。
    """
    import re
    src = _src()
    m = re.search(r"#montab-watch \.ws-kpi \.v\{font-size:(\d+)px!important;white-space:nowrap!important\}", src)
    assert m, "320 档关注 KPI 值缺 nowrap 单行钉"
    assert int(m.group(1)) < 18, "320 档 KPI 字号 %spx 未小于桌面 18px，四格会挤行" % m.group(1)
    assert "#montab-watch .ws-kpi .v span{flex:none!important}" in src, \
        "320 档 KPI 单位必须 flex:none，否则「3.5 / 5」仍折成两行"
