# -*- coding: utf-8 -*-
"""r241 WebUI 落地（审计 _scratch/r241_audit_webui.md）。

P2-1 NOTIFY 落地页 @手机高亮令牌双谱（与主站 --at 族/:673 规则同构）；
P2-2 541-760 带明细筛选条吸顶对（≤540 同构：深滚后筛选/排序入口
随时可达）+ 锚点补偿过「吸顶三件」（--tabsh 动态单源，--hdh 同律；
390 实测 ≤540 同族落点遮挡一并收口）。
P3-1/2/3 为零行为注释互指收口，不设钉。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r241_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


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
