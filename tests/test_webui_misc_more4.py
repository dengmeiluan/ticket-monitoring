# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1195_port_fallback.py
- tests/test_r254_webui.py
- tests/test_r258_webui.py
- tests/test_r259_webui.py
- tests/test_r298_webui.py
- tests/test_r345_ux.py
- tests/test_r346_ux.py
- tests/test_r647_ok_row_never_dashes.py
- tests/test_v15114_webui.py
- tests/test_v15117_webui.py
- tests/test_v15126_webui.py
- tests/test_v15275_ui.py
- tests/test_v1558_webui.py
- tests/test_v1589_webui.py
- tests/test_v171_webui.py
- tests/test_v180_obsfix.py
- tests/test_v181_webui.py
- tests/test_v183_webui.py
- tests/test_v185_webui.py
- tests/test_v186_webui.py
- tests/test_v220_affordance.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import inspect
import io
import json
import logging
import os
import pytest
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webui

from core.alerter import Alerter
from core.models import Route
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from webui import _cluster_round_rows

# 活数据日期：防「日期已过」校验随日历腐化
_FUTURE = (date.today() + timedelta(days=7)).isoformat()


# ---- merged from tests/test_r1195_port_fallback.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_candidate_ports_are_sequential():
    assert webui._candidate_ports(8765, 3) == [8765, 8766, 8767]
    assert webui._candidate_ports("8765", 1) == [8765]
    assert webui._candidate_ports(None, 2) == [8765, 8766]   # 脏值兜底


class _FakeSrv:
    """假 server：只在 allowed 端口上成功，其余抛 OSError（= WinError 10048）。"""

    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.bound = []

    def __call__(self, addr, handler):
        host, port = addr
        if port not in self.allowed:
            raise OSError(10048, "Only one usage of each socket address")
        self.bound.append(port)
        return ("SRV", port)


def test_bind_console_shifts_when_port_busy(monkeypatch):
    fake = _FakeSrv(allowed={8767})
    monkeypatch.setattr(webui, "_Srv", fake)
    srv, actual, err = webui._bind_console("127.0.0.1", 8765, tries=5)
    assert srv is not None and actual == 8767, (srv, actual, err)
    assert err is None
    assert fake.bound == [8767], "应当只在真正可用的端口上绑定一次"


def test_bind_console_reports_failure_honestly(monkeypatch):
    fake = _FakeSrv(allowed=set())
    monkeypatch.setattr(webui, "_Srv", fake)
    srv, actual, err = webui._bind_console("127.0.0.1", 8765, tries=3)
    assert srv is None and actual == 0, (srv, actual)
    assert isinstance(err, OSError), err


def _pick_free_base():
    """找一个 base 与 base+1 都空闲的端口（r1311：不再写死 8795）。"""
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        finally:
            s.close()
        if base + 1 >= 65535:
            continue
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            t.bind(("127.0.0.1", base + 1))
            return base
        except OSError:
            continue
        finally:
            t.close()
    raise RuntimeError("找不到空闲端口对")




# ---- merged from tests/test_r254_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- W1: montabs 右端用户切换 chip ----------

def test_w1_mtabuser_chip_present():
    src = _page_src()
    assert 'id="mtabUser"' in src, "缺用户切换 chip 元素"
    assert "function mtabUserNext" in src, "缺循环切换函数"
    assert "pickUser((U+1)" in src or "pickUser((U + 1)" in src, \
        "循环切换必须复用 pickUser 单源（选中态与 userPills 同拍）"


def test_w1_mtabuser_lives_in_header_not_tabs():
    """r372 IA：用户作用域开关驻顶部账号区，不进内容页签行。

    它表达「看谁的数据」而非「看哪块内容」；曾与六个内容页签并列在
    montabs 行尾且自称「用户视图」，用户实报排位别扭。
    """
    src = _page_src()
    hdr = src[src.index('<header id="hdcard"'):src.index("</header>")]
    assert 'id="mtabUser"' in hdr, "用户 chip 应驻 header 账号区"
    tabs = src[src.index('<div class="tabs" id="montabs"'):]
    tabs = tabs[:tabs.index("</div>")]
    assert 'id="mtabUser"' not in tabs, "用户 chip 不得混入 montabs 内容页签行"
    assert "huser" in src, "header 用户 chip 缺 huser 视觉样式"
    i0 = src.index("function mtabUserSync")
    assert "· 用户视图" not in src[i0:i0 + 900], \
        "用户 chip 重复自称「用户视图」的旧文案应退役"


def test_w1_mtabuser_sync_with_userpills():
    """chip 与 userPills 同拍同步：单用户也显示当前用户范围（r368 起）。"""
    src = _page_src()
    i0 = src.index("function mtabUserSync")
    seg = src[i0:i0 + 1200]
    assert "mtabUserSync" in src, "缺同步函数调用"
    assert "us.length<1" in seg or "us.length < 1" in seg, \
        "单用户也要显示用户范围；无用户才隐藏"


def test_w1_mtabuser_touch_floor():
    """触控 36px 地板族（十四§4）：header 用户 chip 有触控增强声明。"""
    src = _page_src()
    assert "#hdcard .huser" in src and "height:36px" in src, \
        "huser 缺触控地板声明"


# ---------- W2: 脉冲柱带状态落地 ----------

def test_w2_pulse_goto_has_target():
    src = _page_src()
    assert "gotoPulseHealth(" in src, "脉冲柱缺带态落地入口"
    # 旧「裸跳区域」形态退役：柱模板不得再直连 gotoMonTab('health')
    for m in (_src_iter(src, "onclick=\"gotoMonTab('health')\"")):
        pytest.fail(f"柱仍裸跳健康 tab（无定向）: 位置 {m}")
    assert "gotoMonTab('health')" in src, "健康 tab 本体入口仍需保留"


def _src_iter(src, needle):
    out = []
    i = 0
    while True:
        i = src.find(needle, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def test_w2_hflash_class_and_glow():
    src = _page_src()
    assert "hflash" in src, "缺失败渠道辉光类"
    assert "scrollLeft" in src[_src_iter(src, "function gotoPulseHealth")[0]:
                               _src_iter(src, "function gotoPulseHealth")[0] + 1600], \
        "带态落地须横滚定位该轮时间片"


# ---------- W4: .hcells 桌面滚轮通道 ----------

def test_w4_hcells_wheel_channel():
    src = _page_src()
    assert "hcellsWheel" in src or ("wheel" in src and ".hcells" in src), \
        "缺 .hcells 滚轮转写通道"


# ---------- W6: 矮窗 canvas 比例档（审计 P3-6） ----------

def test_w6_short_viewport_canvas_tier():
    """矮窗（max-height:660px）桌面带 canvas 收一档：r236 取大语义下
    宽短窗 28vw 主导（1280×540 → 358px，占视口 66%），基础档下限
    240px 也远超矮窗预算——置尾媒体块 clamp(200px,34vh,280px)，
    层叠序须胜过基础档（L267）与 ≥1866 坡带（r301 F-1 连续函数档，
    矮窗带声明在坡带后故优先级正确）。uitest 视口高
    全 ≥844 不触发，行为面零扰动（源码钉锁结构事实）。
    阈值 600→660（goal 轮 P2-2 模型变准）：720p 主流屏浏览器 chrome
    吃掉 100-170px 后视口高落 601-700 带，旧阈值下过线即回基础档
    358px（Δ154px 跳变复现短窗挤压）。"""
    src = _page_src()
    i0 = src.index("@media(max-height:660px) and (min-width:761px)")
    assert "canvas{height:clamp(200px,34vh,280px)}" in src[i0:i0 + 200], \
        "矮窗档缺 clamp 声明"
    assert "@media(max-height:600px)" not in src, "旧阈值退役禁复活"
    assert i0 > src.index("height:clamp(240px,max(38vh,28vw),360px)"), \
        "矮窗档必须置尾于基础档后（层叠序，LESSONS 二十一§1）"
    assert i0 > src.index("@media(min-width:1866px){"), \
        "矮窗档必须置尾于 ≥1866 坡带后（矮窗优先级正确）"


# ---------- W5: previewPush busy 反馈 ----------

def test_w5_preview_busy_feedback():
    src = _page_src()
    i0 = src.index("async function previewPush")
    body = src[i0:src.index("\nasync function", i0 + 10)] \
        if "\nasync function" in src[i0 + 10:] else src[i0:i0 + 3000]
    assert "pvBtn" in body, "预览函数未挂 busy 反馈面（按钮原地）"
    assert "disabled" in body or "busy" in body, "慢路径缺 busy/disabled 反馈"


# ---- merged from tests/test_r258_webui.py ----

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




# ---------- U2: 走势卡头 chip 组容器（源码钉 + 几何行为钉） ----------

def test_trend_chips_grouped():
    src = _page_src()
    # 窗口取结构边界（第一组 mdgrp 开标签到下一容器 chartRoutes）而非
    # 固定字符数（三十一§3：块内合法增厚——如新增第三组 chip——不应红）
    m = src.index('class="mdgrp"')
    j = src.index('id="chartRoutes"')
    seg = src[m:j]
    assert seg.count('class="mdgrp"') == 3, (
        "走势卡头四 chip（折线/K线/48h/7天）须两组各包 .mdgrp：平铺同层"
        "时窄档折行后模式档与时间窗档混排（组间语义断裂）")
    assert ".mdgrp{display:inline-flex" in src, (
        ".mdgrp 组容器缺基础规则（nowrap 恒整）")




# ---------- W1: fltBtn 键盘焦点环（audit P1-1：sticky 衬底 halo 压环） ----------

def test_fltbtn_focus_ring_source():
    src = _page_src()
    assert ("#montab-details .tabs>#fltBtn:focus-visible{box-shadow:"
            "inset 0 0 0 2px var(--blue),0 0 0 4px var(--card)") in src, (
        "≤760 档 #fltBtn 的 sticky 衬底 halo（特异度 (1,1,0)）整条吃掉"
        "焦点环族 .tabs span:focus-visible（(0,2,x)）——置尾复声明"
        "inset 环+halo 双影（首列表头 th.srt 先例）")




# ---------- W2: 筛选价格双输入可访问名（audit P2-1：fpmax 零名） ----------



# ---------- W3: tabpanel 可访问名（audit P3-1） ----------



# ---------- W4: verbar/demoBar 动态现身 live 语义（audit P3-2） ----------

def test_banners_live_roles():
    src = _page_src()
    assert 'id="verbar" role="alert"' in src, (
        "verbar 服务升级横幅动态现身（display:none→显示）无 live 语义，"
        "读屏零感知——挂 role=alert 显身即播报")
    assert 'id="demoBar" role="status"' in src, (
        "demoBar 演示横幅动态现身无 live 语义——挂 role=status")


# ---------- W5: mtabUser 态入名（audit P3-3：aria 静态不带当前用户） ----------



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




# ---- merged from tests/test_r259_webui.py ----

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
    assert "border:1px solid var(--ctlbd)" in _block(src, ".rhead .ractions{"), (
        "航线动作组边框仍借 --line2（与 .btn2 同屏双档）")




# ---------- U2: 前端 TIER 值域注释收口（audit 备案①） ----------

def test_tier_value_domain_note():
    src = _page_src()
    i = src.index("const TIER=")
    seg = src[max(0, i - 1500):i]
    assert "TIER 值域 {2,1,0}" in seg and "只认后端旗标" in seg, (
        "前端 TIER 值域注释缺位：长窗日桶 flag=0 不得按 v≤tv 回退成"
        "真达标；注释须锁死「只认后端旗标」的联动条件，防被误判死代码删除")


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




# ---- merged from tests/test_r298_webui.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

def _route():
    return Route(from_code="SHA", from_name="上海", to_code="HAK",
                 to_name="海口", dates=["2027-01-29"])


def test_qunar_view_url_h5_listpage():
    """2026-10-10 起 qunar PC 单程页 302 回官网首页（断供）；
    用户链接改指 m.flight H5 列表页，与爬虫 URL_TPL 同参。
    其余渠道出口不回归。"""
    a = Alerter(logging.getLogger("t"), storage=None)
    u = a._build_view_url(_route(), "2027-01-29", "qunar")
    assert "m.flight.qunar.com/ncs/page/flightlist" in u, u
    assert "flight.qunar.com/site/oneway_list.htm" not in u, u
    assert ("depCity=" + quote("上海")) in u, u
    assert ("arrCity=" + quote("海口")) in u, u
    assert "goDate=2027-01-29" in u, u
    from crawlers.qunar import QunarCrawler as QC
    for kv in QC.URL_TPL.split("?", 1)[1].split("&"):
        key = kv.split("=")[0]
        assert (key + "=") in u, (key, u)
    # 其余渠道出口不回归
    assert "m.ctrip.com" in a._build_view_url(_route(), "2027-01-29", "ctrip")
    assert "m.ly.com" in a._build_view_url(_route(), "2027-01-29", "tongcheng")
    assert "m.tuniu.com" in a._build_view_url(_route(), "2027-01-29", "tuniu")
    assert "sjipiao.fliggy.com" in a._build_view_url(
        _route(), "2027-01-29", "fliggy")


def test_no_dead_pc_list_link_in_page():
    """2026-10-10 起 qunar PC 单程页 302 回 www.qunar.com 促销聚合，
    `flight.qunar.com/site/oneway_list.htm` 是死链；webui.py 与
    docs/site 烘焙产物统一改指 m.flight H5 列表页。"""
    import os
    with io.StringIO(webui_full_src()) as f:
        assert "flight.qunar.com/site/oneway_list.htm" not in f.read(),             "webui 残留 PC 死链形态"
    site = os.path.join(os.path.dirname(webui.__file__),
                        "site", "index.html")
    if os.path.isfile(site):
        with open(site, encoding="utf-8") as f:
            assert "flight.qunar.com/site/oneway_list.htm" not in f.read(),                 "烘焙态残留 PC 死链（删 demo .statecache 后重烘）"


def test_routes_txt_grouping():
    """P2-1：同城市对聚合一段、日期随组（MM-DD 短形）；跨条目同对
    日期并档；空日期组回退裸对；段内不出现分隔符「、」（前端按「、」
    切段逐段 nowrap）。"""
    routes = [
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-29", "2027-01-30"]},
        {"from_name": "上海", "to_name": "海口", "dates": ["2027-02-13"]},
        {"from_name": "海口", "to_name": "上海", "dates": ["2027-02-14"]},
    ]
    t = webui._routes_txt(routes)
    assert t == "上海→海口 01-29/01-30/02-13、海口→上海 02-14", t
    assert webui._routes_txt([]) == ""
    assert webui._routes_txt([{"from_name": "上海", "to_name": "海口",
                               "dates": []}]) == "上海→海口"
    for seg in t.split("、"):
        assert "、" not in seg


def test_routes_txt_cap_three_entries():
    """P2-1：截前面 [:3] 语义维持（条目级截断，分组在其后）。"""
    routes = [{"from_name": f"城{i}", "to_name": "目标",
               "dates": ["2027-01-29"]} for i in range(5)]
    t = webui._routes_txt(routes)
    assert t.count("、") == 2, t
    assert "城3" not in t and "城4" not in t, t


def test_routes_txt_in_group_dedup():
    """P2-1：组内日期去重（同对跨条目重复日期只出现一次—— Soldier
    变异「去重去除」的存活缺口补钉；重复配置条目是现实可达形态）。"""
    routes = [
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-29", "2027-01-30"]},
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-30", "2027-02-13"]},
    ]
    t = webui._routes_txt(routes)
    assert t == "上海→海口 01-29/01-30/02-13", t
    assert t.count("01-30") == 1, t


def test_suspended_users_routes_txt_same_source():
    """P2-1 停用卡同源：分组词面与在役卡一致（双口径漂移防线）。"""
    out = webui._suspended_users([{"name": "张三"}], [{
        "name": "张三",
        "routes": [
            {"from": "SHA", "from_name": "上海", "to": "HAK",
             "to_name": "海口", "dates": ["2027-01-29"], "enabled": False},
            {"from": "HAK", "from_name": "海口", "to": "SHA",
             "to_name": "上海", "dates": ["2027-02-14"], "enabled": False},
        ]}])
    assert len(out) == 1 and out[0]["n"] == 2, out
    assert out[0]["routesTxt"] == "上海→海口 01-29、海口→上海 02-14", out


def test_ovalert_css_shape_rule():
    """P1-2：红点形状单源——inline-block 使 width 参与布局（内联盒
    定律：空 <i> 的 7px 宽曾是死档），卡色描边在激活蓝底上以描边对比
    达 3:1 辨识（红点本身对激活底 1.02/1.60:1 双欠）。"""
    src = webui.PAGE
    assert "#ovAlert{display:inline-block" in src, "形状规则缺席"
    rule = [ln for ln in src.splitlines() if "#ovAlert{display:inline-block" in ln]
    assert rule and "box-shadow" in rule[0] and "var(--card)" in rule[0], rule


# ---- merged from tests/test_r345_ux.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui.PAGE


# ---- 日期：模式互斥 + 双草稿保留 + 加入=合并去重 ----

def test_date_mode_switch_single_editor():
    s = _src()
    assert "function _dateRowHTML(" in s
    assert 'data-dm="range"' in s and 'data-dm="single"' in s
    assert "function setDateMode(" in s
    assert "function dateTabKey(" in s
    assert ".dpanel[hidden]{display:none}" in s
    # 旧双卡常显与工具行彻底退役
    assert ".dline.dtools" not in s
    assert "dtools-t" not in s
    assert "class=\"dtool\"" not in s
    # 两模式面板同体：固定一行输入 + 共享快捷/应用脚
    assert ".dpanel-row{display:grid" in s
    assert ".dcompose-foot{display:flex" in s


def test_date_apply_merges_not_replaces():
    s = _src()
    assert "function _mergeDates(" in s and "function _commitDates(" in s
    assert "rs.dates=u.dates" in s
    assert "_commitDates('d',i,j,ds,'未来'+days+'天')" in s
    assert "_commitDates('d',i,j,ds,'区间 '+a+' 至 '+b)" in s
    # 单日显式加入，不再 change 即写模型
    assert 'onchange="if(this.value)addDate' not in s
    assert 'onchange="if(this.value)retAdd' not in s
    assert "if(_commitDates('r',i,j,[v],'已加入返程 '+v))_focusDateInput" in s


def test_date_mode_has_aria_and_keyboard():
    s = _src()
    assert 'role="tablist"' in s
    assert 'aria-controls="dpan-${p}-${i}-${j}-range"' in s
    assert "ArrowLeft" in s and "Home" in s and "End" in s
    assert "aria-label=\"${title}添加方式\"" in s


# ---- 渠道：开关×必需凭据=已启用，否则如实「待完善」 ----

def test_channel_readiness_is_honest():
    s = _src()
    assert "function _chReady(" in s
    assert "function _chLbl(" in s
    assert "x.enabled&&s(x.webhook)" in s
    assert "x.enabled&&s(x.send_key)" in s
    assert "em.enabled&&s(em.user)&&s(em.password)&&s(em.to)" in s
    assert ".chcard.todo{" in s and ".lgdot.mid{" in s
    assert "推送已就绪" in s and "推送待完善" in s


def test_email_add_focus_and_secret_masked():
    s = _src()
    assert "input[placeholder^=\"you@\"]" in s
    assert "if(inp)setTimeout(()=>inp.focus({preventScroll:true}),160)" in s
    assert 'id="dtsecret-${i}" type="password"' in s
    assert "function togglePw(" in s


def test_confirm_focus_cancel_and_trap():
    s = _src()
    assert "const b=$('cmCancel');if(b)b.focus" in s
    assert "e.key==='Tab'" in s and "last.focus()" in s
    assert 'aria-describedby="cmText"' in s


# ---- 明细：筛选语义与计数口径 ----

def test_detail_free_baggage_excludes_negative_text():
    s = _src()
    assert "function _hasFreeBag(" in s
    assert "(?:无|不含|需另购|另购|收费)(?:免费)?(?:托运|行李)" in s
    assert "FLT.bag&&!_hasFreeBag(f)" in s


def test_detail_reset_clears_bagkg_wb_and_chips():
    s = _src()
    assert "FLT.bagkg=0;FLT.wb=false;" in s
    assert "saveUI();buildChips();buildDateChips();buildRouteChips();table()" in s


def test_detail_search_group_not_coupled_to_price():
    s = _src()
    assert "out.push({g:'q',label:'搜索「'+FLT.q+'」'})" in s
    assert "else if(g==='q'){FLT.q='';syncFltInputs();}" in s


def test_detail_kpi_quote_and_flight_units():
    s = _src()
    assert "function _flightUid(" in s
    assert "条报价 / '+_qn+' 班" in s
    assert "!f.xphan" in s


def test_detail_safe_and_few_cover_words():
    s = _src()
    assert "f.lurePrice!=null||f.ticketRisk" in s
    assert "f.fewTicket||(f.leftTickets>0&&f.leftTickets<10)" in s


def test_detail_compare_current_row_savings():
    s = _src()
    assert "function xrowHtml(u,k,open,grp,curPrice)" in s
    assert "（本行已是同班最低）" in s
    assert "（换最低渠道可省 ￥${save}）" in s
    assert "xrowHtml(u,k,EXP===k,fp(f),f.price)" in s


def test_detail_mobile_overflow_and_touch_fixes():
    s = _src()
    assert ".attrgrid .ag-wide .attrq{flex:0 0 104px;width:104px;min-width:0" in s
    assert "#alchips{flex:1 1 0;min-width:0}" in s
    assert ".chiplab{font-size:12px;color:var(--mut);flex:none;white-space:nowrap}" in s
    assert "@media(max-width:900px) and (pointer:coarse){\n   .fltpreset{min-height:36px" in s
    assert ".tw.xend::after{opacity:0}" in s


# ---- 全局：路径待创建/启动项/运行时透明化 ----

def test_path_meta_creatable_under_missing_parent(tmp_path):
    m = webui._path_meta("ud", str(tmp_path / "notyet" / "user_data"), {})
    assert m["ok"] is True
    assert m["exists"] is False
    assert m["parent_exists"] is False
    assert m["creatable"] is True
    assert m["ancestor_writable"] is True


def test_storage_target_status_and_writable_labels():
    s = _src()
    assert "当前 · " in s and "目标 · " in s
    assert "可写 · 待创建" in s
    assert "父目录尚不存在，重启时自动创建" in s
    assert "最近的可写祖先不存在，无法创建" in s


def test_startup_keys_include_host_and_run_on_start():
    s = _src()
    assert "'db_path','log_path','user_data_dir','browser_dir','host','run_on_start'" in s
    vals = webui._startup_vals(
        {"web": {"host": "0.0.0.0"}, "schedule": {"run_on_start": False}})
    assert vals["host"] == "0.0.0.0"
    assert vals["run_on_start"] is False


def test_runtime_identity_fields():
    s = _src()
    for token in ("listen", "started_at", "tz", "argv", "copyText(", "监听 "):
        assert token in s, token


def test_restart_center_non_path_rows():
    s = _src()
    assert "labels={db_path:'数据库'" in s and "host:'控制台监听地址'" in s
    assert "非路径启动项：保存后需重启进程生效，无文件搬迁。" in s


def test_version_bumped():
    text = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    # r1857：不再硬编码某一版的字符串——改成「版本存在、且 >= 1.6.0、且有对应 release-notes」
    # W2b 文档工程：docs/release-notes-v*.md 已并入 docs/CHANGELOG.md
    # （每版一节 `## [vX.Y.Z] - 日期`），判据同步改为 CHANGELOG 有该版条目。
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    assert m, "main.py 里找不到 __version__"
    ver = m.group(1)
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [1, 6, 0], "版本号回退了：%s" % ver
    changelog = open(os.path.join(ROOT, "docs", "CHANGELOG.md"),
                     encoding="utf-8").read()
    assert ("## [v%s]" % ver) in changelog, \
        "docs/CHANGELOG.md 缺 v%s 版本条目" % ver


# ---- merged from tests/test_r346_ux.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui.PAGE


# ---- 同班比价：身份必须含日期/航线/航班号，不能把不同航班串成一组 ----

def test_same_flight_fingerprint_includes_identity():
    s = _src()
    assert "const fp=f=>((f.cal?'cal':'')+'|'+(f.date||'')+'|'+(f.route||'')+'|'+(f.code||f.flightNo||f.name||'')" in s
    assert "（本行已是同班最低）" in s
    assert "xrowHtml(u,k,EXP===k,fp(f),f.price)" in s


def test_kpi_flights_include_date_and_exclude_calendar():
    s = _src()
    # r365：班次去重与 srxFlightKey 同源（航班号+日期+时刻+中转/跨天/经停）
    assert "function _flightUid(f)" in s and "srxFlightKey(f)" in s
    assert "flightNo||f.name" not in s[s.index("function _flightUid"):][:900]
    assert "rows.filter(f=>!f.cal).map(f=>_flightUid(f))" in s


# ---- Server酱：装配器不得漏 logger（旧路径 TypeError 后整通道静默失效） ----

def test_serverchan_build_passes_logger():
    text = open(os.path.join(ROOT, "core", "notifier.py"),
                encoding="utf-8").read()
    seg = text.split("primary = ServerChanNotifier(", 1)[1][:260]
    assert "logger=logger" in seg


# ---- 路径/监听：保存前拦截 Windows 非法名与不可绑定的 host ----

def test_bad_path_reason_rejects_windows_invalid():
    assert webui._bad_path_reason("D:/ok/prices.db") == ""
    assert "不允许的字符" in webui._bad_path_reason("D:/bad<x>/prices.db")
    assert "保留名" in webui._bad_path_reason("D:/tmp/CON.txt")
    assert "空格或句点" in webui._bad_path_reason("D:/tmp/abc. ")


def test_path_meta_marks_invalid():
    m = webui._path_meta("db", "D:/bad<x>/prices.db", {})
    assert m["invalid"] and "不允许的字符" in m["invalid"]
    assert m["writable"] is True  # 可写不代表合法，valid 由 invalid 先否决


def test_path_check_rejects_duplicate_storage_target():
    s = webui_full_src()
    assert '与「%s」路径相同，请换一个位置' in s
    assert 'elif valid and meta.get("exists") and not meta.get("writable")' in s


def test_host_save_has_bind_preflight():
    s = webui_full_src()
    assert "_probe.bind((_h, 0))" in s
    assert "监听地址不可用（本机没有该地址" in s
    assert "function setHost(el)" in _src() and "只支持 IPv4 或主机名" in _src()


# ---- 日期：两面板提示各说各的话；清空走确认层 ----

def test_date_hints_are_mode_specific():
    s = _src()
    assert "const rangeHint=" in s and "const singleHint=" in s
    assert '<span class="dquickhint">${rangeHint}</span>' in s
    assert '<span class="dquickhint">${singleHint}</span>' in s


def test_clear_dates_confirms_before_wipe():
    s = _src()
    assert "function clearDates(prefix,i,j,force)" in s
    assert "清空全部出发日期？" in s and "清空日期" in s
    assert "clearDates(prefix,i,j,true)" in s


# ---- 移动端：保存条不挡、toast 不吞点击、筛选有出口 ----

def test_savebar_left_dock_and_single_row_mobile():
    s = _src()
    assert ".savebar{left:18px;right:auto}" in s
    assert "flex-wrap:nowrap;gap:8px;padding:8px 10px" in s
    assert "#toasts{top:calc(var(--hdh,54px) + 12px)" in s


def test_mobile_filter_has_result_exit():
    s = _src()
    assert 'id="fdrawerCta"' in s and "function closeFltShow()" in s
    assert "body:has(.fbar.open) .fdrawer-cta{display:flex" in s
    assert "const _fd=document.getElementById('fdCount');if(_fd)_fd.textContent=rows.length;" in s


def test_email_title_ellipsis_and_start_scroll():
    s = _src()
    assert '<span class="ch-title">邮件·' in s
    assert ".chhead .ch-title{flex:1 1 0;width:0;min-width:0;overflow:hidden" in s
    assert "scrollIntoView({block:'start',behavior:'smooth'})" in s


# ---- 重启/保存：差量确认层 + 待重启文案不再谎称全部热生效 ----

def test_restart_uses_confirm_and_lists_diff():
    s = _src()
    assert "function doRestart(b)" in s and "async function doRestartNow(b)" in s
    assert "本次差量：\\n" in s
    assert "openConfirm('重启监控进程？'" in s


def test_save_feedback_respects_restart_required():
    s = _src()
    assert "项启动级配置需重启生效" in s
    assert "try{renderRestartCenter();}catch(e){}" in s


def test_route_summary_counts_semantic_terms():
    s = _src()
    assert "if(r.direct_only)n++;" in s
    assert "out.push('只要直飞')" in s
    assert "out.push('次日≤'+r.transfer_arrival_max)" in s
    assert ".rthead .rfsum{flex:1 1 auto;min-width:0" in s


def test_route_toggle_feedback_and_action_gap():
    s = _src()
    assert "航线已停用：保留全部配置" in s
    assert ".rhead .rop{gap:8px;row-gap:6px}" in s


def test_invalid_preview_never_claims_migration():
    s = _src()
    assert "if(!j.valid)bits.push('目标不可用：请先修正后再保存/重启')" in s
    assert "if(j.valid===false){" in s and '<span class="warn">' in s


def test_bad_host_border_global():
    s = _src()
    # 全档规则在媒体块外（桌面/窄档同红边）
    assert " .glcell input.bad,.pathcard input.bad{border-color:var(--red)!important" in s


def test_storage_save_error_rejects_bad_and_duplicate():
    bad = {"output": {"db_path": "D:/bad<x>/prices.db",
                      "log_path": "logs/monitor.log"},
           "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert "不允许的字符" in webui._storage_save_error(bad)
    dup = {"output": {"db_path": "data/prices.db",
                      "log_path": "data/prices.db"},
           "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert "不能使用同一路径" in webui._storage_save_error(dup)
    ok = {"output": {"db_path": "data/prices.db",
                     "log_path": "logs/monitor.log"},
          "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert webui._storage_save_error(ok) == ""


def test_restart_invalid_path_no_migration_claim():
    s = _src()
    assert "if(j.valid===false){el.innerHTML='<span class=\"warn\">目标不可用：" in s
    assert "（不会搬迁/不会生效）" in s
    assert "const _pending=new Set([..._schg,...((RESTART&&RESTART.changed)||[])])" in s


# ---- merged from tests/test_r647_ok_row_never_dashes.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PACING = {
    "ok": True, "quiet": {}, "last_round": {"sent": 3, "paced": 1},
    "channels": {
        "ctrip": {"state": "ok",
                  "advice": {"state": "ok", "severity": "ok", "hint": ""}},
        "fliggy": {"state": "ok",
                   "advice": {"state": "path_degraded", "action": "route",
                              "severity": "auto", "eta_s": 0,
                              "hint": "国际 H5 偏低"}},
    },
    "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {},
}
PATHS = {"fliggy": {
    "paths": {"H5": {"attempts": 32, "rate": 0.25, "login": 2}},
    "retired_paths": [],
    "scopes": {"intl": {"attempts": 32, "rate": 0.25, "query_attempts": 12,
                        "query_rate": 0.42, "query_attempts_live": 12,
                        "query_rate_live": 0.42,
                        "paths": {"H5": {"attempts": 32, "rate": 0.25}}},
               "dom": {"attempts": 15, "rate": 0.8, "query_attempts": 8,
                       "query_rate": 0.75, "query_attempts_live": 8,
                       "query_rate_live": 0.75,
                       "paths": {"H5": {"attempts": 15, "rate": 0.8}}}}}}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": PATHS, "diag": [], "coverage": {}}










# ---- merged from tests/test_v15114_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE = webui.PAGE


# ---- W-2 走势 y 轴标残缺 ----

def test_w2_anim_negative_p_clamped():
    """入场动画 p 钳 [0,1]：rAF 首帧时间戳早于 t0 时 p<0 曾产负宽
    clip 矩形（canvas 规范归一进 y 轴标签带，clearRect 擦带+标签
    中段切片入画，后续帧永不回补）。"""
    assert "const p=Math.max(0,Math.min(1,(t-t0)/700))" in PAGE


def test_w2_reveal_rect_covers_label_band():
    """揭示矩形起点=画布左缘：y 轴标签带 [0,L) 必须首帧即在 clip
    内——钳零只断负宽根因，揭示矩形从 L-2 起步时标签带在任何动画
    帧都不在 clip 内，首入 y 轴标仍缺（终帧须与非动画全绘逐位等）。"""
    assert "ctx.rect(0,0,L-2+(W-L+2)*e,H)" in PAGE


# ---- W-1 视图切换器折行裁残 ----

def test_w1_montabs_nowrap_declared():
    """#montabs 单行横滚形制显式声明 nowrap：基础 .tabs
    flex-wrap:wrap 不再泄漏（折行格被锁高+隐滚动条裁残的根因）。
    #montabs 有多媒体块级联（≤760 grid 形制/≤540 横滚形制/≥761
    吸顶形制），凡声明 overflow-x:auto 的横滚形制规则必须自带
    flex-wrap:nowrap（形制与换行互斥，防未来新档位再漏）。"""
    rules = re.findall(r"#montabs\{[^}]*\}", PAGE, re.S)
    scroll = [r for r in rules if "overflow-x:auto" in r]
    assert scroll, "横滚形制规则缺席"
    assert all("flex-wrap:nowrap" in r for r in scroll)


def test_w1_xhint_selector_covers_montabs():
    """xhint 溢出判定四挂点全部含 #montabs（nowrap 后窄档真溢出，
    滚动条已隐、无暗示即复刻明细条修复前同款问题）。r247 W1 起
    四挂点同步扩至 #opscard .opsbtns（窄档单行横滚族同批重判），
    钉面随判定族扩展更新。r253 起 .tw（表内横滚提示）并入其中
    两挂点（health 渲染批/resize 批）；r288 起并入三挂点（switchView
    cfg→mon 回程批同族补齐——窄窗配置停留回监控且明细 tab 持久时
    .tw 窗口期失暗示），health 批不含（健康 tab 无表内横滚容器）——
    旧串 1 处 + 扩展串 3 处，四挂点不丢。"""
    assert PAGE.count(
        "querySelectorAll('.hcells,#montab-details .tabs,#montabs"
        ",#opscard .opsbtns')") == 1
    assert PAGE.count(
        "querySelectorAll('.hcells,#montab-details .tabs,#montabs"
        ",#opscard .opsbtns,.tw')") == 3


def test_w1_montabs_xhint_after_fade():
    """≤540 块 #montabs 渐隐暗示 ::after 与点亮态在案
    （明细吸顶条同款装饰层，非容器 mask——mask 会连 sticky 件淡出）。"""
    assert "#montabs.xhint::after{opacity:1}" in PAGE
    assert "#montabs::after{content:''" in PAGE


# ---- EN-W3/M-2 空态图例互斥 ----

def test_w3_empty_state_clears_ring_note():
    """空态分支清 ringNote：满编环标图例不与「暂无走势数据」同屏
    （已配置未扫描航线打开走势时图例解释的图并不存在）。"""
    assert "$('ringNote').innerHTML=''" in PAGE


# ---- EN-W4 montabs 键盘族 ----

def test_w4_montabs_roving_and_activation():
    """四 mtab 全部 data-rv+可聚焦（方向键 _roving 族移动）+
    Enter/Space 激活（showMonTab）；容器挂 _roving 委托。"""
    assert re.search(r'id="montabs"[^>]*_roving\(event,this\)', PAGE)
    for t in ("overview", "trend", "details", "health"):
        m = re.search(r'<span class="mtab[^"]*" data-t="%s"[^>]*>' % t, PAGE)
        assert m, t
        tag = m.group(0)
        assert 'data-rv' in tag and 'tabindex="0"' in tag, t
        assert 'showMonTab' in tag, t


# ---- EN-W5/M-1 触控三块成员对齐 ----

def test_w5_touch_block_member_aligned():
    """.fbar .switch::before 热区成员三块齐备（≤900coarse/≤760/
    901+coarse；≤760 曾缺——双命中姊妹块现状零暴露，防新增开关位
    时家族漂移）。"""
    assert PAGE.count(".fbar .switch::before") == 3


# ---- merged from tests/test_v15117_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


# ---------------- verbar a 三缺失 ----------------

def test_verbar_link_focus_ring():
    assert ".verbar a:focus-visible" in src(), "焦点环清单缺 .verbar a"


def test_verbar_link_touch_expand():
    # 触控热区外扩（#foot a/.demoBar a::after 家族纪律：纯命中区）
    s = src()
    assert "#foot a,.demoBar a,.verbar a{position:relative}" in s
    assert "#foot a::after,.demoBar a::after,.verbar a::after" in s


def test_verbar_link_hover():
    assert ".verbar a:hover{text-decoration:underline}" in src()


# ---------------- kpisum a hover ----------------

def test_kpisum_link_hover():
    assert ".kpisum a:hover{text-decoration:underline}" in src()


# ---------------- 表单字体族 ----------------

def test_form_font_family_inherit():
    assert "button,input,select,textarea{font-family:inherit}" in src()


# ---------------- 焦点环 box-shadow 迁移 ----------------

def test_focus_ring_box_shadow_migration():
    s = src()
    # 全站清单：box-shadow 环 + outline 关闭（UA 接管 outline 通道，
    # box-shadow 不受接管；th.srt 负 offset 等效 inset 环）
    assert "box-shadow:0 0 0 2px var(--blue);outline:none" in s
    assert "th.srt:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none" in s
    # 行级焦点（明细 tr）同迁移：inset 贴格
    assert "#ftable tbody tr:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none}" in s


# ---------------- 推送通道健康可见性 ----------------

def _ts(hours_ago):
    """样本时刻动态生成（相对 24h 窗留足余量）——硬编码日历样本会随
    系统时间滑出窗口（时间敏感测试日历自爆律）。"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def test_push_channel_state_aggregation(tmp_path, monkeypatch):
    # 账本按通道聚合：ok/fail 计数、连败=最后一条 ok 之后的连续 fail、
    # last/last_ok 取窗口内首现（逐条升序）；旧账无 ch 字段不入聚合；
    # 路径与写入面同源（PUSH_HISTORY_FILE 重定向同轨）
    import json
    f = tmp_path / "push_history.jsonl"
    recs = [
        {"ts": _ts(6), "ok": True, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(5), "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(4), "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(3.5), "ok": True, "ch": "email",
         "title": "t", "desp": "d"},
        {"ts": "2021-01-01 00:00:00", "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},   # 窗口外（>24h 前）不入
        {"ts": _ts(2), "ok": False, "title": "t",
         "desp": "d"},                 # 无 ch 字段不入
    ]
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                           for r in recs) + "\n", encoding="utf-8")
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(f))
    import webui
    out = webui._push_channel_state(hours=24)
    dt = out["channels"]["dingtalk"]
    assert dt["ok"] == 1 and dt["fail"] == 2
    assert dt["fail_streak"] == 2
    # 升序账本尾现=最近：期望值从落账记录串派生（独立再取 now 在
    # 分钟边界有几十 ms 非确定性窗口）
    assert dt["last"] == recs[2]["ts"][5:16]
    assert dt["last_ok"] == recs[0]["ts"][5:16]
    em = out["channels"]["email"]
    assert em["ok"] == 1 and em["fail"] == 0 and em["fail_streak"] == 0
    assert set(out["channels"].keys()) == {"dingtalk", "email"}


def test_push_channel_state_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSH_HISTORY_FILE",
                       str(tmp_path / "nope.jsonl"))
    import webui
    assert webui._push_channel_state() == {"channels": {}}


def test_api_health_carries_push_channels():
    # /api/health 载荷挂 push 通道聚合（采集渠道之外的第二张脸）
    s = src()
    assert 'out["push"] = _push_channel_state(hours=hours)' in s
    # 前端消费：容器 + renderHealth 尾部调用渲染
    assert 'id="pushhl"' in s
    assert "renderPushChannels(j.push);" in s
    assert "function renderPushChannels(pj){" in s


def test_demo_health_push_channels_shape():
    # demo 分支同形（凡功能都过 demo 分支）：合成钉钉连败+邮件全绿
    from core.demo import demo_health
    j = demo_health(hours=24)
    ch = j["push"]["channels"]
    assert ch["dingtalk"]["fail_streak"] > 0 and ch["email"]["fail"] == 0
    for c in ch.values():
        assert set(c) == {"ok", "fail", "fail_streak", "last", "last_ok"}


# ---- merged from tests/test_v15126_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


def _func_body(name: str) -> str:
    """提取 PAGE 段内 `async function name()` / `function name()` 的
    函数体（到下一个顶层 function 为止的近似切片）。"""
    s = src()
    m = re.search(r"(?:async )?function %s\b" % re.escape(name), s)
    assert m, f"function {name} 不在源码"
    return s[m.start():m.start() + 2200]


# ---------------- pushLog 换代令牌 ----------------

def test_pushlog_has_seq_token():
    body = _func_body("pushLog")
    assert "++_PV_SEQ" in body, "pushLog 入口未捕获换代令牌"
    assert "_PV_PENDING=true" in body, "pushLog 未置在途标志"


def test_pushlog_stale_response_discarded():
    body = _func_body("pushLog")
    assert "_sq!==_PV_SEQ" in body, "迟到响应未按令牌弃放"


def test_pushlog_pending_reset_in_finally():
    body = _func_body("pushLog")
    assert "finally" in body and "_PV_PENDING=false" in body, \
        "在途标志未在 finally 复位"


# ---------------- chips 键盘焦点恢复 ----------------

def test_chips_refocus_helper_exists():
    s = src()
    assert "function chipsRefocus" in s, "chips 焦点恢复 helper 缺失"


def test_chips_rebuilds_routed_through_helper():
    """五处 chips 重建（userPills/datechips/routechips/platchips/
    chartRoutes）全部经 chipsRefocus——innerHTML 直赋的裸重建点
    归零（表格行/表头已有 data-k 回焦，chips 是最后一处缺口）。"""
    s = src()
    for cid in ("userPills", "datechips", "routechips", "platchips",
                "chartRoutes"):
        assert f'chipsRefocus("{cid}"' in s or \
               f"chipsRefocus('{cid}'" in s or \
               f'chipsRefocus({cid}' in s, f"{cid} 重建未走 helper"


# ---------------- 死类钩子清理 ----------------

def test_qbrk_dead_class_removed():
    assert "qbrk" not in src(), ".qbrk 死类（JS 产出 CSS 零消费）应删"


def test_hlb_dead_class_removed():
    assert ".hlb{" not in src() and "class=\"hlb\"" not in src(), ".hlb 死类钩子（图例色票零声明）应删"


# ---------------- delUser 手风琴索引 ----------------

def test_deluser_open_user_index_shift():
    s = src()
    m = re.search(r"function delUser\b.{0,900}", s, re.S)
    assert m, "delUser 不在源码"
    body = m.group(0)
    # r282 起写点走 setOpenUser 单源（localStorage 槽随写点同步），
    # 索引前移语义不变：删本人收起、删前位者前移
    assert "OPEN_USER===i" in body and "setOpenUser(OPEN_USER-1)" in body, \
        "删除用户未调整 OPEN_USER 索引（重建后错位卡片自动展开）"


# ---------------- FGDK 令牌单源 ----------------

def test_rendercal_fgdk_from_cssv():
    s = src()
    assert "FGDK=cssv('--bg')" in s, \
        "FGDK 手抄字面量应改 cssv('--bg') 单源"


# ---------------- .tj 注入面收口 ----------------

def test_tj_jump_uses_dataset():
    """.tj 跳走势经 dataset 取参：onclick 字符串里不再拼接
    he(f.route)（he() 在 JS 串上下文因实体解码还原引号而无效）。"""
    s = src()
    assert "jumpRowTrend(this.dataset.r,this.dataset.d)" in s, \
        ".tj 应改 dataset 取参"
    assert "jumpRowTrend('${he(f.route)}'" not in s, \
        "内联拼接 f.route 的旧形态应退役"


# ---------------- 预览无表占位注 ----------------

def test_preview_no_table_note():
    assert "预览态无明细总表图" in src(), \
        "with_tables=False 预览缺占位注（r227 P3-8 词面收窄≤40，" \
        "行宽钉 tests/test_v15127_push.py）"


# ---- merged from tests/test_v15275_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_http11_enables_conditional_requests():
    assert 'protocol_version = "HTTP/1.1"' in SRC
    assert 'self.send_header("Content-Length", "0")' in SRC


def test_probe_synthetic_never_claims_raw():
    assert '"raw": None if synthetic else raw_item,' in SRC
    assert "渠道 extra 为空时不得把解析值伪装成 raw" in SRC


def test_calendar_switch_closes_detail():
    seg = SRC[SRC.index("function srxCalPick"):]
    seg = seg[:seg.index("function srxMoreRows")]
    assert "srxDetail" in seg and "srxDmask" in seg
    assert "d.classList.remove('open')" in seg


def test_filters_rerender_mirror():
    assert SRC.count("srxRenderRows();srxRenderMirror()") >= 3
    assert "function srxApplyFilterChange(" in SRC
    seg = SRC[SRC.index("function srxApplyFilterChange("):]
    assert "srxRenderMirror()" in seg[:300]
    sf = SRC[SRC.index("function srxSetFilter"):]
    assert "srxApplyFilterChange()" in sf[:300]


def test_watch_add_rejects_duplicate_instead_of_overwrite():
    seg = SRC[SRC.index("def _watch_apply"):]
    seg = seg[:2500]
    assert "该航班已在关注清单" in seg
    assert 'items.insert(0, entry)' in seg


def test_watch_edit_allows_identity_and_explains():
    # r365：编辑态身份字段可编（航线/日期/航班/时刻/舱位/经停），服务端
    # 重建 flightKey/id；不再要求“移除后重加”。
    assert "function cfgWatchIdentityEditable()" in SRC
    assert "cfgWatchLockIdentity" not in SRC
    assert "可改航线/日期/航班/舱位/渠道/目标" in SRC
    assert "#cwCands button" in SRC and "#cwKnown" in SRC
    assert "trans:(($('cwTrans')||{}).value||'').trim(),cross:" in SRC


def test_watch_time_and_code_validation():
    assert "航班号格式应如 MU541 或 MU541/MU542" in SRC
    assert "起降时刻需为 00:00–23:59" in SRC
    assert r"^[A-Z0-9]{2}\d{1,4}(?:/[A-Z0-9]{2}\d{1,4})*$" in SRC


def test_watch_entry_normalizes_zero_target_and_rejects_bad_fields():
    base = {"from": "SHA", "to": "BKK", "date": _FUTURE,
            "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
            "channels": ["qunar"], "target": 0}
    entry = webui._watch_entry(dict(base))
    assert entry["target"] is None
    with pytest.raises(ValueError):
        webui._watch_entry(dict(base, code="NOT A FLIGHT"))
    with pytest.raises(ValueError):
        webui._watch_entry(dict(base, depTime="25:99"))


def test_overview_best_trend_and_per_card_studio():
    assert "function jumpUserBest(i,date)" in SRC
    assert "jumpUserBest(${i},'${(xd&&xd.date)||(xt&&xt.date)||''}')" in SRC
    assert "function monWatchStudio(id)" in SRC
    assert 'data-monwatchstudio="' in SRC


def test_chart_theme_and_span_labels():
    assert "VIEW==='mon'&&MONTAB==='watch'&&typeof wsDrawChart==='function'" in SRC
    assert "覆盖 '+_sp" in SRC
    assert "const points=(tr.points||[]).length,days=Math.min(tr.days||WS.range,WS.range)" in SRC
    assert "else if(t.state==='wait')wait++" in SRC


def test_search_row_actions_are_roving_tab_stops():
    assert "function srxRowFocus(row)" in SRC
    assert 'onfocus="srxRowFocus(this)"' in SRC
    assert SRC.count('tabindex="-1" data-flighttrend="1"') == 1
    assert SRC.count('tabindex="-1" data-openbtn="1"') == 1


def test_route_trend_flags_do_not_claim_hits():
    # 长窗日桶仍写 flag=0（不得标真达标），但同时下发真实 OHLC；
    # K 线不再把单日 lo 复制成开=收=高=低。
    assert ('pts = lambda rows: [[r["day"], r["lo"], 0, r["open"], '
            'r["close"],\n                         r["hi"]] for r in rows]') in SRC


def test_mirror_age_is_route_scoped_and_stale_calendar_counted():
    seg = SRC[SRC.index("function srxChAge"):]
    assert "srxMirrorScope().filter(f=>f.platKey===ch)" in seg[:500]
    assert "const fallback=rows.filter(f=>srxIsStale(f)).length;" in SRC
    assert "补位·日历·不判达标" in SRC


def test_demo_exempt_from_real_time_staleness_but_live_not():
    assert "const stale=!(S&&S.demo)&&ageH!=null" in SRC
    assert "const _aged=q=>{if(S&&S.demo)return q;" in SRC


def test_mobile_row_actions_are_touch_sized():
    # r386：价格列固定 86px 并右对齐，行与行才对齐成一条竖线
    assert "grid-template-columns:26px minmax(0,1fr) 86px 118px" in SRC
    assert "width:36px;height:36px;border:1px solid var(--line);background:var(--card)" in SRC
    assert "@media(pointer:coarse){.btn2{min-height:36px}}" in SRC


def test_health_detail_rate_excludes_calendar_only_rounds():
    src = io.open(os.path.join(ROOT, "core", "health.py"),
                  encoding="utf-8").read()
    assert 'det_att = att - st["cal_only"]' in src
    assert 'st["detail_rate"] = (st["detail_ok"] / det_att) if det_att else 0.0' in src
    # r365：用户面徽标/tooltip 统一全尝试轮分母，仅日历轮计入分母不计成功
    assert "${detOk}/${att}" in SRC
    assert "${detOk}/${detAtt}" not in SRC


# ---- merged from tests/test_v1558_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1558Pins:
    """webui.py 源码级钉死（同 test_v1553_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- 未保存徽标 ----------

    def test_udirty_badge_visible_when_dirty(self):
        """内联 display 空串回落样式表仍被 .udirty{display:none} 压死，
        复位值必须显式 inline-block（.uhead2 flex 内渲染无差）。"""
        src = self._src()
        assert ".udirty{display:none}" in src          # 默认隐藏保留
        assert "el.style.display=d?'inline-block':'none';" in src
        assert "el.style.display=d?'':'none'" not in src   # 旧撕裂复位值清零

    # ---- 改期胶囊触控热区 ----------

    def test_tg_touch_hotzone(self):
        """本体 ~19px 低于 36px 触控基准；::after 全宽生效（透明无视觉差），
        纵向 -9px 外扩、横向只 -4px 不吃同行链接/行点击。"""
        src = self._src()
        assert ".tg::after{content:'';position:absolute;inset:-9px -4px}" in src
        assert "transition:border-color .15s;position:relative}" in src  # 本体定位锚

    # ---- 304 路径 ETag 撕裂 ----------

    def test_state_snap_paired_read(self):
        """body/etag/gz 必须同锁成对读取：重建线程锁内 body→etag 两步
        落位，请求线程裸读两次可拿旧 body 配新 etag 下发 200，客户端
        按新 etag 落陈旧缓存后被 304 粘死。"""
        src = self._src()
        assert "_STATE_LOCK = threading.RLock()" in src    # 快照读取重入 _latest_state
        assert "def _latest_state_snap():" in src
        # 两段式：_latest_state 先无锁触发/等待重建（锁内等待与
        # 构建线程发布段互等死锁，CI uitest 实锤），三元组同锁读齐不变量保持
        assert (
            "_latest_state()\n    with _STATE_LOCK:\n"
            "        body = _STATE_CACHE[\"body\"]" in src
        )
        assert "body, etag, gz = _latest_state_snap()" in src
        assert "_latest_state_body" not in src             # 旧裸读入口清零

    # ---- mkact 双绑 ----------

    def test_mkact_skips_inline_onkeydown(self):
        """模板自带内联 onkeydown（.hc/.pbar/#pvClose）不再叠加监听——
        一次 Enter 曾连发两个相同 /api/logtail。"""
        assert "if(el.getAttribute('onkeydown'))return;" in self._src()

    # ---- 挡位 chips 焦点 ----------

    def test_buildwinsel_inplace_update(self):
        """WINS 恒定：子节点齐时原位翻 on 类，不重建节点——table 每拍
        整组 innerHTML 重建曾把刚点按/回车的 .schip 换掉焦点丢回 body。"""
        src = self._src()
        assert "want.some((w,i)=>have[i]!==w)" in src
        assert "c.classList.toggle('on',c.dataset.w===cw)" in src

    # ---- 渠道空选回填 ----------

    def test_platchips_empty_selection_stable(self):
        """空集=全部是用户显式选择（_platsInit），10s 轮询 buildChips
        不得回填全亮；重置/恢复路径语义不回退。"""
        src = self._src()
        assert "_platsInit:false" in src                                   # FLT 声明
        assert "if(keep.length||FLT._platsInit){FLT.plats=new Set(keep);FLT._platsInit=true;}" in src
        assert "FLT.plats=new Set();FLT._platsInit=false;" in src          # resetFlt 回全选语义
        assert "FLT.plats=new Set(j.plats);FLT._platsInit=true;" in src    # restoreUI 显式选择

    # ---- 卡头转义 ----------

    def test_ucard_head_escaped(self):
        """与同函数用户 pills 的 he 纪律对齐。"""
        src = self._src()
        assert "${he(x.name)}</span>" in src
        # r233 W-3 routesTxt 改「、」分段 nowrap 后 he 纪律逐段保留：
        # 每段 map 内 he(s)（转义面不变，形态演进钉面随消费点走）
        assert ("String(x.routesTxt||'').split('、')"
                ".map(s=>'<span class=" + '"' + "nw" + '"' + ">'+he(s)+'</span>')") in src

    # ---- 行指纹注入面 ----------

    def test_row_fingerprint_sanitized(self):
        """k 含渠道自由文本（trans/cross），构造点去引号/尖括号/反斜杠
        （反斜杠为 Soldier m4 同批扩员：尾反斜杠转义 onclick 串收尾引号）；
        he 在单引号 JS 上下文会因实体解码还原引号反而无效。"""
        assert ".replace(/[\"'<>&\\\\]/g,'_')" in self._src()

    # ---- CSS 死代码 ----------

    def test_dead_css_removed(self):
        src = self._src()
        assert ".calcell.none" not in src      # renderCal 只产 calcell/best/link
        assert "btn2 ical" not in src          # 类无规则无消费

    # ---- 灰点令牌 ----------

    def test_pill_dot_tokenized(self):
        src = self._src()
        assert "93a3b4" not in src             # 亮暗同值硬编码清零（含注释）
        assert "border-radius:50%;background:var(--mut);flex:none}" in src


# ---- merged from tests/test_v1589_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    import webui as _w
    return _w.PAGE


def _lum(hexc):
    """WCAG 相对亮度：#rrggbg → 0..1。"""
    h = hexc.lstrip("#")
    ch = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        ch.append(c / 12.92 if c <= 0.04045
                  else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _ratio(fg, bg):
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# ---- P2-1/P2-2 对比度：公式化断言（非 large 文本 ≥4.5） ----

def test_contrast_stl_lay_warning_on_card():
    """--stl 亮值 #a84c15 对 card 底 #f5f8fb ≥4.5（#c0561a 4.29 欠）。"""
    assert _ratio("#a84c15", "#f5f8fb") >= 4.5


def test_contrast_ok_txt_on_qual_tint_and_okbg():
    """--ok-txt #0b6e39 对 qual 行 tint #ecf5f0 与 okbg #e9f4ec 均
    ≥4.5（--green 4.28~4.34 欠）——bagtag/stl.lay.ok 收编同源。"""
    assert _ratio("#0b6e39", "#ecf5f0") >= 4.5
    assert _ratio("#0b6e39", "#e9f4ec") >= 4.5


def test_page_tokens_pinned():
    """改色落点源码钉：--stl 亮值、bagtag/stl.lay.ok 字面走 --ok-txt、
    暗色日历 alpha 上限 0.56。"""
    p = _page()
    assert "--stl:#a84c15" in p
    assert re.search(r"\.bagtag\{[^}]*color:var\(--ok-txt\)", p), \
        "bagtag 字面未走 --ok-txt"
    assert ".stl.lay.ok{color:var(--ok-txt)}" in p
    assert "Math.min(0.40,(r-1)*0.9)" in p, "暗色日历 alpha 斜率 0.9（r54 红墙恢复梯度；0.56 上限 AA 精算不变）"


# ---- P2-3 触控热区 ----

def test_touch_targets_hotzone():
    p = _page()
    # r255 P3-1：a.vw 纯 inline 盒 ::after 包含块取行内片段 content-box，
    # -9px 只兑现 34px，纵向提到 -11px（语义担保不变：纵向补到触控基准）
    assert ".pvx::after,a.vw::after{content:'';position:absolute;inset:-11px -8px}" in p, \
        "a.vw 纵向热区未补到触控基准"
    # 触控地板 padding:8px 0 在位（r232 词组 nowrap 语义保持；r285 审计
    # 实测 5px 态本体 27px,8px 态本体 33px+::after 纵向外扩命中区
    # ≥36px 达标，钉面同步）
    assert re.search(r"\.demoBar a\{[^}]*padding:8px 0[^}]*white-space:nowrap\}", p), \
        "demoBar 链接触控地板或词组 nowrap 缺失"


# ---- P2-4/P2-5 switchView 回程补拍 ----

def test_switchview_mon_return_repaints():
    p = _page()
    # 窗口锚到块界（switchView 体止于下一函数）防插入敏感假红——
    # 固定字符窗曾被块内合法新增（登录轮询停表）推过上限
    i = p.index("if(v==='mon'&&_from==='cfg'){")
    j = p.index("async function loadLogin")
    blk = p[i:j]
    assert "if(MONTAB==='trend')chart();" in blk, "回程未补走势重绘"
    # r322：健康格重判批次收敛 _hfit 单源（弹性实判定+滚动暗示），
    # 字面从块内消失——锁批次接线在场（语义担保不变）
    assert "forEach(_hfit)" in blk, "回程未补健康线重判批次"


# ---- P2-6 日历死通道收口 ----

def test_calendar_dead_channel_removed_but_bridge_alive():
    """dfull 映射/calcell.link 死通道整体收口；jumpCalDate 本体保留
    （走势 canvas 点击 jumpTrendDetail 是活通道）。"""
    p = _page()
    assert "const dfull" not in p, "dfull 死映射未删"
    assert ".calcell.link" not in p, "死通道 CSS 未删"
    assert "calcell.link" not in p, "mkactAll 选择器残留死类"
    assert "function jumpCalDate" in p, "误删活通道 jumpCalDate"
    assert "jumpTrendDetail" in p and "jumpCalDate(d)" in p


# ---- P2-8 pill 三态 title 单源 ----

def test_pill_state_title_single_source():
    p = _page()
    assert "function pillState(txt,cls,title)" in p
    assert "数据通道状态：服务异常" in p
    assert "数据通道状态：服务未启动" in p
    assert "数据通道状态：未配置" in p
    assert "$('pill').textContent" not in p, "pill 直写散点未收编单源"
    assert "跳转达标明细（仅达标档，将重置现有筛选）" in p, "常态 title 丢失"


# ---- P2-9 注释如实 + KPI 飞猪税前标 ----

def test_resetflt_comment_truthful():
    p = _page()
    m = re.search(r"function resetFlt\(\)\{(.{0,320})", p, re.S)
    assert m, "resetFlt 锚点丢失"
    assert "空集=全部" in m.group(1), "resetFlt 注释与 buildChips 语义脱节"
    assert "回填全亮" not in p, "失实词面残留"


def test_kpi_fliggy_pretax_badge():
    p = _page()
    # r326 A2 起国际行豁免（飞猪国际价恒含税总价，「税前」成假警示）
    assert "brief.plat==='fliggy'&&!brief.intl?'<span class=\"pretax\"" in p, \
        "KPI 卡飞猪价缺税前标注（含国际豁免档）"
    assert "FLIGGY_TAX_PAD>0 时 qual/推送用含税 eff 价" in p, \
        "pad 同步律注释缺失"


# ---- merged from tests/test_v171_webui.py ----

class TestWebuiV171Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def _notify_src(self):
        src = self._src()
        return src[src.index("NOTIFY_PAGE"):]

    def test_p1_glcell_switch_focus_not_swallowed(self):
        """：glcell hover/focus 豁免 .switch，开关回落 UA 焦点环。"""
        src = self._src()
        assert ".glcell input:not(.switch):hover{border-bottom-color:var(--mut)}" in src, \
            "glcell hover 未豁免 .switch"
        assert ".glcell input:not(.switch):focus{outline:none;" in src, \
            "glcell focus 未豁免 .switch"
        # 旧形态（吞焦点环的无豁免 focus 规则）必须消失
        assert ".glcell input:focus{" not in src, \
            "存在未豁免 .switch 的 glcell focus 规则（键盘焦点环被吞回潮）"

    def test_p2a_tj_hitzone_family(self):
        """P2-A：.tj 入热区家族（relative +::after 纵向 -11px；
        r255 P3-1 纵向 -9px→-11px，inline 盒包含块律同 a.vw。
        横向 r318 收 0：行中心偶发几何下横向外扩放大跳走势劫持面，
        纵向触控基准保留、横向不越出本体词组）。"""
        src = self._src()
        assert ".dchip .dx,.pvx,a.vw,.hc,.tj{position:relative}" in src, \
            ".tj 未入 position:relative 组"
        assert ".tj::after{content:'';position:absolute;inset:-11px 0}" in src, \
            ".tj 缺 ::after 热区外扩（纵向 -11px、横向收 0 形态）"

    def test_p2b_health_cells_elastic_breakpoint(self):
        """P2-B→r322：弹性档承载面退役静态门槛改 .fit 实判定类
        （门槛按 96 格满密度校准，轻轮次在门槛下带放得下却恒左聚，
        空腔 16→132px 实测——判据从「视口带宽」变「格带可容纳性」，
        全带宽正确）。钉实效档（.fit 类 clip+均分）与判定单源在场，
        锁静态门槛禁复活。"""
        src = self._src()
        assert ".hcells.fit{overflow:hidden;overflow:clip}" in src, \
            "弹性档 clip 容器（防 hover 呼吸抖动）未挂 .fit 类"
        assert ".hcells.fit .hc{width:auto;flex:1 1 6px}" in src, \
            "弹性格均分规则未挂 .fit 类"
        assert "function _hfit(x){" in src, "弹性实判定单源 _hfit 缺席"
        assert "@media(min-width:1024px){" not in src, \
            "静态 1024 弹性门槛残留（轻轮次左聚空腔回潮）"
        assert "@media(min-width:1440px){\n  .hc{width:auto;flex:1 1 6px}\n }" not in src, \
            "1440 旧弹性档残留（1180-1439 空腔回潮）"

    def test_p2c_glcell_text_16px_two_media(self):
        """P2-C：≤760 与 coarse 两份清单各补 glcell 16px !important。
        r333 起选择器并档 #cpq（同值同声明族扩展，#cpq 16px 防放大
        与 glcell 同源）——计数钉随并档改写锁新串。"""
        src = self._src()
        n = src.count(
            ".glcell input[type=text],#cpq{font-size:16px!important}")
        assert n == 3, "glcell+#cpq 16px 防放大钉应恰在三份触控媒体清单(≤760/≤900/901+): %d" % n
        assert ".glcell input[type=text]{font-size:16px!important}" not in src, \
            "并档前旧串残留（三处应全部并档 #cpq）"

    def test_p2c_glcell_input_explicit_text_type(self):
        """P2-C 伴随钉：glcell text/ro 型显式输出 type="text"——原生成
        `<input`（省略 type 属性）令 input[type=text] 选择器命中 0 元素，
        16px 防放大钉空转（行为钉预演抓回：HTML 默认 text 但属性选择器
        不认隐式形态）。"""
        src = self._src()
        assert '(type===\'text\'||type===\'ro\')?\' type="text"\':\' type="number"\'' in src, \
            "glcell 未显式输出 type=\"text\"（16px 防放大钉空转回潮）"

    def test_p2d_notify_tokens_aligned(self):
        """P2-D：notify --mut 对齐主站 #5a6c7d；.logo 圆角走 --r3 令牌。"""
        nsrc = self._notify_src()
        assert "--mut:#5a6c7d" in nsrc, "notify 亮色 --mut 未对齐主站"
        assert "--mut:#617384" not in nsrc, "notify 旧 --mut 值残留"
        assert "--r3:9px" in nsrc, "notify :root 缺 --r3 令牌"
        assert ".logo{width:26px;height:26px;border-radius:var(--r3);" in nsrc, \
            "notify .logo 圆角未走 --r3 令牌"
        assert "border-radius:7px" not in nsrc, "notify .logo 旧 7px 硬编码残留"


# ---- merged from tests/test_v180_obsfix.py ----

def _row(t):
    return {"platform": "ctrip", "from_city": "URC", "to_city": "SHA",
            "depart_date": "2026-10-05", "price": 2000.0,
            "extra": "", "fetched_at": t}


# ---- P1-1 轮界 420s ----

def test_round_gap_default_dplits_8min():
    """默认轮界 420s：8 分钟（480s）断口切轮——生产实测最小轮间隔
    483-503s，600s 阈值曾把这类相邻轮并桶（曲线/列表口径分歧根因）。"""
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:08:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 1


def test_round_gap_500s_splits():
    """500s 断口（实测区间内）切轮：420 < 500 ≤ 600。"""
    rows = ["2026-09-20 10:16:40", "2026-09-20 10:08:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 1


def test_round_gap_intra_round_holds():
    """轮内错峰（3 分钟）不切：一轮多查询跨 2-3 分钟 < 420s。"""
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:13:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 2


def test_report_bucket_gap_420_same_value():
    """曲线桶轮界与列表同值 420（两端同改——两套阈值并存曾「图有列无」）。"""
    src = open("report.py", encoding="utf-8").read()
    assert ".total_seconds() <= 420" in src, "曲线桶轮界未同步 420"


# ---- P2-4 normalize stopCity 首个非空段 ----

def test_norm_stopcity_first_nonempty():
    from core.flightnorm import normalize
    f = {"stopCitys": ";庆阳", "platform": "qunar"}
    normalize(f)
    assert f.get("stopCity") == "庆阳", "前导分号脏值致 stopCity 丢失"


def test_norm_stopcity_clean_first():
    from core.flightnorm import normalize
    f = {"stopCitys": "西安;库尔勒", "platform": "qunar"}
    normalize(f)
    assert f.get("stopCity") == "西安"


# ---- P2-8 ctrip labels 组装去重 ----

def test_ctrip_labels_dedup():
    """aset 同词重复（dump 两处 tagarea 同词）不再重复拼接。"""
    from crawlers.ctrip import CtripCrawler
    seg = {"basinfo": {"flgno": "HO1256"},
           "dateinfo": {"ddate": "2026-10-06 09:30:00",
                        "adate": "2026-10-06 14:05:00"},
           "dportinfo": {"city": "URC", "aport": "URC", "bsname": ""},
           "aportinfo": {"city": "SHA", "aport": "SHA", "bsname": "T2"}}
    item = {"mutilstn": [seg],
            "policyinfo": [{"tprice": 800, "quantity": 5}],
            "aset": [{"tagarea": [{"tagcnt": "宠物友好"},
                                  {"tagcnt": "宠物友好"},
                                  {"tagcnt": "轻飞享奖里程"},
                                  {"tagcnt": "轻飞享奖里程"}]}]}
    fs = CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))
    assert fs[0]["labels"] == "宠物友好·轻飞享奖里程"


# ---- P2-8 qunar transferService 前缀重复 ----

def test_qunar_svc_txt_no_dup_prefix():
    from crawlers.qunar import QunarCrawler
    # tsl 自带 tsn 前缀（'中转优享：…'）不再重复拼 '中转优享:'
    assert QunarCrawler._svc_txt("中转优享", "中转优享：免费餐食") \
        == "中转优享：免费餐食"
    assert QunarCrawler._svc_txt("中转优享", "免费餐食") \
        == "中转优享:免费餐食"
    assert QunarCrawler._svc_txt("", "免费餐食") == "免费餐食"
    assert QunarCrawler._svc_txt("中转优享", "") == ""


# ---- P2-7 停用航线不进 routesArr ----

def test_user_state_filters_disabled_routes():
    """_user_state 的 routes 列表推导过滤 enabled is False（与日报
    _chart_routes 已滤停用对齐；停用线作 routes[0] 曾使顶层 history
    恒空）。源码钉：_user_state 重不可直测，钉过滤条件在场。"""
    src = webui_full_src()
    assert 'if r.get("enabled") is not False' in src or \
        "if not r.get(\"enabled\") is False" in src or \
        'r.get("enabled") is not False' in src, \
        "停用航线过滤缺失（enabled:false 仍进 routesArr）"


# ---- merged from tests/test_v181_webui.py ----

class TestWebuiV181Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- D-1 退改费三端消费 ----

    def test_refund_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 returnFee/changeFee（缺它=孤儿键）。"""
        src = self._src()
        assert '"returnFee": _int_or_none(f.get("returnFee"))' in src, \
            "白名单未透传 returnFee"
        assert '"changeFee": _int_or_none(f.get("changeFee"))' in src, \
            "白名单未透传 changeFee"

    def test_refund_badge_pretax_with_title(self):
        """价格格退改徽标（pretax 同位）+ title 说明语义（-1=不可办理）。"""
        src = self._src()
        assert "_rc_txt(f)" in src, "退改词面未走 _rc_txt 单源"
        i0 = src.index("_rc_txt(f)}")
        seg = src[max(0, i0 - 240):i0 + 40]
        assert "pretax" in seg, "退改徽标未复用 pretax 同位样式"
        assert "title=" in seg and "退" in seg and "不可" in seg, \
            "退改徽标缺 title 或未说明 -1 语义"

    def test_refund_wordface_minus1_and_free(self):
        """词面规则：双 0=免费退改；-1=不可退/不可改；有值=退￥N·改￥M。"""
        src = self._src()
        assert "免费退改" in src
        assert "'不可'+lbl" in src.replace('"', "'").replace('"', "'"), \
            "词面缺 -1 不可办理形态"
        i0 = src.index("function _rc_txt")
        seg = src[i0:i0 + 320]
        assert "returnFee===0" in seg and "changeFee===0" in seg, \
            "双 0 免费退改判定缺失"

    def test_refund_csv_column(self):
        """CSV「退改」列与徽标同词面单源（head+行值两处）。"""
        src = self._src()
        assert "'退改'" in src or "退改'" in src, "CSV head 缺退改列"
        assert "_rc_txt(f)" in src, "CSV 行值未走 _rc_txt 单源"

    # ---- audit P2 六案 ----

    def test_p2_footer_demo_sentinel(self):
        """页脚版本哨兵：demo 值不加 v 前缀（演示站不再出现 vdemo）。"""
        src = self._src()
        assert "s.version!=='demo'" in src, \
            "页脚 v 前缀未排除 demo 哨兵值"

    def test_p2_footer_port_dynamic(self):
        """页脚端口随实际监听（state 带 svc，模板不再硬编码 8765）。"""
        src = self._src()
        assert '"svc"' in src, "state 未携带实际 host:port"
        assert "本地服务 127.0.0.1:8765" not in src, \
            "页脚端口硬编码未清除"
        assert "s.svc" in src, "页脚未消费 svc 字段"

    def test_p2_footer_kbd_hidden_on_coarse(self):
        """触屏隐藏键盘快捷键提示（pointer:coarse 媒体块）。
        检测点改全文级：coarse 隐藏块已挪样式区尾（同选择器 ≤760
        块的层叠序钉在 test_v187_webui），邻位检测点失效。"""
        src = self._src()
        assert "kbdtips" in src, "快捷键提示段未挂 kbdtips 类"
        assert "@media(pointer:coarse){.kbdtips{display:none}}" in src, \
            "kbdtips 隐藏未挂 coarse 指针媒体查询"

    def test_p2_price_fire_fixed_width(self):
        """价格列 🔥 定宽占位（qual 行与非 qual 行 ￥ 共起点）。"""
        src = self._src()
        assert 'class="fire"' in src, "🔥 未改定宽占位 span"
        i0 = src.index(".price .fire{")
        seg = src[i0:i0 + 140]
        assert "width:19px" in seg, "fire 占位未定宽"
        assert "<span class=\"fire\">'+(f.qual?'" in src, "fire span 未条件承载达标图标"

    def test_p2_kpi_bar_hit_full_and_title(self):
        """KPI 进度条达标态满条（读的人先问能不能出手）+ title 解码。"""
        src = self._src()
        i0 = src.index('class="bar"')
        seg = src[i0:i0 + 320]
        assert "title=" in seg, "KPI bar 缺解码 title"
        assert "width:${hit?100" in seg.replace(" ", ""), \
            "达标态未满条（width 100%）"

    def test_p2_pbar_pvx_hover_transition(self):
        """脉冲柱/关闭钮 hover 过渡与全站 0.12s 家族同律。"""
        src = self._src()
        ip = src.index(".pbar{")
        seg_p = src[ip:ip + 260]
        assert "transition" in seg_p, ".pbar 缺 transition"
        ix = src.index(".pvx{")
        seg_x = src[ix:ix + 220]
        assert "transition" in seg_x, ".pvx 缺 transition"


# ---- merged from tests/test_v183_webui.py ----

class TestWebuiV183Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- Minor-1 catch 分支按 S 分叉，保旧不掀卡 ----

    def test_load_catch_branch_split(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 4200]
        ci = seg.index("catch(e){LASTTXT")
        cseg = seg[ci:ci + 560]
        assert "if(S)" in cseg, "fetch 失败 catch 分支未按有无旧数据分叉"
        assert "服务异常" in cseg, \
            "catch 有旧数据未落中性词面（「服务未启动」与服务在线自相矛盾）"
        assert "保留上次结果" in cseg, "catch 有旧数据未标注保旧"
        assert "LASTTXT=''" in cseg, \
            "catch 未失效签名：恢复轮同文本将被跳过，「服务异常」词面驻留不退场"
        assert "_markStale()" in cseg, "冷启动 catch 仍需错误态落点"
        pre = cseg[:cseg.index("else{")]
        assert "_markStale()" not in pre, "有旧数据分支不得掀骨架（保陈旧数据交互不失效）"

    def test_state_errbody_wordface(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 4200]
        ei = seg.index("错误体分支")
        eseg = seg[ei:ei + 560]
        assert "服务异常" in eseg, "错误体（服务在线）分支 pill 词面过重"

    # ---- Minor-2 先解后存 ----

    def test_load_parse_before_lasttxt(self):
        # r244 P3-2 重构后钉面随行为演进改写（语义担保保留，十八§7）：
        # JSON.parse 移入独立 try/_pj 门，「LASTTXT=t」只在解析成功分支
        # 写定；非 JSON 失败体显式 LASTTXT=''（比旧序更强）。窗口 400
        # →1200 只因结构行数增加，断言本质仍是「先解后存」
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 1200]
        pi = seg.index("JSON.parse(t)")
        li = seg.index("LASTTXT=t")
        assert pi < li, "LASTTXT 先于 JSON.parse 写定：畸形 200 体一次即驻留"
        # 非 JSON 失败分支必须显式失效签名（恢复轮同文本可重入）
        nj = seg.index("_pj=false")
        ns = seg.index("LASTTXT=''")
        assert nj < ns < li, "非 JSON 失败体未失效签名或顺序错位"

    # ---- Minor-3 heFriendly 字素安全截断 ----

    def test_hefriendly_grapheme_safe(self):
        src = self._src()
        i0 = src.index("function heFriendly")
        seg = src[i0:i0 + 320]
        # 1) 必须按**码点**切（不是 String.prototype.slice，那会劈出孤立代理对）
        assert "Array.from(e).slice(0," in seg and ".join('')" in seg, \
            "heFriendly 仍按 UTF-16 码元截断（emoji 尾端劈出孤立代理对）"
        # 2) 上限默认 80，且可被调用点放宽（登录失败要把「缺哪个 cookie」读完）
        assert "const cap=(max&&max>0)?max:80;" in seg, \
            "heFriendly 的默认上限不再是 80，或丢了可配置上限"
        # 3) 旧的字面量码元截断不许回来
        assert "e.slice(0,80)" not in seg, "旧码元截断残留"

    # ---- audit v183 P2-1 health/pulse 脱离 state 签名门 ----

    def test_health_pulse_outside_signature_gate(self):
        src = self._src()
        i0 = src.index("async function load()")
        i1 = src.index("function pct(", i0)
        seg = src[i0:i1]
        hp = seg.rindex("health();pulse();")
        assert hp > seg.index("catch(e){", seg.index("LASTTXT=t")), \
            "health/pulse 仍在 state 签名门内：state 文本不变时健康/脉冲永不刷新（错误词面驻留）"

    # ---- audit v183 P2-2 冷启动错误体词面同轨 ----

    def test_markstale_wordface_param(self):
        src = self._src()
        i0 = src.index("function _markStale(")
        # 窗口=函数体（到 load 定义），固定 400 字符窗对合法注释增厚
        # 过敏（卅一§3：窗口长度是实现细节，锚结构才是钉面）
        i1 = src.index("async function load()")
        seg = src[i0:i1]
        assert "(svc||'服务未启动')" in seg, \
            "_markStale 未参数化词面（冷启动 500 错误体与服务在线状态混轨）"
        seg1 = src[i1:i1 + 6000]
        ei = seg1.index("错误体分支")
        eseg = seg1[ei:]
        assert "_markStale('服务异常')" in eseg, \
            "错误体冷启动分支未传「服务异常」词面（骨架与 pill 混轨）"


# ---- merged from tests/test_v185_webui.py ----

class TestWebuiSeatTilt:
    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_whitelist_passthrough_int(self):
        src = self._src()
        # 白名单透传:int 协议转写(非数字→None 前端不占位,七批先例)
        assert '"seatTilt": _int_or_none(f.get("seatTilt"))' in src, \
            "webui 白名单缺 seatTilt 透传(int 协议)"

    def test_cabin_code_title_annotation(self):
        src = self._src()
        # 渲染门:cabinCode 悬停 title 并注座椅倾斜(ctrip cabinCode
        # 100% 在场与 seatTilt 同源配对;缺一不注)
        assert "座椅倾斜" in src and "seatTilt" in src, \
            "cabinCode title 缺座椅倾斜注记"

    def test_csv_column(self):
        src = self._src()
        # CSV「座椅倾斜」列:cabinCode 列之后(导出分析消费面)
        i0 = src.index("(f.cabin||'').replace(/<[^>]*>/g,'')")
        seg = src[i0:i0 + 400]
        assert "seatTilt" in seg, "CSV 缺座椅倾斜列(cabinCode 列后)"


class TestAuditV185Design:
    """r184 WebUI 审计落地钉(P1×1+P2×7,设计层)。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p1_pulse_legend_centered_at_1440(self):
        src = self._src()
        # ≥1440 解锁后 statline 全宽/柱区居中/图例左贴边三轴分裂——
        # 图例与柱区同轴。同轴条件全宽度域无条件生效（柱区 center
        # 全宽域生效；窄档少轮次双轴残留一并收口，覆盖钉在
        # test_v188_webui）
        assert "#pulseLegend{justify-content:center}" in src, \
            "图例未与脉冲柱区同轴居中"

    def test_p2_jump_entries_declare_filter_reset(self):
        src = self._src()
        # pill 与「全线最低」mchip 跳转会隐式 resetFlt 清用户筛选——
        # title 必须声明副作用,jumpQual 落地后 toast 同步告知
        assert src.count("将重置现有筛选") >= 2, \
            "pill/mchip title 未声明 resetFlt 副作用"
        i0 = src.index("function jumpQual()")
        assert "toast(" in src[i0:i0 + 400], "jumpQual 缺落地 toast"

    def test_p2_tablist_semantics(self):
        src = self._src()
        # 退役改写(r275)：三族标签页(监控 tabs/明细筛选 tabs/配置导航)
        # 统一 button 形态——tablist/tab 旧形制禁复活(#montabs 混入
        # 多租户 chip 后纯性破缺，按 #tabs 同律降级)，aria-pressed
        # 动态回写为实效档(mkactAll 同源挂载)
        assert "function tabAria()" in src, "tabAria 助手缺"
        # r345：日期模式条（setDateMode）是唯一合法 tab 形制
        _i = src.index("function setDateMode(")
        assert "setAttribute('aria-selected'" in src[_i:_i + 700], \
            "日期模式条 aria-selected 缺席"
        # aria-selected 仅限 listbox option / 日期模式条；mtab 走 aria-pressed
        assert "setAttribute('aria-pressed'" in src, "aria-pressed 实效档缺席"
        assert "querySelectorAll('.mtab').forEach(x=>" in src and \
            "aria-pressed" in src, ".mtab aria-pressed 回写缺"

    def test_p2_form_a11y_trio(self):
        src = self._src()
        assert 'aria-label="搜索配置项"' in src, "#cfgSearch 缺 label"
        assert 'id="fltBtn" aria-expanded="false"' in src, \
            "#fltBtn 初始 aria-expanded 缺"
        # r199 后抽屉开合收 setFltOpen 单源（togFlt/Esc/`/` 三口共用）
        _seg = src.split("function setFltOpen")[1][:400]
        assert 'aria-expanded' in _seg, "setFltOpen 未同步 aria-expanded"
        assert "setFltOpen(" in src.split("function togFlt")[1][:200], \
            "togFlt 未走 setFltOpen 单源"
        i0 = src.index('id="savebar"')
        assert 'role="status"' in src[i0 - 40:i0 + 60], "savebar 缺 role=status"

    def test_p2_montabs_grid_narrow(self):
        src = self._src()
        # ≤540 单行横滚吸顶 + 541-760 同款单行形制（窄档统一单行吸顶，
        # 两列网格场景随吸顶全档化退场）。r224 起块首插入
        # :root{--mtabsh:52px}（scroll-padding 消费带补定义），钉锚拆
        # 媒体条件与形制两段
        assert "#montabs{position:sticky;top:var(--hdh" \
            in src, "montabs 窄档吸顶缺失"
        i_band = src.index("@media(min-width:541px) and (max-width:760px)")
        seg = src[i_band:i_band + 900]
        assert "#montabs{display:flex;gap:6px;" in seg, \
            "541-760 带未收敛单行形制"

    def test_p2_pulse_legend_swatch_uniform(self):
        src = self._src()
        # 图例双色票形制同排(渠道 12×8 方块 vs 红帽 18×4 细条)——
        # 红帽改与渠道同规格 inline i
        assert '<i style="background:var(--red);width:12px;height:8px' in src, \
            "红帽色票未统一 12×8 形制"

    def test_p2_pill_static_affordance(self):
        src = self._src()
        assert ".pill::after{content:" in src, "pill 缺静态可点线索"

    def test_p2_kbd_tips_block_narrow(self):
        src = self._src()
        # goal 轮分隔线随行：桌面带 border-left 语义分隔，窄带独立
        # 成行时分隔线与衬距一并复位（border 复位缺席会把竖线带进
        # 折行首）
        assert "@media(max-width:760px){.kbdtips{display:block;margin:6px 0 0;margin-left:0;padding-left:0;border-left:none}}" \
            in src, "窄窗快捷键教学未独立成行（或分隔线未复位）"


# ---- merged from tests/test_v186_webui.py ----

class TestWebuiChildFare:
    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_whitelist_passthrough_num(self):
        src = self._src()
        # 白名单透传:float 协议转写(_num_or_none;儿童半价 X.5 不截断)
        assert '"childPrice": _num_or_none(f.get("childPrice"))' in src, \
            "webui 白名单缺 childPrice 透传(float 协议)"
        assert '"infantPrice": _num_or_none(f.get("infantPrice"))' in src, \
            "webui 白名单缺 infantPrice 透传(float 协议)"

    def test_num_or_none_helper(self):
        src = self._src()
        # float 协议帮手:_int_or_none 同型(脏值→None 前端不占位)
        assert "def _num_or_none(v):" in src, "_num_or_none 帮手缺"
        i0 = src.index("def _num_or_none(v):")
        assert "float(v)" in src[i0:i0 + 200], "_num_or_none 未用 float 转写"

    def test_name_cell_title_annotation(self):
        src = self._src()
        # 渲染门:航班名格悬停 title 注记儿童/婴儿价(有值才注)
        assert "儿童价" in src and "childPrice" in src, \
            "航班名 title 缺儿童价注记"
        assert "婴儿价" in src and "infantPrice" in src, \
            "航班名 title 缺婴儿价注记"

    def test_name_cell_title_gate_covers_child_fare(self):
        src = self._src()
        # 外层渲染门必须把童婴价纳入:labels/labelNote/baggage/bizPrice
        # 四键全空(tuniu 窄体无公务舱多数形态、qunar H5)时童婴价仍可
        # 独立成注——门漏扩=注记段整段不渲染(内层分隔符按独立成注
        # 设计,内外门自相矛盾的功能空转形态)
        i0 = src.index('<td${((f.labels||f.labelNote||f.baggage'
                       '||f.carryon||f.bizPrice!=null)')
        seg = src[i0:i0 + 140]
        assert "f.childPrice!=null" in seg and "f.infantPrice!=null" in seg, \
            "航班名 title 外层渲染门未纳入童婴价(四键全空形态整段不渲染)"

    def test_csv_column(self):
        src = self._src()
        # CSV「儿童/婴儿」列:表头尾部追加(既有列序零位移)
        assert "'儿童/婴儿'" in src, "CSV 表头缺「儿童/婴儿」列"
        i0 = src.index("改期最低")
        assert "childPrice" in src[i0:i0 + 2100], \
            "CSV 行值缺 childPrice 消费(表头后近邻)"


class TestWebuiRefundCurrentTier:
    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_price_badge_title_declares_tier(self):
        src = self._src()
        # 价格格退改徽标 title:注明「当前档位」语义(调研结论 N8:
        # qunar 渠道仅下发当前时点阶梯档,起飞前分档变动)
        assert "当前档位" in src, "退改徽标 title 缺当前档语义注明"


class TestWebuiV186Audit:
    """WebUI 审计 P2×5 落地钉(布局/自适应/交互打磨)。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p2_1_coarse_901_touch_checklist(self):
        src = self._src()
        # >901px coarse 触控块补齐姊妹块清单(.cnav/.hbtn/输入 38px/
        # switch 热区/16px 字号)——iPad Pro 横屏触控基准欠账
        # 窗口取块边界（配平大括号），不锚固定字符数——PAGE 增厚会
        # 把目标声明推出固定窗口（LESSONS 卅一§3 窗口钉对插入敏感）
        i0 = src.index("@media(pointer:coarse) and (min-width:901px){")
        depth = 0; i1 = i0
        for i1 in range(i0, min(i0 + 8000, len(src))):
            if src[i1] == "{":
                depth += 1
            elif src[i1] == "}":
                depth -= 1
                if depth == 0:
                    break
        seg = src[i0:i1 + 1]
        for needle in (".cnav{padding:10px 14px}",
                       ".hbtn{min-height:36px;min-width:36px}",
                       ".switch::before{content:'';position:absolute;inset:-8px}",
                       "font-size:16px"):
            assert needle in seg, f"901+ 触控块缺 {needle}"

    def test_p2_2_ssub_wrap_at_900(self):
        src = self._src()
        # 「用时」尾段截断带 391-509px:ssub 放行换行上提 ≤760；
        # r225 同病灶残余带 761-900 并入（放行门 760→900）
        assert "@media(max-width:900px){.stat .ssub{white-space:normal}}" in src, \
            "≤900 档缺 ssub 换行放行"

    def test_p2_3_hdmeta_wrap_at_900(self):
        src = self._src()
        # 生产态(cdt 倒计时在场)窄机临界溢出:≤900 补 flex-wrap
        assert "@media(max-width:900px){.hdmeta{flex-wrap:wrap}}" in src, \
            "≤900 档缺 hdmeta 折行"

    def test_p2_4_resize_rejudge_xhint(self):
        src = self._src()
        # resize 几何变化点重判健康格（r322 起批次回调收敛 _hfit 单源：
        # 弹性实判定+滚动暗示同批；窗口放宽到批次尾防插入敏感——卅一§3）
        i0 = src.index("window.addEventListener('resize'")
        i1 = src.index("},200);});", i0)
        assert "forEach(_hfit)" in src[i0:i1], \
            "resize 回调缺 _hfit 批次重判（几何变化点弹性档失判回潮）"

    def test_p2_5_kbdtips_margin_not_inline(self):
        src = self._src()
        # 内联 margin-left:14px 在 ≤760 独立成行后造成右偏——
        # 挪为基础 CSS(媒体块 margin 简写可覆写),内联清零。
        # goal 轮：基础块升级为 margin+衬距+语义分隔线（服务信息｜
        # 键位教学两组的视觉分界），钉面随形态演进改写
        assert 'class="kbdtips" style=' not in src, \
            "kbdtips 内联 margin 残留"
        assert ".kbdtips{margin-left:14px;padding-left:14px;border-left:1px solid var(--line2)}" in src, \
            "kbdtips 基础 margin+语义分隔线缺"


# ---- merged from tests/test_v220_affordance.py ----

pytestmark = pytest.mark.skipif(
    os.environ.get("R220_SKIP") == "1", reason="manual skip")


class _Src:
    @staticmethod
    def read():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()


class TestRowExpandAffordance:
    def test_row_template_has_aria_expanded_and_indicator(self):
        """明细行模板：aria-expanded 态属性 + .xind 指示符元素在场。"""
        src = _Src.read()
        assert 'aria-expanded=' in src, "明细行模板缺 aria-expanded 态属性"
        assert 'class="xind"' in src or "class='xind'" in src, \
            "明细行模板缺 .xind 展开指示符"

    def test_togrow_flips_aria_state_both_branches(self):
        """togRow 开/收两支都回写 aria 态（收支共用 _ariaOff 单源，开支直设 true）。"""
        src = _Src.read()
        i0 = src.index("function togRow")
        seg = src[i0:i0 + 900]
        assert "_ariaOff()" in seg, "togRow 缺 _ariaOff 回写（收支单源）"
        assert "setAttribute('aria-expanded','true')" in seg, \
            "togRow 开支缺 aria-expanded=true 直设"

    def test_indicator_css_rotates_when_open(self):
        """CSS：▸ 指示符在场，展开态 rotate(90deg)（与 .pill::after 同语言）。"""
        src = _Src.read()
        assert ".xind::before" in src, "缺 .xind::before 指示符规则"
        assert "aria-expanded" in src.split(".xind::before", 1)[1], \
            "缺展开态旋转规则（aria-expanded 选择器须在 .xind::before 之后）"
        assert "rotate(90deg)" in src, "缺 rotate(90deg) 展开态"

    def test_restore_honours_expanded_state(self):
        """重渲染按 EXP 回填 aria-expanded 初始态（恢复路径与交互路径同源）。"""
        src = _Src.read()
        marker = 'aria-expanded="${EXP'
        assert marker in src, "aria-expanded 初始值未按 EXP 态回填（模板插值缺失）"

    def test_aria_off_single_source_all_writers(self):
        """aria 回写走 _ariaOff 单源；EXP 清零的旁路（tgGo 互斥/Esc）必须同收。
        静态初始值是假单源：共享态每个入口都要显式回写（LESSONS 二十§1）。"""
        src = _Src.read()
        assert "function _ariaOff" in src, "缺 _ariaOff 单源 helper"
        body = src[src.index("function _ariaOff"):]
        body = body[:body.index("function ", 10)] if "function " in body[10:] else body
        n_q = body.count('aria-expanded="true"')
        # r257 P3-3 起查询点=2（tr 数据行家族 + .tg 改期胶囊家族，
        # 互斥收口两族都收敛本单源；新增家族须同轮 +1 并改本钉）
        assert n_q == 2, f"_ariaOff 体内查询点 {n_q}!=2"
        # 消费点受控枚举:togRow 收支+开前、tgGo 互斥、Esc 收比价+收改期
        # （r257 P3-3 起 Esc 双分支；写点新增须同轮 +1 并改本钉）
        # 「_ariaOff();」调用形态,定义签名 _ariaOff(){ 不含 ); 精确排除
        n_call = src.count("_ariaOff();")
        assert n_call == 5, \
            f"_ariaOff 调用点 {n_call}!=5（togRow×2+tgGo×1+Esc×2）"
