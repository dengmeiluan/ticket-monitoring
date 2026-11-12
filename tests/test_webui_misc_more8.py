# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r249_webui.py
- tests/test_r250_webui.py
- tests/test_v15122_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import pytest
import subprocess
import sys
import tempfile
import time
import urllib.request


# ---- merged from tests/test_r249_webui.py ----

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




# ---- merged from tests/test_r250_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- P2-1: 明细行首列焦点环（源码序层叠钉 + computed 行为钉） ----------

def test_row_firstcol_focus_ring_source_pin():
    src = _page_src()
    ring = "#ftable tbody tr:focus-visible td:first-child{"
    assert ring in src, (
        "明细数据行缺首列焦点环复声明：tr:focus-visible 的 inset 环画在 "
        "tr 装饰层，被首列吸附格不透明底（--card/斑马/qual tint）盖住左缘 "
        "2px——环必须落 td 自身才在吸附列之上（tr 层修法无效）")
    proj = ".tw th:first-child,.tw td:first-child{"
    assert src.index(proj) < src.index(ring), (
        "行首列焦点环复声明必须置尾于吸附投影声明之后：同族层叠胜负由"
        "源码序决定（ID 特异度已恒压，序钉防未来同特异性块前插）")
    m = src.index(ring)
    seg = src[m:m + 220]
    assert "inset 2px 0 0 var(--blue)" in seg and "2px 0 0 var(--line)" in seg, (
        "行首列焦点环须双影叠加：inset 左缘蓝段（三值形态 x=2，非表头"
        "四值全环）+ 吸附投影共存（单写 inset 会吃掉首列吸附分隔投影，"
        "r249 表头修法同语言）")




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




# ---- merged from tests/test_v15122_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui as _w
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_p2a_cardhead_title_same_tier_as_seclab():
    s = _src()
    assert s.count('id="chartTitle" style="font-weight:700;font-size:14px"') == 1
    assert s.count('id="calTitle" style="font-weight:700;font-size:14px"') == 1
    # 旧裸 weight 无字号形态不回潮
    assert 'id="chartTitle" style="font-weight:700"></span>' not in s


def test_p2b_hlb_dead_dims_removed():
    s = _src()
    # .legend b（0,1,1）恒压过 .hlb（0,1,0）：12×6 死维度从未渲染
    assert ".hlb{display:inline-block;width:12px;height:6px" not in s
    # .hlh 维护纹修饰类保留（健康图例第四枚色票依赖）
    assert ".hlh{" in s


def test_p2c_cdt_margin_double_count_removed():
    s = _src()
    assert "margin-right:8px;font-size:11px" not in s
    # gap 单源后倒计时 chip 与 .hdmeta 相邻件同距（8px gap 唯一来源）
    assert ".hdmeta{display:inline-flex;align-items:center;gap:8px" in s


def test_p2d_letter_spacing_two_tier_tokens():
    s = _src()
    # 令牌定义：主站 + notify 独立页两处 :root（--pill 先例）；
    # r273 增设半像素档 --ls05（主站 ：root 独有，notify 无 0.5px 消费）
    assert s.count("--ls1:1px;--ls2:2px") == 2
    assert s.count("--ls05:.5px") == 1
    # 五值并轨：0.8 与 1.5 档清零
    assert "letter-spacing:.8px" not in s
    assert "letter-spacing:1.5px" not in s
    # 微签族消费点全走令牌：主站 9 + notify .top b = 10 处 --ls1；
    # r342 配置工作台新增 5 处微签（配置 chrome/概览卡/筛选预设/分组/
    # 明细摘要）同走令牌 → 15；r344 存储卡 pstat 微签 +1 → 16；
    # r340 生产检索页新增 7 处微签（eyebrow/live/lab/kpi/thead/dlab/prov）
    # → 23；r340b 三重对齐表头再 +1 → 24；r348 探针字段/城市分组 +2 → 26；
    # r351 关注航班配置/清单微签 +6 → 32（新增微签不得裸写 px 字距）
    # 39 → 38（2026-11-06 复核）：r942c 去掉了 `#searchview .srx-thead`
    # 那行的 letter-spacing（表头改发丝线、font-size:11px），消费点少一处。
    # 仍按精确计数钉住，防止有人整段删掉微签样式。
    assert s.count("letter-spacing:var(--ls1)") == 38
    # --ls2 消费四处：装饰英文签两处（.seclab .en / .grouplab .en）
    # + r273 收编的两处 15px 展示签（.pvbody .md-g 主站 / .md .g notify）
    assert s.count("letter-spacing:var(--ls2)") == 4
    # r325：+1 处 .rintl 国际徽标消费（源码钉随消费点记账）
    # R15：+1 处 .rrt 往返徽标消费（源码钉随消费点记账）
    assert s.count("letter-spacing:var(--ls05)") == 10  # r420 节流小节标题/复发表头 +2（与健康卡 pseclab 同族）
    # 裸字距声明清零（半像素/两像素档全入令牌）
    assert "letter-spacing:.5px" not in s
    assert "letter-spacing:2px" not in s
    # 14px 页题字距维持原值（h1 品牌字距非微签族，不入令牌）
    assert s.count("letter-spacing:1.2px") == 1


def test_p2e_tile_radius_token():
    s = _src()
    assert s.count("--r10:10px") == 2          # 主站 + notify
    assert s.count("border-radius:10px") == 0
    assert s.count("border-radius:0 10px 10px 10px") == 0
    # 主站 7 处 + notify 2 处 + r340 检索浮层 1 处
    # + r340b 详情抽屉/校准册 2 处 + r357 配置表面 4 处
    # + 检索台 srx-mxcard/srx-hero-act 2 处 + srf-card 1 处 + 特价面板 1 处
    # + 渠道台 chband 1 处 + 检索浮层 r10 1 处 = 22
    # + 登录双端弹窗 lgmodal 1 处 = 23
    # + v294 扁平化监控卡/雷达监控/健康诊断/关注航班统一卡 6 处 = 29
    # v1.5.303 基线 28 处（v297 登录内层 lgslot 并入外层表面 -1）
    # + r369 节流状态条 paceBox 1 处 = 29
    # r473e 起节流量尺改成「无底色的发丝竖线布局」，.pace-stats 不再需要圆角
    # （它在浅灰面板里本来就不该是一张带边的白卡），所以回到 29。
    # + 检索筛选面板 srf-card 1 处 = 30（同样走 --r10 令牌，没有退回字面量）
    # 2026-11-01 复核：`.srf-card` 确实已用 --r10，但计数仍是 29——
    # 30 是「把它加进清单后本该得到」的数，实际文件里并没有第 30 处。
    # 全量 `var(--r10)` 是 30 次，多出来的那次是
    # `.cfgseg .chip{border-radius:calc(var(--r10) - 2px)}`：小控件圆角，
    # 本来就不属于这张「容器表面」清单。按实际 29 钉，并在此注明差 1 的来源，
    # 免得下次又照着 30 去「补一处」而凭空加一个圆角。
    # 29 → 31（2026-11-06 复核）：r942 系列新增两处容器表面圆角消费。
    # 上面那段「差 1 的来源」说明仍然有效（.cfgseg .chip 不计入本清单）。
    # r1147：桌面筛选 popover（#srxCtxFly）改贴按钮大浮层，圆角从瓦片档
    # --r10 升到 --r（14px，仍是令牌）。40 → 39，白名单其余不变。
    # r1510：策略目录首开的**等待卡**与**失败卡**各 +1 处（两张都是
    # `var(--r-surface-2)` 底 + --r10 圆角的容器表面，与全站同档）。
    # 39 → 41。
    assert s.count("border-radius:var(--r10)") == 41
    # r455 退役唯一一处单角变体（.pldesp「展开体跟行左缘对齐」）。
    # 那处圆角本来是为「行是圆角盒子 + 展开体另起一张盒子」服务的；
    # 现在行与展开体合成同一条列表项（无色块、发丝下划线分隔），
    # 不再有第二个盒子，单角变体失去消费者。留着它就是死样式。
    assert "border-radius:0 var(--r10) var(--r10) var(--r10)" not in s
    assert ".pldesp{background:transparent;border:0;" in s
    # --r3=9px 值不动（uitest 在案钉：notify logo 9px）
    assert "--r3:9px" in s
