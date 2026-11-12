# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r236_webui.py
- tests/test_r241_webui.py
- tests/test_r273_webui.py
- tests/test_r274_webui.py
- tests/test_r288_webui.py
- tests/test_r312_webui.py
- tests/test_r314_webui_polish.py
- tests/test_r323_trend_source.py
- tests/test_r339j_duration.py
- tests/test_r368_cancel_isolation.py
- tests/test_r491_front_back_field_alignment.py
- tests/test_r495_trace_request_url.py
- tests/test_r516_all_red_distinguishes_stalled.py
- tests/test_r600_proxy_map_configurable.py
- tests/test_r699_overview_collapse_really_collapses.py
- tests/test_v15110_webui.py
- tests/test_v15111_webui.py
- tests/test_v15113_webui.py
- tests/test_v15130_webui.py
- tests/test_v15132_webui.py
- tests/test_v168_webui.py
- tests/test_v170_webui.py
- tests/test_v172_webui.py
- tests/test_v174_webui.py
- tests/test_v176_webui.py
- tests/test_v184_webui.py
- tests/test_v192_webui.py
- tests/test_v284_fliggy_intl.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import crawlers
import inspect
import io
import json
import logging
import main
import os
import pathlib
import pytest
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import webui

from contextlib import redirect_stderr
from core import demo as demo_mod
from core.models import FlightPrice
from core.pacing import advise
from core.storage import PriceStorage
from crawlers.base import BaseCrawler
from crawlers.fliggy import FliggyCrawler
from datetime import date, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace


# ---- merged from tests/test_r236_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_canvas_height_max_semantics():
    """P1-1：高度式 min→max——宽短带（28vw>38vh）真正抬升，窄高窗
    复原 38vh 既有几何；min 旧式不得残留。"""
    src = _src()
    assert "clamp(240px,max(38vh,28vw),360px)" in src, \
        "canvas 高度式未按 max 语义重落"
    assert "min(38vh,28vw)" not in src, "min 旧式残留（对目标带零实效）"


def test_loadcfg_failure_lands_in_cfgglobals():
    """P2-1：loadCfg 失败分支必须改写 #cfgglobals 静态「加载中…」
    （catch 原只写 cfgmsg+toast，面板骨架永不到达）。"""
    src = _src()
    assert "cfgErr('配置读取失败: '+e)" in src, "loadCfg catch 锚点易位"
    assert "_cg=$('cfgglobals')" in src, "catch 未补 cfgglobals 错误态落点"


def test_demo_wording_health_source():
    """P3-1a：健康卡数据来源词面随 s.demo 切换（demo=合成数据）。"""
    src = _src()
    assert 'id="hsrcNote"' in src, "健康卡来源词面未提为 JS 可切节点"
    assert "s.demo?'演示合成数据':'解析自 monitor.log'" in src


def test_demo_wording_pvfoot_log():
    """P3-1b：轮日志弹层脚注 demo 分支（demo 无 logs/monitor.log）。"""
    src = _src()
    assert "(S&&S.demo)?'演示模式 · 合成轮日志回放'" in src


def test_demo_wording_pvfoot_push():
    """P3-1c：推送记录弹层脚注 demo 分支（demo 无本地存档）。"""
    src = _src()
    assert "(S&&S.demo)?'演示模式 · 合成推送记录回放'" in src


def test_montabs_aria_controls_tabpanel():
    """P3-3 退役改写（r275）：#montabs 混入多租户切换 chip（非 tab
    子件）后按 #tabs 同律降 button 形态——tab↔tabpanel 引用关联随
    tablist 形制退役（禁复活）；面板侧 role=tabpanel 静态在位与
    aria-label 可访问名回写保留（实效档）。"""
    src = _src()
    assert "setAttribute('aria-controls','montab-'" not in src, \
        "tab↔tabpanel 引用关联复活"
    assert src.count('role="tabpanel"') == 9, \
        "tabpanel 数量=%d 应为 9（原 4 + r345 双面板 + r352 关注航班 + r357 详情页签 + 特价雷达）" % src.count('role="tabpanel"')
    assert "PNAME" in src and "montab-'" in src, \
        "面板 aria-label 回写缺席"


# ---- merged from tests/test_r241_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _block_from(src, gate_i):
    """从 gate_i 起按 brace 配对取完整规则块。"""
    j = src.index("{", gate_i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[gate_i:k + 1]
    raise AssertionError("block not closed at %d" % gate_i)


# ---- P2-1 NOTIFY @手机高亮令牌双谱 ----

def test_p2_1_notify_at_tokens_dual_theme():
    src = webui.NOTIFY_PAGE
    # 亮色 :root 令牌，与主站 :80 逐字同值
    assert "--at-bg:#ffd24d;--at-fg:#7a4b00" in src
    # 两个暗色块成对换谱，与主站 :121 逐字同值
    assert src.count("--at-bg:rgba(255,210,77,.16);--at-fg:#ffd24d") == 2
    # 渲染改 class 形态，硬编码内联残留清零
    assert 'class="md-at"' in src
    assert 'style="background:#ffd24d' not in src
    # 页内自有消费规则（令牌消费，双主题自动换谱）
    assert ".md-at{background:var(--at-bg);color:var(--at-fg)" in src


# ---- P2-1b setFltOpen 顶拉 assist 媒体门随形制扩带（Soldier P2-1） ----

def test_p2_1b_flt_drawer_assist_gate_matches_band():
    src = webui.PAGE
    # 抽屉在流展开形制（.fbar.open display:block）是 ≤760 全带；
    # setFltOpen 顶拉 assist 媒体门须与形制同域——540 旧门下新带
    # 深滚点筛选=「按钮无响应」机制复活（滚动锚定病灶同 ≤540 立案）
    i = src.index("function setFltOpen")
    seg = src[i:i + 900]
    assert "window.innerWidth<=760" in seg
    assert "window.innerWidth<=540" not in seg


# ---- P2-2 541-760 明细筛选条吸顶对 + 落点补偿过吸顶三件 ----

def test_p2_2_band_541_760_tabs_sticky_pair():
    src = webui.PAGE
    # 541-760 带块=首个 --mtabsh:52px 定义所在块（≤540 块在源码更后）
    i = src.index(":root{--mtabsh:52px}")
    gate_i = src.rindex("@media(min-width:541px) and (max-width:760px)", 0, i)
    blk = _block_from(src, gate_i)
    # 吸顶对同构 ≤540：筛选条 sticky 贴切换器底（双条贴合无透缝）
    assert "#montab-details .tabs{position:sticky;" in blk
    assert "top:calc(var(--hdh,76px) + var(--mtabsh))" in blk
    # 单行化：类别片 nowrap 横滚 + 图例隐藏（语义并入 fltBtn title，
    # ≤540 同律——该档 .tabs 恒为吸顶条无非吸顶位）
    assert ("#montab-details .tabs span{flex:0 0 auto;white-space:nowrap}"
            in blk)
    assert "#montab-details .tabs>b.muted{display:none}" in blk
    # 切换器实高就位（--mtabsh 从纯补偿变量变为几何变量）
    assert "height:var(--mtabsh)" in blk


def test_p2_2_xhint_family_gate_covers_760():
    src = webui.PAGE
    # 横滚暗示族 + fltBtn sticky 右缘块的媒体门随横滚形制扩带
    # （横滚形制现存在于 ≤760 两带，≤540 独占前提随之退役）
    i = src.index("#montab-details .tabs::after{content:''")
    gate_i = src.rindex("@media(max-width:", 0, i)
    gate = src[gate_i:src.index(")", gate_i) + 1]
    assert gate == "@media(max-width:760px)", gate


def test_p2_2_scroll_padding_clears_sticky_stack():
    src = webui.PAGE
    # 两处活跃 scroll-padding 补偿均含筛选条高项（JS 失效 0px 兜底
    # 回落原值零退化）；761+ 各带无吸顶筛选条，公式不受扰
    assert src.count("calc(var(--hdh,134px) + var(--mtabsh) "
                     "+ var(--tabsh,0px) + 4px)") == 2
    # 观察器把筛选条实高写进变量（--hdh 同律动态单源；
    # 非明细视图条隐藏 offsetHeight=0，补偿自动降档）
    assert "setProperty('--tabsh'" in src


# ---- merged from tests/test_r273_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE = webui.PAGE
NPAGE = webui.NOTIFY_PAGE


def _block(start_anchor, end_anchor):
    m = PAGE.index(start_anchor)
    return PAGE[m:PAGE.index(end_anchor, m + 10)]


# ---------- K1: K 线环标双端钳位 ----------

def test_kline_ring_center_clamped():
    body = _block("const ringK=", "ringK(CD,")
    assert "const cx=Math.max(L+cw/2,Math.min(W-R-cw/2,X(xf(i))+off));" \
        in body, "ringK 缺烛体同款双端钳位：末桶环心越绘图区半截环贴边"
    assert "fallMark(cx,Y(c.l))" in body, "回落标中心未走钳位 cx"
    assert "arc(cx,Y(rp)" in body, "档位环中心未走钳位 cx"
    # 禁复活：环/回落标不得再出现未钳位中心
    assert "arc(X(xf(i))+off" not in body, "档位环退回未钳位中心"
    assert "fallMark(X(xf(i))+off" not in body, "回落标退回未钳位中心"


# ---------- K2: 链接族基态去下划线 ----------

def test_link_underline_base_states():
    assert ".verbar a{color:#8a1f1f;font-weight:700;text-decoration:none}" \
        in PAGE, "verbar 链接缺基态去下划线"
    assert (".kpisum a{position:relative;padding:12px 4px;margin:0 -4px;"
            "text-decoration:none}") in PAGE, "kpisum 链接缺基态去下划线"
    assert "#foot a,.demoBar a{text-decoration:none}" in PAGE, \
        "页脚/演示条链接缺基态去下划线"
    # hover 显形档三处仍在（基态收口不得吞掉可供性反馈）
    assert PAGE.count("a:hover{text-decoration:underline}") >= 3


# ---------- K3: 字距三档单源 ----------

def test_letter_spacing_tokens():
    assert "--ls05:.5px" in PAGE, "--ls05 半像素档令牌缺席"
    assert PAGE.count("letter-spacing:var(--ls05)") == 10, \
        "半像素档消费点应恰 10 处（r352 关注台/试看条 +2，r420 节流小节标题/复发表头 +2）" \
        "（.seclab .zh/.tag/.pseclab/.rtcode + r325 .rintl 国际徽标 + R15 .rrt 往返徽标）"
    assert PAGE.count("letter-spacing:var(--ls2)") == 3, \
        "主站两像素档消费点应恰 3 处（.seclab .en/.grouplab .en/15px 展示签）"
    assert NPAGE.count("letter-spacing:var(--ls2)") == 1, \
        "NOTIFY 轻页 15px 展示签消费恰 1 处（:root 令牌区已同步在册）"
    assert "letter-spacing:.5px" not in PAGE, "半像素裸声明残留"
    assert "letter-spacing:2px" not in PAGE, "两像素裸声明残留"
    assert "letter-spacing:2px" not in NPAGE, "NOTIFY 两像素裸声明残留"


# ---- merged from tests/test_r274_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE = webui.PAGE
NPAGE = webui.NOTIFY_PAGE


def _block(start_anchor, end_anchor):
    m = PAGE.index(start_anchor)
    return PAGE[m:PAGE.index(end_anchor, m + 10)]


# ---------- W1: NOTIFY 页脚链基态 ----------

def test_notify_foot_link_base_none():
    assert "border:none;background:none;text-decoration:none}" in NPAGE, \
        "NOTIFY .foot a 缺基态去下划线（UA 默认 underline 恒在）"
    # hover 显形档保留（基态收口不吞可供性反馈）
    assert ".foot a:hover{background:none;text-decoration:underline}" in NPAGE


# ---------- W2: lay_min=0 衔接小字中性灰 ----------

def test_lay0_row_neutral_class():
    # r294 P3-1：两分支补 nw 豁免（断词孤字收口），中性语义不变
    # （lay_min=0 分支仍无 lay/ok，仅多 nw 词组 nowrap）
    assert ('<div class="${f.layMin>0?(\'stl lay nw\'+((+f.layoverM||0)>=f.layMin?\' ok\':\'\')):\'stl nw\'}"'
            in PAGE), "lay_min=0 时衔接小字未降级中性 .stl（假警示橙红恒挂）"
    # 禁复活：旧形态 class 属性无条件落 stl lay
    assert 'class="stl lay${(f.layMin>0&&' not in PAGE, \
        "衔接小字退回无条件 stl lay 形态"


def test_dark_qual_row_lay_ok_exempt_from_muted_lift():
    """暗色 qual 行 .stl 提亮灰 (0,3,2) 恒压 .stl.lay.ok (0,3,0)——
    衔接达标小字是 .ok 语义绿档非中性子行，须豁免（与推送 PNG
    达标行停时 C_QUAL 绿同语言）；真机实锤：demo 暗色 qual 行内
    「停X(ok)」computed 落 #8ba0b4 灰、非 qual 行同款为绿。"""
    assert "html[data-theme=\"dark\"] tr.qual .stl.lay.ok{color:var(--ok-txt)}" \
        in PAGE, "暗色 qual 行衔接达标小字缺提亮灰豁免（绿语义被压灰）"


# ---------- W3: 空态阈值图例隐藏 ----------

def test_empty_state_threshold_legend_hidden():
    body = _block("if(!vals.length||!(K?CD.length+CT.length:hd.length+ht.length)){",
                  "$('chartEmpty').style.display='none';")
    assert "$('lgZone').style.display='none'" in body, \
        "空态早退分支未隐藏 lgZone 色票"
    assert "$('lgThD').style.display='none'" in body, \
        "空态早退分支未隐藏 lgThD 色票"
    assert "$('lgThT').style.display='none'" in body, \
        "空态早退分支未隐藏 lgThT 色票"


# ---------- W4: 跨端同值同步律注记 ----------

def test_cross_channel_sync_notes():
    assert "--green:#0e8345;     /* 与推送图达标绿 C_QUAL 同值（跨端同色同义），改必双端同步（report.py） */" \
        in PAGE, "--green 缺 C_QUAL 同值同步律注记"
    assert "与推送图 LAY_SHORT 同值" in PAGE and "改必双端同步（report.py）" in PAGE, \
        "--stl 缺 LAY_SHORT 同值同步律注记"


# ---------- W5: routechips 注入收口 ----------

def test_routechips_escaped_injection():
    # r316 FC-1 在 data-r 与 onclick 之间补 aria-pressed 程序态，
    # 钉面随模板形态改写（转义担保不丢：data-r 仍过 he()）
    assert ('" data-r="${he(p)}" aria-pressed='
            '"${FLT.routes.has(p)?\'true\':\'false\'}" '
            'onclick="togRoute(this)">') in PAGE, \
        "routechips 文本位/属性位未过 he() 收口"
    assert "function togRoute(el){const p=el.dataset.r;" in PAGE, \
        "togRoute 未改走 dataset.r 取值"
    # 禁复活：属性内裸内插形态
    assert "togRoute(this,'${p}')" not in PAGE, \
        "routechips onclick 属性退回裸内插"


# ---------- W6: .uname 字距备案 ----------

def test_uname_tracking_annotated():
    assert ".uname{font-size:15px;font-weight:700;letter-spacing:.3px}  /* 人名字距独立档：15px 展示性大字距不入 --ls05 族（同 h1 品牌对语义） */" \
        in PAGE, ".uname 字距独立档缺备案注释"


# ---- merged from tests/test_r288_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_switchview_back_batch_rejudges_tw():
    """R288-1：cfg→mon 回程批的 xhint 重判清单必须含 .tw（与其余
    三批同族齐备；窗口锚=chart() 早退补拍行，块内定位不靠字符数）。"""
    src = _src()
    i = src.find("if(MONTAB==='trend')chart();")
    assert i > 0, "回程批锚点易位"
    seg = src[i:i + 400]
    m = re.search(r"document\.querySelectorAll\('([^']+)'\)", seg)
    assert m, "回程批重判选择器未找到"
    sels = m.group(1).split(",")
    assert ".tw" in sels, f"cfg→mon 回程批缺 .tw 重判: {m.group(1)}"


def test_hsrcnote_static_default_neutral():
    """R288-2：静态默认词面留空（冷失败态不显生产词面）；render
    成功路径回设在案（r236 P3-1a 语义担保随行）。"""
    src = _src()
    assert '<span id="hsrcNote"></span>' in src, \
        "hsrcNote 静态默认词面非空（冷失败态失真）"
    assert "s.demo?'演示合成数据':'解析自 monitor.log'" in src, \
        "render 成功路径回设缺失"


# ---- merged from tests/test_r312_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _mk_crawler(tmp_path):
    c = BaseCrawler.__new__(BaseCrawler)
    c.debug = True
    c.debug_dir = str(tmp_path)
    c.name = "testplat"
    c.logger = _FakeLogger()

    class _Page:
        def screenshot(self, *a, **k):
            raise RuntimeError("no shot in test")

        def content(self):
            return "<html></html>"
    return c, _Page()


def test_debug_snapshot_extra_text_writes_txt(tmp_path):
    """extra_text 在场 → {base}.txt 落盘且内容逐字节一致（回放载体）。"""
    c, page = _mk_crawler(tmp_path)
    c._debug_snapshot(page, "pc_ABCD_2026-10-15",
                      extra_text="航班A\n@@@\n航班B")
    txt = Path(tmp_path) / "testplat_pc_ABCD_2026-10-15.txt"
    assert txt.exists(), "extra_text 未落 .txt"
    assert txt.read_text(encoding="utf-8") == "航班A\n@@@\n航班B"


def test_debug_snapshot_without_extra_text_no_txt(tmp_path):
    """缺省不落 .txt（既有调用方零变化）。"""
    c, page = _mk_crawler(tmp_path)
    c._debug_snapshot(page, "pc_X")
    assert not (Path(tmp_path) / "testplat_pc_X.txt").exists()


def test_fliggy_fetch_wires_full_stream():
    """fliggy 抓取尾段把解析输入 full（innerText 流）传给快照
    （回放载体的接线点：存的是解析器实际吃的东西，不是 DOM 壳）。"""
    import crawlers.fliggy as _fm
    # 接线断言走源码级（模块定位随包安装位置走，非仓库根 CWD 亦可跑）；
    # 行为级全链需真浏览器，uitest 面；此处锁接线形态防回归
    body = Path(_fm.__file__).read_text(encoding="utf-8")
    call = [ln for ln in body.splitlines()
            if "self._debug_snapshot(page, f\"pc_{fc}{tc}_{date}\"" in ln]
    assert len(call) == 1, "pc_ 快照调用形态漂移"
    idx = body.splitlines().index(call[0])
    nxt = body.splitlines()[idx + 1]
    assert "extra_text=full" in nxt, "pc_ 快照未传解析输入流"


def test_pillstate_failure_forms_carry_bad_flag():
    """失败形态 pillState **全部**带 bad 旗标（计数断言锁全量——存在性
    断言对「其中一处回退」失明）：服务异常 ×3、服务未启动 ×2；
    中性态（已全停用/未配置/达标态）不带。"""
    src = webui_full_src()
    assert src.count("pillState('服务异常','pill bad',") == 3, \
        "服务异常失败形态应恰 3 处带 bad 旗标"
    assert src.count("pillState('服务未启动','pill bad',") == 2, \
        "服务未启动失败形态应恰 2 处带 bad 旗标"
    assert "pillState('已全停用','pill'," in src, "中性态被误标 bad"
    assert "pillState('未配置','pill'," in src, "中性态被误标 bad"


def test_jumpqual_branches_on_bad_flag():
    """jumpQual 首分支按 bad 旗标分路（行为钉在 uitest 尾段）。"""
    src = webui_full_src()
    assert "classList.contains('bad')" in src
    assert "恢复后自动刷新" in src


def test_header_bleed_matches_wrap_padding_clamp():
    """header 出血与 .wrap padding 同函数（相抵律）：-clamp(12px,3vw,18px)。
    几何行为钉（三带巡检）在 tools/uitest.py。"""
    src = webui_full_src()
    assert "margin:0 calc(-1*clamp(12px,3vw,18px)) 4px" in src


# ---- merged from tests/test_r314_webui_polish.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = None
BASE = ""
_proc = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(timeout=20.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + timeout
    while time.time() < end:
        try:
            with opener.open(BASE + "/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False










# ---------- P1-1: RM 伪元素盲区 ----------



def test_rm_selector_source_pin():
    """源码钉：RM 块选择器含伪元素两臂。"""
    import webui
    import pathlib
    src = webui_full_src()
    assert ("@media(prefers-reduced-motion:reduce){*,*::before,*::after"
            "{transition:none!important;animation:none!important}}") in src, (
        "RM 禁令选择器未扩伪元素（*::before,*::after 两臂必须在场）")


# ---------- P1-2: .pill.bad 错误态着装 ----------



# ---------- P2-1: .cnav.on 辉光 + focus reclaim ----------



# ---------- P2-2: body 孤苗过渡删除 ----------



# ---------- P2-3: erow 内联重置钮 ----------



# ---------- P3-1: sticky 表头滚动态投影 ----------





# ---- merged from tests/test_r323_trend_source.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(price, code, fetched):
    el = [{"price": price, "code": code, "name": code,
           "depTime": "08:00", "arrTime": "11:00"}]
    return FlightPrice(
        platform="qunar", from_city="URC", to_city="SHA",
        depart_date="2026-11-01", price=price, airline="",
        flight_no=code, depart_time="08:00", arrive_time="11:00",
        extra=json.dumps(el, ensure_ascii=False), fetched_at=fetched)


def test_trend_payload_reads_state_cfg_db(tmp_path, monkeypatch):
    """数据源=_State.cfg；config_path 是诱饵（lo=999）不得被读。"""
    db_cfg = os.path.join(str(tmp_path), "cfg.db")
    db_decoy = os.path.join(str(tmp_path), "decoy.db")
    now = _now_s()
    PriceStorage(db_cfg).save_many([_row(1710.0, "CZ1", now)])
    PriceStorage(db_decoy).save_many([_row(999.0, "CZ9", now)])
    for db in (db_cfg, db_decoy):
        PriceStorage(db).refresh_daily("URC", "SHA", "2026-11-01")
    cfg_yaml = os.path.join(str(tmp_path), "config.yaml")
    with open(cfg_yaml, "w", encoding="utf-8") as f:
        f.write(f"output:\n  db_path: {db_decoy}\n")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db_cfg}})
    monkeypatch.setattr(webui._State, "config_path", cfg_yaml)
    out = webui._trend_payload({"from": ["URC"], "to": ["SHA"],
                                "date": ["2026-11-01"],
                                "days": ["30"], "th": ["1500"]})
    assert out["ok"], out
    assert out["direct"] and out["direct"][-1][1] == 1710.0, out


def test_build_demo_db_seeds_price_daily(tmp_path):
    """demo 库必须派生 price_daily（直/中双桶在案，长窗非空态）。"""
    path = demo_mod.build_demo_db(os.path.join(str(tmp_path), "demo.db"))
    con = sqlite3.connect(path)
    kinds = dict(con.execute(
        "SELECT kind, COUNT(*) FROM price_daily GROUP BY kind").fetchall())
    con.close()
    assert kinds.get("d", 0) > 0, kinds
    assert kinds.get("t", 0) > 0, kinds


def test_demo_bake_intercepts_trend_api(tmp_path, monkeypatch):
    """静态演示站 fetch shim 必须拦 /api/trend（长窗死通道=静态站长窗
    恒「正在加载」假死）——烘焙产物带三档×全航线的趋势数据。"""
    import tools.demo_build as bake
    import webui as _wui
    # build() 直写 _State.cfg/users/version（demo 态三件）——快照还原，
    # 不还原会污染后续用例（v193 statecache 假红实录，Soldier 抓获）
    for _attr in ("cfg", "users", "version"):
        monkeypatch.setattr(_wui._State, _attr,
                            getattr(_wui._State, _attr))
    out = os.path.join(str(tmp_path), "site")
    monkeypatch.setattr(bake, "OUT", os.path.join(out, "index.html"))
    bake.build()
    with open(bake.OUT, encoding="utf-8") as f:
        html = f.read()
    assert "/api/trend" in html, "shim 未拦 /api/trend"
    assert "trend" in html and html.count("|30") >= 3, \
        "烘焙数据缺三档趋势载荷"


# ---- merged from tests/test_r339j_duration.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "totalDuration": "2时30分"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


def test_duration_within_limit_passes():
    from core.alerter import Alerter
    rt = _route(max_duration_h=3)
    assert Alerter._route_filters([_flt()], rt)          # 2.5h ≤ 3h
    assert Alerter._route_filters(
        [_flt(totalDuration="3时")], rt)                  # 边界含端


def test_duration_over_limit_dropped():
    from core.alerter import Alerter
    rt = _route(max_duration_h=2)
    assert not Alerter._route_filters([_flt()], rt)       # 2.5h > 2h
    assert not Alerter._route_filters(
        [_flt(totalDuration="5时25分")], rt)
    # 小数小时（0.5 步进语义）：1.5h 门对 2h 行剔除
    rt2 = _route(max_duration_h=1.5)
    assert not Alerter._route_filters([_flt(totalDuration="2时")], rt2)
    assert Alerter._route_filters([_flt(totalDuration="1时20分")], rt2)


def test_duration_zero_is_off():
    from core.alerter import Alerter
    rt = _route()
    assert Alerter._route_filters([_flt(totalDuration="18时")], rt)


def test_duration_unparsable_fail_close():
    """不可解析的行按不满足（fail-close 同律）：门开着时薄行不放行。"""
    from core.alerter import Alerter
    rt = _route(max_duration_h=5)
    assert not Alerter._route_filters([_flt(totalDuration="")], rt)
    assert not Alerter._route_filters([_flt(totalDuration=None)], rt)
    assert Alerter._route_filters(
        [_flt(totalDuration="1时30分")], rt)              # 正常行不受累


def test_build_routes_wires_key():
    rt = _route(max_duration_h=4.5)
    assert rt.max_duration_h == 4.5
    # 漏传防线：缺键归 0（门关闭），不因 KeyError 整卡报废
    rt0 = _route()
    assert rt0.max_duration_h == 0


# ---- PAGE 词面钉 ----

def test_page_duration_row():
    import webui
    src = webui.PAGE
    assert "<b>最长飞行时长</b>" in src
    assert "setRoute(${i},${j},'max_duration_h',this.value)" in src
    assert "渠道未标注时长的班次按不满足剔除" in src
    # saveCfg 越界拦截词面
    assert "最长飞行时长须为 0-72 小时" in src
    # 折叠头 title 词面同步
    assert "最长飞行时长" in src.split("筛选与时段约束")[0] or \
        "价格上限/最长飞行时长" in src


def test_specials_badge_price_gate():
    """P3 速修钉：特价 0 价/缺价=配置未完形，徽标与卡头不得报「开」。"""
    import webui
    src = webui.PAGE
    assert src.count("_spOn=!!(_sp0&&_sp0.enabled!==false&&(_sp0.from||"
                     "_sp0.from_name)&&Number(_sp0.max_price)>0)") == 2
    # 到达窗 hint 跨零点宣传（与出发窗对称）
    assert "支持跨零点</b>，如 22:00–06:00" in src


# ---- merged from tests/test_r368_cancel_isolation.py ----

class _SlowLate:
    name = "slowlate"

    def __init__(self, cfg, logger):
        self.paths = []
        self.probe_mode = False
        self.on_path = None

    def login_url(self):
        return ""

    def fetch(self, fc, tc, dates):
        time.sleep(0.6)
        return [SimpleNamespace(
            price=100, airline="测试航", flight_no="LATE1",
            depart_time="08:00", arrive_time="10:00",
            extra=json.dumps([{"price": 100, "code": "LATE1",
                               "name": "测试航", "depTime": "08:00",
                               "arrTime": "10:00"}], ensure_ascii=False))]


_D1 = (date.today() + timedelta(days=30)).isoformat()
_D2 = (date.today() + timedelta(days=31)).isoformat()
_D3 = (date.today() + timedelta(days=60)).isoformat()

def test_cancel_late_result_stays_old_and_new_task_rejected():
    old_reg = crawlers.REGISTRY.get("slowlate")
    old_cfg = getattr(webui._State, "cfg", None)
    old_last = webui._PROBE_LAST
    crawlers.REGISTRY["slowlate"] = _SlowLate
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    webui._PROBE_AUTH.clear()
    cancel = threading.Event()
    result = {}

    def run_old():
        try:
            result["old"] = webui._probe_search(
                None, None, None, ["slowlate"],
                legs=[{"from": "上海", "to": "北京", "date": _D1}],
                cancel=cancel)
        except Exception as e:  # pragma: no cover
            result["err"] = repr(e)

    try:
        th = threading.Thread(target=run_old)
        th.start()
        time.sleep(0.15)
        cancel.set()
        with pytest.raises(RuntimeError) as ei:
            webui._probe_search(
                None, None, None, ["slowlate"],
                legs=[{"from": "上海", "to": "北京", "date": _D1}])
        assert "冷却" in str(ei.value) or "已有探针" in str(ei.value)
        th.join(timeout=10)
        assert not th.is_alive()
        assert "err" not in result
        old = result["old"]
        codes = [r.get("code") for r in old.get("rows") or []]
        assert "LATE1" in codes, "cancelled fetch result must be retained on the old task"
    finally:
        if old_reg is None:
            crawlers.REGISTRY.pop("slowlate", None)
        else:
            crawlers.REGISTRY["slowlate"] = old_reg
        webui._State.cfg = old_cfg
        webui._PROBE_LAST = old_last
        webui._PROBE_AUTH.clear()


# ---- merged from tests/test_r491_front_back_field_alignment.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 前端在这些对象上读 node.* / v.* 字段；只统计「节流行读取 PTH 节点」那一段
FRONT_SCOPE_ANCHOR = "const node=PTH[k]||{},pw=node.paths||{}"


def _front_fields():
    w = webui_full_src()
    i = w.index(FRONT_SCOPE_ANCHOR)
    # 节流行拼装整段（到下一个渠道 map 结束前）
    seg = w[i:i + 7000]
    return set(re.findall(r"\bnode\.([a-z_]+)", seg)), w


def _backend_node_keys(tmp_path):
    """真实 /api/paths 产出里，平台节点上实际存在的键。

    用临时账本固定「近 24h 有 pc/h5 两条 ok」的形态，不依赖本机生产库
    当前是否在跑；干净克隆也走同一条聚合实现。
    """
    import sqlite3
    import time

    import webui
    db = str(tmp_path / "paths.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
            " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
            " depart_date TEXT, attempt_id TEXT, fetched_at TEXT)")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.executemany(
            "INSERT INTO fetch_paths (platform, entry_path, path_status,"
            " from_city, to_city, depart_date, attempt_id, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-10", "a1", now),
             ("ctrip", "H5", "ok", "SHA", "BJS", "2026-11-10", "a1", now),
             ("qunar", "H5", "blocked", "SHA", "BJS", "2026-11-10", "a2",
              now)])
        conn.commit()
    finally:
        conn.close()
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": db}}
    try:
        p = webui._paths_payload(24)
    finally:
        webui._State.cfg = old
    plats = (p or {}).get("platforms") or {}
    keys = set()
    for node in plats.values():
        keys |= set((node or {}).keys())
        for sc in ((node or {}).get("scopes") or {}).values():
            keys |= set((sc or {}).keys())
    return keys, len(plats)


def test_frontend_node_fields_all_exist_in_real_payload(tmp_path):
    front, w = _front_fields()
    # scroll/get/class 之类不是数据字段，排除
    front = {f for f in front if f not in ("scroll", "get", "class",
                                           "scrollLeft", "scrollWidth")}
    assert front, "未能解析节流行的 node.* 读取"
    back, n = _backend_node_keys(tmp_path)
    assert back, "聚合产出为空，判据失去锚点"
    missing = sorted(front - back)
    assert not missing, (
        "前端读取但后端不产出的字段（该维度会永远空白）：%s\n"
        "前端读取集合：%s" % (missing, sorted(front)))


# ---- merged from tests/test_r495_trace_request_url.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LONG = ("https://m.ctrip.com/html5/flight/taro/first?from=inner&tripType=ONE_WAY"
        "&depCity=SHA&arrCity=BKK&depDate=2026-11-05&channel=xx&trace=abcdef")
TRACE = {"ok": True, "platform": "fliggy",
         "rows": [
             {"fetched_at": "2026-10-29 03:20:00", "entry_path": "H5",
              "path_status": "login", "note": "登录墙", "request_url": LONG},
             {"fetched_at": "2026-10-29 03:10:00", "entry_path": "PC",
              "path_status": "ok", "note": "出数 12 条", "request_url": ""},
         ],
         "interventions": [], "effect": {}}
PACING = {"ok": True, "quiet": {}, "last_round": {}, "channels": {
    "fliggy": {"state": "ok", "needs_login": False, "scene": {},
               "advice": {"state": "ok", "action": "none", "severity": "ok",
                          "hint": "正常", "eta_s": 0}}},
    "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {}}




# ---- merged from tests/test_r516_all_red_distinguishes_stalled.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _node(last_at):
    return {"query_attempts": 0, "paths": {}, "last_at": last_at,
            "last_ok_at": last_at, "scopes": {}}


def _ts(hours_ago):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(time.time() - hours_ago * 3600))


def test_recent_empty_window_is_still_unknown():
    """刚启动 / 刚清库：仍然说「先跑一轮」，不能一上来就报警。"""
    a = advise("ctrip", {}, {}, node=_node(_ts(0.2)))
    assert a["state"] == "unknown", a
    assert a["severity"] == "ok", a


def test_long_silence_is_reported_as_stalled_not_as_first_round():
    a = advise("fliggy", {}, {}, node=_node(_ts(25)))
    assert a["state"] == "stalled", "采集停了 25 小时仍判成「待首轮」：%r" % (a,)
    assert a["severity"] == "act", "停摆被标成无需处理：%r" % (a,)
    assert "采集" in a["hint"], a
    # 关键：必须明确「登录状态本身无需重做」，否则用户会去反复重登
    assert "登录" in a["hint"], \
        "没有告诉用户这跟登录无关（会引发无效重登）：%r" % (a["hint"],)
    assert "25" in a["hint"] or "24" in a["hint"], \
        "没有说明停了多久：%r" % (a["hint"],)


def test_no_sample_ever_is_unknown_not_stalled():
    """从未采集过（没有 last_at）：不能说「停了」，那是新装。"""
    a = advise("tuniu", {}, {}, node=_node(""))
    assert a["state"] == "unknown", a


def test_fresh_samples_but_no_window_is_not_stalled():
    """刚有样本、只是本轮窗口空（例如刚清空统计）：不算停摆。"""
    a = advise("qunar", {}, {}, node=_node(_ts(1)))
    assert a["state"] == "unknown", a


def test_panel_renders_the_stalled_state_distinctly():
    import io
    w = webui_full_src()
    assert "adv.state==='stalled'" in w, "节流行没有专门的「采集停了」分支"
    i = w.index("adv.state==='stalled'")
    seg = w[i:i + 420]
    assert "采集停了" in seg, "标签没有说明是采集停了"
    assert "bad" in seg, "停摆没有用告警色"
    # 与「待首轮」必须仍是两个独立分支（顺序在前，各管各的）
    j = w.index("adv.state==='unknown'")
    assert i < j, "「采集停了」分支必须排在「待首轮」之前"


def test_backend_supplies_cross_window_last_seen(monkeypatch, tmp_path):
    """窗口内一条记录都没有时，仍要能拿到全表最近样本。

    用临时库固定「fliggy 最后一条样本在 26 小时前」的形态：不依赖本机
    生产库当下是否恰好在跑，干净克隆也能复核同一条判据。
    """
    import sqlite3

    import webui

    stale = _ts(26)
    db = str(tmp_path / "prices.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE fetch_paths (platform TEXT, fetched_at TEXT)")
        conn.execute("INSERT INTO fetch_paths VALUES ('fliggy', ?)", (stale,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db}}, raising=False)
    ls = webui._last_seen_of("fliggy")
    assert ls == stale, "拿不到不限窗口的最近样本：%r" % (ls,)
    a = advise("fliggy", {}, {}, node={"last_seen_at": ls}, quiet={})
    assert a["state"] == "stalled", \
        "拿到 26 小时前的样本仍判成「待首轮」：%r" % (a,)
    assert "登录" in a["hint"], "没有点明与登录无关"


# ---- merged from tests/test_r600_proxy_map_configurable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATS = ["qunar", "fliggy", "ctrip", "tongcheng", "tuniu"]


def _w():
    return webui_full_src()


def test_backend_reads_back_proxy_map():
    w = _w()
    i = w.index('"proxy": str((cfg.get("crawler") or {}).get(')
    seg = w[i:i + 900]
    assert '"proxy_map"' in seg, "GET /api/config 没有回读 crawler.proxy_map"


def test_every_channel_has_a_proxy_map_control():
    w = _w()
    i = w.index("渠道出口 · 按渠道绑代理")
    seg = w[i:i + 1400]
    for p in PLATS:
        assert "'glbPm_'+p" in seg, "缺少 %s 的出口代理控件" % p
    assert "GLB.proxy_map=Object.assign(" in seg, "控件没有写回 GLB.proxy_map"


def test_post_persists_proxy_map_with_shape_validation():
    w = _w()
    i = w.index('if isinstance(glb.get("proxy_map"), dict):')
    seg = w[i:i + 300]
    assert '_crw["proxy_map"] = _proxy_map_clean(' in seg, (
        "没有落到 crawler.proxy_map")


def test_clean_helper_rejects_bad_and_empty_values():
    """真调用落盘用的清洗函数——这是 POST 分支唯一实际执行的那段。"""
    import sys
    sys.path.insert(0, ROOT)
    from webui import _proxy_map_clean
    got = _proxy_map_clean({
        "qunar": " http://127.0.0.1:7891 ",
        "ctrip": "127.0.0.1:7892",   # 漏 scheme
        "fliggy": "",
        "tongcheng": None,
        "tuniu": "socks5://127.0.0.1:7893",   # 非 http(s)
    })
    assert got == {"qunar": "http://127.0.0.1:7891"}, got


def test_clean_helper_keeps_every_valid_channel():
    import sys
    sys.path.insert(0, ROOT)
    from webui import _proxy_map_clean
    src = {p: "http://127.0.0.1:%d" % (7890 + i)
           for i, p in enumerate(PLATS)}
    assert _proxy_map_clean(src) == src, "合法值被误删"


def test_control_value_matches_backend_key():
    """控件写的键名必须与后端读的键名一致——写成 proxyMap 就会静默失效。"""
    w = _w()
    i = w.index("渠道出口 · 按渠道绑代理")
    seg = w[i:i + 1400]
    assert "GLB.proxy_map" in seg
    assert "GLB.proxyMap" not in seg, "前端写成 proxyMap，后端读不到"


# ---- merged from tests/test_r699_overview_collapse_really_collapses.py ----

SRC = webui.PAGE


def _collapsed_rules():
    return re.findall(r"#searchview\.srx-ov-collapsed[^{]*\{[^}]*\}", SRC)


def test_collapsed_state_hides_the_rest_of_the_title_row():
    joined = "\n".join(_collapsed_rules())
    for sel in ("#srxOvSum", "#srxBandMeta", ".srx-bandnav", ".srx-axis",
                ".srx-bandlogin"):
        assert sel in joined, (
            "收起态没有隐藏 %s——标题行会留下一整排操作控件，读作「收不回去」"
            % sel)


def test_trigger_stays_pinned_right_when_title_row_is_slimmed():
    """判据是「有一个零宽撑杆把触发器顶到右缘」，不是某一种实现写法。

    r830 之前撑杆是 `.srx-band-h::after{flex:1 1 auto;order:1}`；r830 把
    触发器挪到标题之后、其余控件挪到触发器之后，撑杆随之变成真实元素
    `.srx-band-fill`（`order:2`，触发器 `order:3`）。两种都能满足意图：
    隐藏左邻后触发器仍贴右缘（实测两态同为 left=1338.5 / top=256.9）。
    """
    joined = "\n".join(_collapsed_rules())
    has_spacer = (
        ("::after" in joined and "flex:1 1 auto" in joined)
        or (".srx-band-fill" in SRC and "flex:1 1 auto" in SRC)
    )
    assert has_spacer, (
        "没有撑杆：隐藏左邻后 margin-left:auto 推不动，触发器会掉到标题右侧")
    assert ("srx-foldbtn{order:2}" in joined) or ("srx-ovtoggle" in SRC and "order:3" in SRC), (
        "撑杆没排在触发器之前，会把按钮挤到左边")


def test_title_row_height_pinned_so_trigger_does_not_shift_vertically():
    joined = "\n".join(_collapsed_rules())
    assert re.search(r"\.srx-band-h\{min-height:34px\}", joined), (
        "标题行在收起态会矮 2px，触发器随之纵移 1px（两态须同坐标）")


def test_collapsed_grid_keeps_no_empty_tracks():
    """收起态只有「标题 + 触发器」，不能被空轨道撑出高度。

    实测缺陷（r832 改 grid 后，1512）：其余成员虽 `display:none`，但
    `grid-area:3/1/4/2` 这类显式放置仍会**建立轨道**，8px 行距把两条空
    轨道一起算进高度——标题行 34→107px，触发器下方多出 73px 空白，
    读起来像「收起了却还留着一条空带」。判据：收起态必须收敛成单轨道
    且行距为 0（`grid-template-rows:auto` + `row-gap:0`）。
    """
    joined = "\n".join(_collapsed_rules())
    body = ""
    for m in re.finditer(
            r"#searchview\.srx-ov-collapsed[^{]*\.srx-band-h\{[^}]*\}", SRC):
        if "grid-template-rows" in m.group(0) or "row-gap" in m.group(0):
            body = m.group(0)
    assert body, "收起态没有单独收敛标题行轨道的规则"
    assert "grid-template-rows:auto" in body, (
        "收起态没有收敛轨道：空的第 3/4 行会把标题行撑高")
    assert "row-gap:0" in body, "收起态仍有行距，空轨道会被撑开"
    assert "min-height:34px" in joined


# ---- merged from tests/test_v15110_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_delta_by_date_payload_built():
    """载荷带 delta_by_date：按日期匹配 routes_arr（date 参数路径）。"""
    assert '"delta_by_date"' in _src()
    assert '_delta_vs_prev(b, "direct", d)' in _src()


def test_delta_vs_prev_date_match_precedes_label():
    """date 精确匹配先于 label 匹配：单航线多日期 route='' 时
    不得错配 routes_arr[0] 的序列。"""
    src = _src()
    i_date = src.find('if r.get("date") == date')
    i_label = src.find('if r["label"] == brief["route"]')
    assert i_date != -1 and i_label != -1 and i_date < i_label


def test_dgroup_kpi_passes_delta_by_date():
    """前端 dgroup 分支传 dDl[d]/dTl[d]（恒 null 曾让多日期概览
    无任何涨跌信息）；demo/旧快照无字段时安全退化。"""
    import webui
    assert "(x.delta_by_date||{}).direct||{}" in webui.PAGE
    assert "kpiCard('d',dd,dth,'直飞最低',dDl[d],d)" in webui.PAGE


def test_srtchip_single_source_sortcol():
    """「⇅日期」chip 点击走 sortCol('date') 单源（与表头同一
    SORT 状态机），箭头 data-dir 属性驱动。"""
    import webui
    assert "function dateSortChip(el){sortCol('date');" in webui.PAGE
    assert '.srtchip[data-dir="asc"] .arr::after{content:"↑"}' \
        in webui.PAGE


def test_srtchip_visible_only_le760():
    """chip 默认隐藏（桌面表头入口在），≤760 媒体块显示（日期列
    隐藏的对称补偿）——两处声明各自在其媒体语境生效。"""
    import webui
    assert " .srtchip{display:none}" in webui.PAGE
    assert "  .srtchip{display:inline-block}" in webui.PAGE


def test_preview_payload_splits_per_date():
    """预览逐日期独立成 entry（与生产逐日期喂条形状对齐）；
    Route 构造保持在日期循环外（_digest_payload 的 hit_routes
    id 恒等依赖，推送审校预演护栏）。"""
    src = _src()
    assert 'for d in rv["dates"]:' in src
    assert "prices = [FlightPrice(" in src
    i_route = src.find("route = Route(")
    i_loop = src.find('for d in rv["dates"]:', max(0, i_route - 400))
    assert i_route != -1 and i_loop != -1 and i_route < i_loop


def test_top_best_delta_carries_date():
    """顶层 best 卡 delta 按所属日期精确匹配（单航线多日期 route
    为空串时 label 回退会错配首日期序列——既有潜伏同轮收口）。"""
    src = _src()
    assert '"date": (f.get("depDate") or "")}' in src
    assert '(bd_brief or {}).get("date")' in src
    assert '(xt_brief or {}).get("date")' in src


def test_zero_childlist_sort_chip_path():
    """排序 chip 就地更新只走 classList/setAttribute/dataset
    （零 childList）；函数体（至下一函数边界）内不得出现
    innerHTML/textContent 重建。"""
    import webui
    i = webui.PAGE.find("function dateSortChip(el){")
    assert i != -1
    j = webui.PAGE.find("\nfunction togDate", i)
    assert j != -1
    seg = webui.PAGE[i:j]
    assert "innerHTML" not in seg and "textContent" not in seg


# ---- EN-3 航线维度 URL 深链（#tab/uN） ----

def test_hash_user_deep_link_write():
    """pickUser 写 #tab/uN 深链（曾只有 tab 级，航线选择不可分享）。"""
    import webui
    assert "history.replaceState(null,'','#'+MONTAB+'/u'+i)" in webui.PAGE


def test_hash_user_restore_after_restoreui():
    """启动恢复在 restoreUI 之后（否则 localStorage U 覆盖 hash）。"""
    import webui
    src = webui.PAGE
    i_restore = src.find("restoreUI();mkactAll();")
    i_hash_u = src.find("深链用户段恢复")
    assert i_restore != -1 and i_hash_u != -1 and i_restore < i_hash_u


def test_hashchange_user_seg_parse():
    """hashchange 活页解析 /uN 段：越界忽略（不钳 0 乱切）。"""
    import webui
    assert "_un<S.users.length)pickUser(_un)" in webui.PAGE


# ---- EN-4 行展开态持久化 ----

def test_expand_state_persisted():
    """EXP/TGOPEN 入 saveUI 序列化 + restoreUI 类型守卫回填。"""
    import webui
    # r320 行属性筛选族入快照：尾键随轮演进（pmax 后接 airlines/ps/
    # few/nostop/noshare/safe/lmin/lmax/dmin/dmax/pr/ag/bg/ml/nl/cr/ch
    # ——准点率/机龄/行李/餐食/廉航/跨天/儿童价等维度陆续入排；
    # r339 起 bkg（托运 kg）/wb（仅大型机明细门）随两 facet 入排成尾键）
    assert ("chr:CHR,exp:EXP,tg:TGOPEN,pmin:FLT.pmin||0,pmax:FLT.pmax||0,"
            in webui.PAGE)
    assert "wb:FLT.wb,so:FLT.shareOnly,st:FLT.stopOnly,ro:FLT.riskOnly,hc:FLT.hideCal,oq:FLT.onlyQual,wo:WATCH_ONLY}" in webui.PAGE
    assert "if(typeof j.exp==='string')EXP=j.exp;" in webui.PAGE
    assert "if(typeof j.tg==='string')TGOPEN=j.tg;" in webui.PAGE


def test_expand_state_all_exit_paths_persist():
    """持久化全出口对称（Soldier P2-2）：开（togRow/togGo 主路）、
    收（各自 toggle 回同键分支）、Esc 级联清（键盘 Esc 分支）三条
    退出路径全部落盘——收起不落盘则 localStorage 残旧键、刷新复开。
    r220 affordance 轮：各收路同轮补 _ariaOff() 态回写（落盘语义不变）。
    r257 P3-3：togGo 收分支与 Esc 级联收改期分支补 _ariaOff() 回写
    （.tg 家族并入单源，落盘语义不变）。"""
    import webui
    assert "if(EXP===k){EXP=null;if(cur)cur.style.display='none';_ariaOff();saveUI();return;}" \
        in webui.PAGE
    assert "if(TGOPEN===k){TGOPEN=null;if(tg)tg.style.display='none';el.setAttribute('aria-expanded','false');saveUI();return;}" \
        in webui.PAGE
    assert "if(EXP){EXP=null;_hideXrows();_ariaOff();saveUI();}" in webui.PAGE
    assert "if(TGOPEN){TGOPEN=null;_hideXrows();_ariaOff();saveUI();}" in webui.PAGE


# ---- merged from tests/test_v15111_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_pulsecard_inside_overview_tab():
    """脉冲卡 DOM 位于概览 tab 容器内（容器开标签先于 pulsecard）。"""
    src = _src()
    assert src.index('id="montab-overview"') < src.index('id="pulsecard"')
    assert src.index('id="pulsecard"') < src.index("</div><!-- /montab-overview -->")


def test_pulse_alert_badge_wiring():
    """红帽徽标三件套：概览 tab 红点、渲染函数、renderPulse 尾部接线。"""
    src = _src()
    assert 'id="ovAlert"' in src
    assert "function renderPulseAlert(fails)" in src
    assert "renderPulseAlert(last.fails||0);" in src


def test_pulse_alert_badge_a11y():
    """徽标读屏语义（WebUI 审计 EN-9）：role=img + aria-label 静态
    在位——display:none 天然从可访问性树移除，点亮即暴露。"""
    src = _src()
    # r281 红帽双源合成后语义扩为「采集或推送通道有异常」
    assert 'id="ovAlert" role="img" aria-label="采集或推送通道有异常' in src


def test_desktop_montabs_sticky_tail_block():
    """桌面吸顶：761+ 主块的 sticky 声明消费 --hdh 动态贴 header 实高
    （top:var(--hdh,54px)，fallback 与旧固定值等效）；761-900 带内
    固定校准覆写块已随动态化退役——变量自动跟随倒计时折行，固定
    单值反而在实高漂移时盖住切换器（WD P1-1 生产 768 实测盖 33px）。
    本钉锁两件事：主块形态（消费变量）+ 固定校准块不回流。"""
    src = _src()
    assert "#montabs{position:sticky;top:var(--hdh,54px)" in src
    assert "html{scroll-padding-top:calc(var(--hdh,54px) + 34px)" in src
    main761 = src.index("@media(min-width:761px){")   # 带 { 直连=主块
    sticky_at = src.index("#montabs{position:sticky;top:var(--hdh,54px")
    assert sticky_at > main761
    # 桌面档形态唯一：源码更后的同形声明会按层叠序劫持
    assert src.count("#montabs{position:sticky;top:var(--hdh,54px") == 1
    # 固定校准块退役：带内覆写（固定 top/补偿像素）不得回流——
    # 回流即 reintroduce 实高漂移下的遮挡缺陷
    assert ("@media(min-width:761px) and (max-width:900px)"
            not in src)


def test_transfer_column_conditional_hide():
    """中转列条件隐藏：CSS 选择器与 table() 按当前结果集切类成对。"""
    src = _src()
    assert "#ftable.no-transfer th:nth-child(8)" in src
    assert "rows.every(f=>!f.transfer)" in src
    assert src.count("no-transfer") >= 3   # CSS 类名 + JS toggle×2 处


def test_glb_ranges_single_source_table():
    """配置校验单源表：glbCheck 输入即校验、saveCfg 复用同表、
    glcell 数字项挂 oninput、越界红边与行内提示样式在位。"""
    src = _src()
    assert "const GLB_RANGES=[" in src
    assert "function glbCheck(el,returnMsg)" in src
    assert 'oninput="glbCheck(this)"' in src
    savecfg = src[src.index("async function saveCfg()"):]
    assert "for(const r of GLB_RANGES)" in savecfg[:600]
    assert ".glcell input.invalid" in src
    assert ".glcell .verr" in src


def test_price_font_size_tier():
    """价格字号阶梯：cozy 档放大、compact 档不命中（密度语义保留）。

    原断言把 15px 写死；字号阶统一后主价格走 16px（10/11/12/13/14/16/18/22
    七阶之一）。守的是「cozy 档单独放大且大于正文 13px、compact 档不覆盖」，
    不钉死具体像素。
    """
    import re
    src = _src()
    m = re.search(r":root:not\(\[data-density=compact\]\) #ftable td\.price\{font-size:(\d+)px\}", src)
    assert m, "明细价格 cozy 档字号阶梯缺席"
    px = int(m.group(1))
    assert px > 13, "明细价格 cozy 档 %dpx 未与正文 13px 拉开主次" % px
    assert px in {14, 16, 18}, "明细价格 cozy 档 %dpx 不在七阶内" % px


def test_riskpolicy_whitelist_and_badge():
    """ctrip 高风险政策透明标记消费端：API 白名单 strip 门 + 价格格
    ⚠ 徽标（warn 色与 title 风险说明在位；词面不加「价」尾——它是
    政策风险标记不是资格价语义）。"""
    src = _src()
    assert '"riskPolicy": (f.get("riskPolicy") or "").strip(),' in src
    assert ('f.riskPolicy?`<span class="pretax" style="color:var(--warn);'
            'cursor:help" title="渠道标注的高风险政策价') in src
    assert "⚠${he(f.riskPolicy)}</span>" in src


def test_demo_riskpolicy_sample():
    """demo 演示样本：首行 riskPolicy 在场（演示页价格格徽标目检点）。"""
    import webui
    demo = pathlib.Path(
        os.path.join(os.path.dirname(webui.__file__), "core", "demo.py")
    ).read_text(encoding="utf-8")
    assert 'fs[0]["riskPolicy"] = "高风险政策"' in demo


def test_details_tabs_scroll_hint():
    """P1-W1 ≤540 明细吸顶条横滚暗示与筛选入口常在：::after 装饰层
    渐隐挂 xhint 类点亮（不用容器 mask——mask 会把 sticky 的 fltBtn
    一起淡出）；fltBtn sticky 钉可视右缘（筛选抽屉 ≤760 唯一入口
    不依赖滚动可达）。"""
    src = _src()
    assert "#montab-details .tabs::after" in src
    assert "#montab-details .tabs.xhint::after" in src
    assert "#montab-details .tabs>#fltBtn{position:sticky;right:0" in src
    # 四处组合选择器 xhint 判定循环（showMonTab health 分支/
    # renderHealth/resize debounce/switchView，同判定
    # scrollWidth>clientWidth+4）选择器扩展覆盖明细条
    assert src.count(".hcells,#montab-details .tabs") >= 4
    # 第 5 处循环：showMonTab details 分支独立明细条判定（首渲在
    # 隐藏容器 sw=0，切回补一拍）——组合计数钉罩不住它，独立钉。
    # r253 起 .tw（表内横滚提示）并入同批
    assert ("if(t==='details')document.querySelectorAll("
            "'#montab-details .tabs,.tw')") in src


def test_footer_link_hover():
    """M1 页脚/演示条链接 hover 反馈（与 NOTIFY 轻页同位对齐，
    自约「真实可点链接悬停零反馈」属缺陷）。"""
    src = _src()
    assert "#foot a:hover,.demoBar a:hover{text-decoration:underline}" in src


# ---- merged from tests/test_v15113_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_showmontab_hash_keeps_user_segment():
    """showMonTab 的 URL 深链同步带 /uN：tab 写点不再覆写掉
    pickUser 落下的用户段（M-1）；且写点带 !silent 门——silent 档
    （启动恢复唯一调用点）不写 hash，防未恢复的 U=0 污染深链用户段
    与回访者 localStorage 态（Soldier P0）。"""
    src = _src()
    assert re.search(
        r"if\(!silent\)\{try\{const _u='#'\+t\+'/u'\+U;if\(hist===false\)history\.replaceState",
        src), "showMonTab 尾部 replaceState 未带 /uN 用户段或缺 !silent 门"


def test_startup_restore_parses_user_segment():
    """启动块解析 #tab/uN 双段：tab 段跟深链（P2-①，此前只认裸 tab、
    深链 tab 落空）；且仅当 hash 本身无合法 tab（localStorage 回退档）
    才补写裸 tab hash——有合法 tab 时保持原 hash 零污染。"""
    src = _src()
    i1 = src.index("启动恢复：URL 深链优先于 localStorage")
    i2 = src.index("hashchange 消费")
    body = src[i1:i2]
    assert re.search(r"indexOf\('/u'\)", body), "启动块未解析 /u 段"
    assert re.search(r"indexOf\(_ht\)<0", body), \
        "启动块裸 tab 补写缺少「hash 无合法 tab」条件门"


def test_pickuser_hash_write_intact():
    """pickUser 自身写点形态不受扰动（#tab/uN 原样）。"""
    src = _src()
    assert re.search(
        r"replaceState\(null,'','#'\+MONTAB\+'/u'\+i\)", src)


def test_jumpcaldate_reset_toast():
    """jumpCalDate 内 resetFlt 后有重置告知 toast（M-2；与 jumpQual/
    mchip 同族词面「已重置现有筛选」）。"""
    src = _src()
    i1 = src.index("function jumpCalDate")
    i2 = src.index("function jumpTrendDetail")
    body = src[i1:i2]
    assert "resetFlt()" in body
    assert "已重置现有筛选" in body, "jumpCalDate 缺重置筛选告知 toast"


def test_expcsv_success_toast():
    """expCsv 成功路径有 toast（增强③，与 exportCfg 成功反馈同律，
    行数随行）。"""
    src = _src()
    i1 = src.index("function expCsv")
    i2 = src.index("let _ROWS")
    body = src[i1:i2]
    assert "a.click()" in body
    assert "已导出" in body, "expCsv 缺导出成功 toast"


def test_agepolicy_title_enumeration_covers_word_family():
    """agePolicy ⚠ title 枚举覆盖现役词族（含协议/成团人数）：
    词面透传型字段的读屏解释口径随词族演进（Soldier P2-2）。"""
    src = _src()
    assert "航司协议/成团人数" in src
    assert "资格受限专享价" in src


# ---- merged from tests/test_v15130_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


# ---------------- P2-1 K线图例色票 ----------------

def test_p21_legend_series_spans_have_ids():
    s = src()
    assert 'id="lgDirect"' in s, "直飞系列色票缺锚点 id"
    assert 'id="lgTrans"' in s, "中转系列色票缺锚点 id"


def test_p21_chart_toggles_series_swatch_by_mode():
    body = re.search(r"function chart\(\)", src())
    assert body, "chart() 不在源码"
    seg = src()[body.start():body.start() + 9000]
    assert "lgDirect" in seg and "lgTrans" in seg, \
        "chart() 未随模式切换系列色票显隐"
    assert seg.count("'none'") >= 2 or seg.count('"none"') >= 2, \
        "K线模式未隐藏系列色票"


def test_p21_ringnote_kline_cluster_semantics():
    body = re.search(r"function chart\(\)", src())
    seg = src()[body.start():body.start() + 9000]
    assert "左簇=直飞" in seg and "右簇=中转" in seg, \
        "K线 ringNote 缺簇位语义（系列靠左右簇区分却无一字说明）"


# ---------------- P2-2 KPI 主数字文字级令牌 ----------------

def test_p22_kpi_num_text_tokens():
    s = src()
    assert ".kpi.t .num{color:var(--orange-txt)}" in s, \
        "橙档主数字未换文字级令牌（3.78 全站正文级最低）"
    assert ".kpi.hit .num{color:var(--ok-txt)}" in s, \
        "达标主数字未收 --ok-txt 族（12px 小字已收，主角反停裸令牌）"
    assert "--orange-txt:#a45508" in s, "亮色文字级橙令牌缺失（5.41:1）"
    assert "--orange-txt:#e6922e" in s, "暗色成对换谱缺失（=暗 --orange 本值）"


# ---------------- P2-3 选中态 hover 反馈 ----------------

def test_p23_on_hover_family_rule_and_cascade_position():
    s = src()
    rule = (".tabs span.on:hover,nav span.on:hover,.chip.on:hover,\n"
            " .rngchip.on:hover,.cnav.on:hover{filter:brightness(1.07)}")
    pos = s.find(rule)
    assert pos >= 0, "选中态 hover 族规则缺失或 rngchip/cnav 成员脱落"
    # 级联位次：族规则必须声明在全部同族 .on 基础规则之后（同特异性
    # 后者胜；filter 无既有声明，置尾即胜）
    for base in (".tabs span.on{", "nav span.on{", ".chip.on{",
                 ".rngchip.on{", ".cnav.on{"):
        b = s.find(base)
        assert b >= 0 and b < pos, f"族规则未置尾于 {base} 之后"


# ---- merged from tests/test_v15132_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


def test_demobar_link_nowrap():
    """demoBar 链接词组粒度 nowrap：CJK 窄带断词孤字（「下载源 /
    码或发行包」）是门面缺陷；链接 9 字 ≈117px，390 档容器
    342px 容得下无溢出风险。"""
    m = re.search(r"\.demoBar a\{[^}]*\}", src())
    assert m, ".demoBar a 规则不在源码"
    assert "white-space:nowrap" in m.group(0), \
        "demoBar 链接缺词组粒度 nowrap（CJK 断词）"


def _lum(hexc):
    """WCAG 相对亮度（sRGB 线性化）。"""
    def _ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _ch(int(hexc[0:2], 16)) + \
        0.7152 * _ch(int(hexc[2:4], 16)) + \
        0.0722 * _ch(int(hexc[4:6], 16))


def _contrast(fg, bg):
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_brk_zebra_solid_contrast():
    """brk 第四档改实心 --ok-txt + 点线下划：DPR1 下不再空心发糊。
    对斑马底 (--rowalt) 必须 ≥4.5（AA 正文）且留有余量。"""
    m = re.search(
        r"\.price\.brk\{color:var\(--ok-txt\);text-decoration:underline dotted",
        src())
    assert m, "brk 实心+点线规则缺失（空心描边曾发糊）"
    assert "-webkit-text-stroke:1.1px var(--green)" not in src(), \
        "空心描边旧规则残留"
    # 变量值算术复算：亮色 --ok-txt #0b6e39 对斑马 --rowalt #f5f8fb
    c = _contrast("0b6e39", "f5f8fb")
    assert c >= 4.5, f"--ok-txt 对斑马底 {c:.3f} 欠 AA"
    assert c >= 5.0, f"--ok-txt 对斑马底 {c:.3f} 余量不足"


def test_switch_focus_visible_ring():
    """开关焦点环显式接管：.switch 族 checkbox 曾走 UA 默认环，
    与全站 2px 蓝环双轨（焦点观感不齐）。outline 形态（box-shadow
    对 appearance:none 件微晕不可辨是既有豁免理由）。"""
    m = re.search(r"\.switch:focus-visible\{[^}]*\}", src())
    assert m, ".switch:focus-visible 规则不在源码"
    assert "outline:2px solid var(--blue)" in m.group(0), \
        "开关焦点环未显式接管"


def test_opscard_muted_below_actions():
    """opscard 系统行为说明下沉独立行：说明文字曾嵌在四个动作按钮
    行尾（主次混排）——移到 userPills 容器之后独占整行。
    （r244 P2-1 钉面随行为演进改写：内联样式挪基础 CSS 挪 id=opsHint，
    独占整行语义由 #opscard .row>.muted{display:block;width:100%}
    承载，钉面同轮对齐、语义担保保留）"""
    s = src()
    muted = s.find('id="opsHint"')
    assert muted > 0, "opscard 说明行未下沉（独立行形态）"
    assert "#opscard .row>.muted{display:block;width:100%" in s,         "说明行独占整行语义未落在基础 CSS"
    pills = s.find('id="userPills"')
    assert 0 < pills < muted, "说明行应在 userPills 容器之后"
    seg = s[s.find('id="opscard"'):muted]
    assert "推送记录</button>" in seg, "说明行与按钮行之间缺换行载体"


# ---- merged from tests/test_v168_webui.py ----

class TestWebuiV168Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_cal_qual_solid_green_light_theme(self):
        """P1-1a：亮色真达标实色底保白字（rgba 合成白字最低 3.91 欠 AA）。

        r249 演进：实色形态从 CSS 活变量 'var(--green)'（直接翻主题
        不重渲时白字衬亮绿 2.33 欠 AA）升为运行时实色 'rgb('+CG+')'
        （渲染时刻 --green 实值），语义不变、主题翻转面收口。"""
        assert "bg=DK?'rgba('+CG+',.88)':'rgb('+CG+')'" in self._src()

    def test_cal_breakline_light_dark_text_alpha_cap(self):
        """P1-1b：破线 alpha 上限 + 深浅字（收 0.60+暗色 FGDK 分支
        → 案结收 0.53 且亮暗恒 var(--tx)；修正衬底
        为 --card 后 0.56 仍欠 → 0.53）。"""
        src = self._src()
        assert "const a=0.25+Math.min(0.28,(1-r)*2.2);" in src
        assert "bg='rgba('+CG+','+a.toFixed(2)+')';\n    fg='var(--tx)';}" in src

    def test_cal_overline_light_dark_text_alpha_cap(self):
        """P1-1c：超线 alpha 上限 0.56（min(0.40,…)）+ 亮暗统一
        var(--tx)（暗色 FGDK 对暗红合成底 2.42~2.62 曾倒退，收编；
        上限 0.56：0.60 时暗色最深格小字 4.39 欠 AA）。"""
        src = self._src()
        assert "const a=0.16+Math.min(0.40,(r-1)*0.9);" in src
        assert "fg='var(--tx)';}}" in src

    def test_cal_near_price_warn_deep(self):
        """P1-1d：擦边价字 --warn-deep（--warn 亮色对琥珀 tint 3.31 欠）。"""
        assert ".calcell .cp.near{color:var(--warn-deep)}" in self._src()

    def test_dn_down_delta_uses_ok_txt(self):
        """：.dn 降绿字 --ok-txt（--ok-strong 白卡 4.21/okbg 3.73 欠）。"""
        assert ".dn{color:var(--ok-txt);font-weight:600}" in self._src()

    def test_health_empty_recycles_card_and_err_wording(self):
        """：空态/错误态回收 healthcard + 错误词面不冒充空态。"""
        src = self._src()
        assert "$('healthcard').style.display='none';" in src
        assert "'⚠ 健康数据读取失败（详见服务日志）'" in src

    def test_loadcfg_users_shape_guard_cfgerr(self):
        """：loadCfg users 形状守卫落 catch + cfgErr 双通道。
        （锚定 catch 段：buildForm 与 catch 之间插入 aria
        后处理块，cfgErr 双通道行为不变；r236 P2-1 起 catch
        追加 #cfgglobals 错误态落点——静态「加载中…」骨架的
        失败分支落点，cfgErr 双通道语义保留）"""
        src = self._src()
        assert "if(!j||!Array.isArray(j.users))throw new Error('配置接口响应异常');" in src
        assert "catch(e){cfgErr('配置读取失败: '+e);" in src
        assert "_cg=$('cfgglobals')" in src

    def test_fbar_focus_not_switch(self):
        """：.fbar input:focus:not(.switch)（开关 UA 焦点环豁免）。"""
        assert ".fbar select:focus,.fbar input:focus:not(.switch){outline:none;" \
            in self._src()

    def test_cal_hint_conditional_on_link_cell(self):
        """：日历纯展示——格级点击跳转两域不相交恒不可用，死通道
        （dfull/calcell.link/点击格提示）整体收口，提示词面全页不在。"""
        src = self._src()
        assert ('<span style="white-space:nowrap">红=超线（格底）</span></span>\';' in src
                and "点击格看该日明细" not in src)

    def test_pulse_head_click_hint(self):
        """：脉冲卡头补「点击柱跳渠道健康」。"""
        assert "悬停看明细 · 点击柱跳渠道健康" in self._src()


# ---- merged from tests/test_v170_webui.py ----

class TestWebuiV170Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def _notify_src(self):
        import webui as _w
        src = self._src()
        i = src.index("NOTIFY_PAGE")
        return src[i:]

    def test_pill_token_defined_and_six_consumers(self):
        """P2-C：--pill 令牌单源 + 六处消费并轨，20/18/999px 硬编码归零。"""
        src = self._src()
        assert "--pill:999px" in src, "主站 :root 缺 --pill 令牌"
        # 消费端：CSS 区五选择器逐个点名（border-radius:var(--pill)）
        import re
        m = re.findall(r"\.(tag|switch|hbadge|upill|mchip)\{[^}]*?"
                       r"border-radius:var\(--pill\)", src)
        assert sorted(set(m)) == ["hbadge", "mchip", "switch", "tag", "upill"], \
            "主站胶囊五选择器消费不全: %s" % m
        # notify 页 .md a 消费
        nsrc = self._notify_src()
        assert "border-radius:var(--pill)" in nsrc, "notify .md a 未并轨"
        # notify 页:root 补定义（漏补→computed 塌 0，uitest CTA 钉先红）
        assert "--pill:999px" in nsrc, "notify 独立 :root 缺 --pill（CTA 圆角塌 0 先例）"
        # 硬编码残留归零（含 20px/18px 旧写法；50% 圆形/微元素 1~8px 不在列）
        resid = re.findall(r"border-radius:(?:20|18|999)px", src)
        assert not resid, "胶囊家族硬编码残留: %s" % resid

    def test_glsec_normalized_to_subsec(self):
        """P2-A：glsec 输出 class="subsec"（hairline 收尾线+margin 归一）。"""
        src = self._src()
        assert "const glsec=(t,fold)=>'<div class=\"subsec\"'" in src, \
            "glsec 未归一 subsec"
        assert 'glsec' in src and src.count('class="glsec"') == 0
        # .subsec 基线仍带 hairline（归一收益的本体）
        assert ".subsec::after{content:'';flex:1;height:1px;background:var(--line)}" in src

    def test_glcell_padding_12_14(self):
        """P2-B：.glcell 内衬并入 12px 14px（与 .lgcard/.chcard 同档）。"""
        src = self._src()
        assert ".glcell{border:1px solid var(--line);border-radius:var(--r2);" \
               "padding:12px 14px;" in src
        # 11px 垂直档仅余表头/按钮等非卡容器形态（audit 盘点对象为卡容器）；
        # 登录双端弹窗头 .lgmodal-h 属于表头形态，允许保留 11px 14px
        bad = [ln for ln in src.splitlines()
               if "padding:11px 14px" in ln and ".lgmodal-h" not in ln]
        assert not bad, "glcell 11px 游离档残留: %s" % bad[:2]

    def test_toast_hover_rule(self):
        """P2-E：.toast:hover{background:var(--hover)} 与 .pvx 同语言。"""
        src = self._src()
        assert ".toast:hover{background:var(--hover)}" in src


# ---- merged from tests/test_v172_webui.py ----

class TestWebuiV172Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p1_threshold_loop_iterates_keys_not_chars(self):
        """：阈值校验循环迭代键数组，圆括号字符串迭代死码消失。"""
        src = self._src()
        assert "for(const k of ['alert_direct','alert_transfer']){" in src, \
            "阈值校验未用数组字面量（逗号表达式退化为字符迭代＝校验恒死码）"
        assert "for(const k of ('alert_direct','alert_transfer')){" not in src, \
            "圆括号逗号表达式形态仍在（校验死码回潮）"

    def test_p2a_xhint_rerun_on_health_tab(self):
        """P2-A：showMonTab 补 health 分支重跑（隐藏容器首渲死档）。
        钉面随判定族演进更新（.hcells→明细吸顶条→#montabs→r247
        #opscard .opsbtns，同判定；r322 起该批次回调收敛到 _hfit
        单源——.hcells 成员走弹性实判定+滚动暗示，其余成员函数内
        保持原 xhint 判定，语义担保不变）。"""
        src = self._src()
        assert ("if(t==='health'){document.querySelectorAll("
                "'.hcells,#montab-details .tabs,#montabs"
                ",#opscard .opsbtns').forEach(_hfit);") in src, \
            "showMonTab 缺 health 分支批次重跑（主路径渐隐死档回潮）"
        # v1.5.274：激活时补滚最新一轮（隐藏容器首渲 scrollWidth=0）
        assert ("if(window.innerWidth<=760)document.querySelectorAll("
                "'#hbody .hcells').forEach(x=>{try{x.scrollLeft="
                "x.scrollWidth}catch(_){}})") in src, \
            "health 激活未补滚最新轮"
        # 禁复活：内联匿名回调形态（弹性实判定从批次旁路=fit 恒缺席）
        assert ("if(t==='health')document.querySelectorAll("
                "'.hcells,#montab-details .tabs,#montabs"
                ",#opscard .opsbtns')"
                ".forEach(x=>x.classList.toggle('xhint',"
                "x.scrollWidth>x.clientWidth+4));") not in src

    def test_p2b_dates_full_select_not_counted(self):
        """P2-B：dates 全选不计筛选数（与 plats/routes 守卫同构）。"""
        src = self._src()
        assert "if(FLT.dates.size&&FLT.dates.size<ds.length)n++;" in src, \
            "dates 缺 size<ds.length 守卫（全选回填幻影计数回潮）"
        # 旧形态（无守卫早计）必须消失
        assert "if(FLT.dates.size)n++;" not in src, \
            "dates 无守卫早计仍在（幻影「筛选 1」回潮）"

    def test_p2b_single_date_early_exit_clears_dates(self):
        """P2-B 伴随：单日期早退清 FLT.dates（跨用户残留致过滤全灭）。"""
        src = self._src()
        assert "if(ds.length<2){box.innerHTML='';FLT.dates=new Set();return;}" in src, \
            "buildDateChips 单日期早退未清 FLT.dates（跨用户残留过滤全灭）"

    def test_p2b_single_route_early_exit_clears_routes(self):
        """P2-B 同族（采纳）：单航线早退清 FLT.routes——
        buildRouteChips 与 buildDateChips 同病对称（跨用户切到单航线
        用户时 routes 残留同样致明细过滤全灭，saveUI 无条件恢复）。"""
        src = self._src()
        assert "if(rs.length<2){box.innerHTML='';FLT.routes=new Set();return;}" in src, \
            "buildRouteChips 单航线早退未清 FLT.routes（与 dates 同病不对称回潮）"

    def test_p2c_buildform_focus_restore(self):
        """P2-C：buildForm 重建前快照 activeElement.id、重建尾回焦。"""
        src = self._src()
        assert "_fkid=(_fae&&_fae.id)?_fae.id:null;" in src, \
            "buildForm 缺 activeElement.id 快照（回车加日期后焦点坠 body）"
        assert "if(_fkid){const _fe=document.getElementById(_fkid);" \
               "if(_fe)_fe.focus({preventScroll:true});}" in src, \
            "buildForm 缺重建尾回焦（键盘连续录入流断裂回潮）"


# ---- merged from tests/test_v174_webui.py ----

class TestWebuiV174Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p1_1440_breakpoint_unlocks_nonratio_parts(self):
        """：非比例敏感件随 1280 渐进带解锁（解锁与 wrap 托底释放
        同拍，渐进带内空腔归零）。"""
        src = self._src()
        # 上限统一 min(1716px,max(1180px,92vw))（渐进+托底封顶连续
        # 函数）——放宽语义保持，断点随托底释放点同步 1280。
        # r302 W1：纯 none 退役（≥1726 双轴回潮病灶形态），四族同上限
        assert (".statline,#pulseLegend,.pulsewrap"
                "{max-width:min(1440px,100%)}" in src
                and "max-width:min(1716px,max(1180px,92vw))" in src), \
            "1280 放宽行丢失（断点缝空腔回潮）"
        # 放宽行必须出现在 1280 media 声明之后、1920 块之前
        i1280 = src.index("min-width:1280px")
        i_unlock = src.index(
            ".statline,#pulseLegend,.pulsewrap{max-width:min(1440px,100%)}")
        i1920 = src.index("min-width:1920px")
        assert i1280 < i_unlock < i1920, \
            "放宽行不在 1280 块内（仍在 ≥1920 独占=断点缝残留）"

    def test_p2_clickable_cells_use_pointer_cursor(self):
        """：.hc/.pbar 点击有动作必须 pointer（help 反信号回潮）。"""
        src = self._src()
        hc = src.index(".hc{width:6px")
        pbar = src.index(".pbar{flex:1")
        assert "cursor:help" not in src[hc:hc + 200], \
            ".hc 仍挂 cursor:help（点击开日志弹层与光标语义失配）"
        assert "cursor:help" not in src[pbar:pbar + 200], \
            ".pbar 仍挂 cursor:help（点击跳渠道健康与光标语义失配）"

    def test_p3_pvbody_link_hover_feedback(self):
        """：推送预览正文链接有 hover 反馈（可点无反馈回潮）。"""
        src = self._src()
        assert ".pvbody a:hover{text-decoration:underline}" in src, \
            ".pvbody a 缺 hover 反馈（与 .toast:hover/a.vw:hover 同族律）"

    def test_p4_stl_segment_separator_two_levels(self):
        """：明细子行段间 ' ｜ ' 与段内 '·' 两级分明（同符歧义回潮）。"""
        src = self._src()
        assert "].filter(Boolean).join(' ｜ ')}</div>" in src, \
            "明细 .stl 子行段间分隔未升级 ' ｜ '（与段内 '·' 同符歧义）"
        # 段内 '·' 复合词保持不动（廊桥43%·机龄N年 同段内小层）
        assert "'·廊桥'+he(String(f.bridgeRate))+'%'" in src, \
            "段内 '·' 小层被误改（两级分隔律：段间 ｜/段内 ·）"


# ---- merged from tests/test_v176_webui.py ----

class TestWebuiV176Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p1_mark_stale_defined_and_called_on_fetch_failure(self):
        """：_markStale 定义在位且 fetch 失败冷启动分支必调（假等待回潮）。"""
        src = self._src()
        assert "function _markStale(" in src, "_markStale 帮手丢失"
        i_load = src.index("async function load()")
        i_catch = src.index("catch(e){LASTTXT", i_load)
        i_fin = src.index("finally{LOADN=false;}", i_catch)
        cseg = src[i_catch:i_fin]
        assert "if(S)" in cseg, "catch 分支未按有无旧数据分叉（有旧数据被掀卡）"
        assert "_markStale()" in cseg, \
            "load() catch 冷启动分支未调 _markStale（错误态骨架不同步）"
        assert "_markStale()" not in cseg[:cseg.index("else{")], \
            "有旧数据分支不得掀骨架（保陈旧数据交互不失效）"

    def test_p1_stale_covers_three_skeletons_no_fake_loading(self):
        """：三处骨架全覆盖，且错误态文案不再含「加载中」字样。"""
        import re
        src = self._src()
        i0 = src.index("function _markStale(")
        i1 = src.index("async function load()", i0)
        body = src[i0:i1]
        for dom_id in ("ftable", "loginRows", "cfgglobals"):
            assert dom_id in body, f"骨架 #{dom_id} 未覆盖（假等待残留）"
        assert "(svc||'服务未启动')+'，恢复后自动刷新'" in body, "错误态文案丢失"
        m = re.search(r"const msg=\(svc\|\|'[^']+'\)\+'([^']+)'", body)
        assert m and "加载中" not in m.group(1), \
            "错误态文案不得再出现「加载中」（注释提及不受限）"

    def test_p2_focus_return_chain_intact(self):
        """撤案正面钉：closePv 焦点回送链（_PV_RETURN→focus）在位。"""
        src = self._src()
        assert "function _openPvMask(){_PV_RETURN=document.activeElement;" in src, \
            "开弹层入口未记录 _PV_RETURN（回送链源头缺失）"
        assert "const ret=_PV_RETURN;_PV_RETURN=null;" in src \
            and "ret.focus()" in src, "closePv 焦点回送链丢失"


# ---- merged from tests/test_v184_webui.py ----

class TestSrvHandleError:
    """_Srv.handle_error 断连族静默契约。"""

    @staticmethod
    def _srv():
        import webui as _w
        return _w._Srv(("127.0.0.1", 0), _w._Handler)

    def test_client_disconnect_is_silent(self):
        srv = self._srv()
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                try:
                    raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接")
                except ConnectionResetError:
                    srv.handle_error(None, ("127.0.0.1", 51000))
            assert "Traceback" not in err.getvalue(), \
                "断连族仍打 traceback（err 文件刷屏病面未收口）"
        finally:
            srv.server_close()

    def test_real_defect_stays_visible(self):
        srv = self._srv()
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                try:
                    raise ValueError("真缺陷哨兵")
                except ValueError:
                    srv.handle_error(None, ("127.0.0.1", 51000))
            out = err.getvalue()
            assert "Traceback" in out and "真缺陷哨兵" in out, \
                "非断连异常被静默（真缺陷必须可见的契约被破坏）"
        finally:
            srv.server_close()

    def test_server_survives_abrupt_client(self):
        srv = self._srv()
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            # 连上即断（不发请求）：handler 读侧得空串走正常关闭路径
            c = socket.create_connection(("127.0.0.1", port), timeout=5)
            c.close()
            time.sleep(0.2)
            # 服务器必须存活并继续服务后续请求（空代理直连回环）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/api/pulse", timeout=10) as r:
                assert r.status == 200
        finally:
            srv.shutdown()
            srv.server_close()


class TestAuditV184Fixes:
    """audit_v184 P1-1/P2-1 源码钉。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_trend_markmin_price_domain(self):
        src = self._src()
        i0 = src.index("const markMin=")
        seg = src[i0:i0 + 200]
        # 走势「低」标注按价域（p[2]）取 argmin——y 像素域（p[1]）
        # 因 canvas y 向下会反向锚到窗口最高价（决策语义反转）
        assert "p[2]<pts[mi][2]" in seg, "markMin 未按价域取最低"
        assert "p[1]<pts[mi][1]" not in seg, "markMin 仍在 y 像素域比较"

    def test_cal_best_qhit_outline_token(self):
        src = self._src()
        assert ".calcell.best.qhit{outline-color:var(--cal-best-stroke)}" in src, \
            "best×qhit 叠加态缺描边配色分支（绿描边压绿底隐形）"
        # 双主题令牌成对
        assert "--cal-best-stroke:rgba(255,255,255,.8)" in src, "亮色描边令牌缺"
        assert "--cal-best-stroke:rgba(10,15,22,.55)" in src, "暗色描边令牌缺"


# ---- merged from tests/test_v192_webui.py ----

class TestWebuiV192Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- 修 1：弹层开合零布局位移 ----

    def test_scrollbar_gutter_stable(self):
        """viewport gutter 常驻：现代 Chrome/Edge 弹层开合内容零横移。"""
        src = self._src()
        assert "scrollbar-gutter:stable" in src, \
            "html 缺 scrollbar-gutter:stable（弹层开合仍会横移）"

    def test_pv_mask_scroll_compensate(self):
        """老内核兜底：锁滚前量滚动条宽垫 padding-right，关弹层复位。"""
        src = self._src()
        i0 = src.index("function _openPvMask()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert ("window.innerWidth-document.documentElement.clientWidth") \
            in seg, "_openPvMask 缺滚动条宽度测量（老内核仍横移）"
        assert "paddingRight" in seg, "_openPvMask 缺 padding-right 补偿"
        # closePv 必须复位补偿，否则关弹层后右侧多一条空白垫
        j0 = src.index("function closePv()")
        j1 = src.index("function ", j0 + 10)
        jseg = src[j0:j1]
        assert "paddingRight=''" in jseg, "closePv 未复位 padding-right"

    # ---- 修 2：明细表切片渲染 ----

    def test_table_chunked_render(self):
        """table() 首拍只渲首屏切片，滚动续载取代 300 行一次性重建。"""
        src = self._src()
        i0 = src.index("function table()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert "const CAP=300" not in seg, \
            "旧 300 行一次性截断仍在（点击卡顿根因未除）"
        assert "_chunkHtml(0)" in seg, "table() 未接入首屏切片"
        assert "_tblAppend" in seg, "table() 滚动位深于首屏时未补切片"
        assert "function _tblAppend" in src, "缺切片续载单源函数"
        assert "const _CHUNK=" in src, "缺切片尺寸常量"
        assert "function _chunkHtml" in src, "缺切片 HTML 构建单源"
        # 续载行不再播入场动画（滚动追加行延迟渐显=越滚越"卡"的观感）
        assert "animation:none" in src.split("function _chunkHtml")[1] \
            .split("function ")[0], "续载切片行缺 animation:none"

    def test_table_scroll_append_listener(self):
        """.tw 滚动近底预取下一切片（passive 不阻塞滚动合成）。"""
        src = self._src()
        assert ("#tablecard .tw") in src, "缺滚动容器监听锚"
        i0 = src.index(
            "document.querySelector('#tablecard .tw').addEventListener('scroll'")
        # 窗口锚到监听器块边界而非固定字符数（LESSONS 卅一§3：块内合法
        # 增厚——如 r314 P3-1 滚动态投影开关行——不该把钉面推出窗口）
        i1 = src.index("},{passive:true});", i0) + len("},{passive:true});")
        seg = src[i0:i1]
        assert "{passive:true}" in seg, "滚动监听缺 passive（合成器阻塞）"
        assert "_tblAppend" in seg, "滚动监听未接续载"

    # ---- 修 3：弹层开着跳过整拍轮询 ----

    def test_load_defer_while_popup(self):
        """弹层开着 load() 整拍跳过：背后重渲闪帧 + 抢主线程。"""
        src = self._src()
        i0 = src.index("async function load()")
        i1 = src.index("LOADN=true", i0)
        seg = src[i0:i1]
        assert ("$('pvMask').classList.contains('on')") in seg, \
            "load() 未在弹层开启时整拍跳过"


# ---- merged from tests/test_v284_fliggy_intl.py ----

_LOG = logging.getLogger("t_v284_fliggy")


def _item(**over):
    base = {
        "nameLine": "春秋航空 9C7293", "tips": "中型机321",
        "depTime": "22:25", "arrTime": "02:20", "cross": "+1天",
        "depAirport": "浦东国际机场T2", "arrAirport": "素万那普国际机场",
        "duration": "约4时55分", "priceText": "机票价格745元",
        "priceNum": "含税￥745", "taxText": "￥457", "quantity": "1张",
        "trans": "", "segs": 1,
    }
    base.update(over)
    return base


def test_parse_intl_items_maps_and_dedupes():
    items = [
        _item(),
        _item(),  # 同班同价重复渲染
        _item(nameLine="泰国越捷航空 VZ3525", priceText="机票价格803元",
              priceNum="含税￥803", taxText="￥500", depTime="02:30",
              arrTime="06:30", cross=""),
        _item(nameLine="坏行 123", depTime="", arrTime=""),
        _item(nameLine="坏价 XX123", priceText="机票价格0元"),
    ]
    rows = FliggyCrawler._parse_intl_items(items, "2026-11-16")
    assert len(rows) == 2
    first = [r for r in rows if r["code"] == "9C7293"][0]
    assert first["name"] == "春秋航空"
    assert first["depTime"] == "22:25" and first["arrTime"] == "02:20"
    assert first["price"] == 745 and first["tax"] == 457
    assert first["depAirport"] == "浦东国际机场T2"
    assert first["totalDuration"] == "4时55分"
    assert first["depDate"] == "2026-11-16" and first["intl"] == 1
    assert first["crossDayDesc"] == "+1天"


def test_intl_pc_first_then_calendar_for_missing_dates(monkeypatch):
    f = FliggyCrawler({}, _LOG)
    row = FliggyCrawler._parse_intl_items([_item()], "2026-11-16")[0]
    monkeypatch.setattr(f, "_fetch_intl_pc",
                        lambda fc, tc, dates: {"2026-11-16": [row],
                                               "2026-11-17": []})
    seen = {}

    def _cal(fc, tc, dates, fc0, tc0, ret=""):
        seen["dates"] = list(dates)
        return []

    monkeypatch.setattr(f, "_fetch_intl_calendar", _cal)
    out = f._fetch_intl("SHA", "BKK", ["2026-11-16", "2026-11-17"])
    assert len(out) == 1 and out[0].depart_date == "2026-11-16"
    assert out[0].price == 745 and out[0].flight_no == "9C7293"
    assert seen["dates"] == ["2026-11-17"]


def test_intl_pc_empty_uses_calendar(monkeypatch):
    f = FliggyCrawler({}, _LOG)
    from crawlers.base import FlightPrice
    monkeypatch.setattr(f, "_fetch_intl_pc",
                        lambda fc, tc, dates: {d: [] for d in dates})
    monkeypatch.setattr(f, "_fetch_intl_calendar",
                        lambda fc, tc, dates, fc0, tc0, ret="": [
                            FlightPrice(platform="fliggy", from_city="SHA",
                                        to_city="BKK", depart_date=dates[0],
                                        price=799.0, airline="", flight_no="",
                                        depart_time="", arrive_time="",
                                        extra="[]")])
    out = f._fetch_intl("SHA", "BKK", ["2026-11-16"])
    assert len(out) == 1 and out[0].price == 799.0


def test_login_card_bottom_alignment_and_capbar_sync_pins():
    import pathlib
    import webui
    src = webui_full_src()
    assert ".lgcard .btn2{margin:auto 0 0;width:100%;justify-content:center}" in src
    assert "function channelAuthView(p){" in src and "function loadChannelState(force){" in src
    assert "channelAuthView(p).needsLogin" in src and "本次无结果" in src
    assert "会话待重登" not in src


def test_tuniu_domestic_login_wall_and_session_injection_pins():
    import pathlib
    import webui
    from crawlers.tuniu import TuniuCrawler
    assert TuniuCrawler.login_suspect in (True, False)
    src = pathlib.Path(webui.__file__).parent.joinpath(
        "crawlers", "tuniu.py").read_text(encoding="utf-8")
    assert "login_suspect = False" in src
    assert "def _saved_session_cookies(self)" in src
    assert "710114" in src and "国内接口 710114 请登录" in src
    assert "self._install_tac_cookies(client)" in src
    ui = webui_full_src()
    # 2026-10-27 起废弃「建议/国内需/国际需」分档：全渠道必须登录，
    # 差异只在会话槽位。原来这条钉的是旧档位，已按新口径改写。
    assert "tuniu:'必须'" in ui
    assert "tuniu:'国内需'" not in ui


def test_tongcheng_session_evidence_and_density_pins():
    import pathlib
    import webui
    from crawlers.tongcheng import TongchengCrawler
    assert TongchengCrawler.login_suspect in (True, False)
    tc = pathlib.Path(webui.__file__).parent.joinpath(
        "crawlers", "tongcheng.py").read_text(encoding="utf-8")
    assert "login_suspect = False" in tc
    assert "type(self).login_suspect = True" in tc
    assert "type(self).login_suspect = False" in tc
    src = webui_full_src()
    assert "近 14 天出发日均未采" in src and "data-bandexpand" in src
    assert "@media(max-height:980px)" in src and "srx-probe-on .srx-audit" in src


# ---- r386：飞猪中转卡片无航班号（实测行头「马来西亚亚航长途 等2家航司」）

def _transfer(**over):
    base = _item(nameLine="马来西亚亚航长途 等2家航司", tips="2程航班",
                 depTime="01:35", arrTime="10:20", cross="",
                 priceText="机票价格739元", priceNum="含税￥739",
                 taxText="", quantity="少量", trans="吉隆坡", segs=2)
    base.update(over)
    return base


def test_transfer_card_without_flight_no_is_kept():
    """r386：SHA→SIN 页面 82 张卡片里 68 张中转，旧解析全丢只存 14 条直飞。"""
    rows = FliggyCrawler._parse_intl_items([_transfer()], "2026-11-16")
    assert len(rows) == 1, "中转卡片不得因缺航班号被丢"
    r = rows[0]
    assert r["code"] == "", "渠道不给航班号就不编"
    assert r["name"] == "马来西亚亚航长途", "去掉「等2家航司」尾巴"
    assert r["transfer"] is True and r["transCity"] == "吉隆坡"
    assert r["price"] == 739 and r["depTime"] == "01:35"
    assert r["arrTime"] == "10:20"


def test_transfer_cards_same_dep_different_arr_not_deduped():
    """同一航司同一起飞时刻的不同中转方案必须都保留。"""
    rows = FliggyCrawler._parse_intl_items(
        [_transfer(arrTime="10:20"), _transfer(arrTime="11:35"),
         _transfer(arrTime="13:40")], "2026-11-16")
    assert len(rows) == 3, [r["arrTime"] for r in rows]
    assert sorted(r["arrTime"] for r in rows) == ["10:20", "11:35", "13:40"]


def test_transfer_without_price_or_times_still_dropped():
    """认不出/没时刻/没价的仍然丢——不当假行。"""
    rows = FliggyCrawler._parse_intl_items([
        _transfer(priceText="机票价格0元"),
        _transfer(depTime="", arrTime=""),
        _item(nameLine="", trans="", segs=1),   # 无行头也非中转
    ], "2026-11-16")
    assert rows == []


def test_direct_card_unchanged():
    rows = FliggyCrawler._parse_intl_items([_item()], "2026-11-16")
    assert len(rows) == 1 and rows[0]["code"] == "9C7293"
    assert rows[0]["transfer"] is False


# ---- r386：无航班号的中转行不得被下游当成"日历行/非真实班次"

def test_ui_and_backend_treat_timed_row_as_real_flight():
    """前端 srxIsCal 与后端 _real_offer 都只认时刻。

    曾额外要求 code：飞猪国际中转卡片不给航班号，会被标成日历行 /
    非真实班次，于是"页面有中转"变成"页面没中转"。
    """
    import inspect
    import webui
    src = webui_full_src()
    assert ("function srxIsCal(f){return !!f.isCal||!(f.depTime&&f.arrTime)}"
            in src), "前端日历判据必须只看时刻"
    assert "!(f.code&&f.depTime&&f.arrTime)" not in src, \
        "不得再以 code 缺失判为日历行"


def test_calendar_row_still_detected_by_missing_times():
    from core import alerter as A
    cal = {"price": 719, "name": "日历最低价", "depTime": "", "arrTime": ""}
    assert A._is_calendar_row(cal) is True
    transfer = {"price": 1992, "name": "海湾航空", "code": "",
                "depTime": "16:30", "arrTime": "06:35",
                "transCity": "巴林", "transfer": True}
    assert A._is_calendar_row(transfer) is False, \
        "有时刻的中转行是真实班次，不是日历行"


def test_transfer_segments_not_written_into_plane():
    """r386：tips 对中转是段数标记（「2程航班」），不能占机型字段。"""
    rows = FliggyCrawler._parse_intl_items(
        [_transfer(tips="2程航班")], "2026-11-16")
    r = rows[0]
    assert r["plane"] == "", "机型不得写成「2程航班」"
    assert r["segments"] == 2, "段数另立字段供展示"


def test_direct_plane_kept_and_segments_zero():
    rows = FliggyCrawler._parse_intl_items(
        [_item(tips="中型机321")], "2026-11-16")
    r = rows[0]
    assert r["plane"] == "中型机321"
    assert r["segments"] == 0


def test_segments_parsed_from_tips_not_from_time_blocks():
    """segs（.time-info 计数）对中转恒为 1；段数必须来自「N程航班」。"""
    two = FliggyCrawler._parse_intl_items([_transfer(tips="2程航班")],
                                          "2026-11-16")[0]
    four = FliggyCrawler._parse_intl_items([_transfer(tips="4程航班")],
                                           "2026-11-16")[0]
    assert two["segments"] == 2 and four["segments"] == 4
    assert FliggyCrawler._seg_n("2程航班") == 2
    assert FliggyCrawler._seg_n("") == 2   # 有转城市即至少两段
