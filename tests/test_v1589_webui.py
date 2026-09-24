# -*- coding: utf-8 -*-
"""webui 打磨钉（WebUI 审计 P2 收口）：亮/暗对比度 AA 公式化断言、
触控热区、switchView 回程补拍、日历死通道收口、pill 三态 title 单源、
resetFlt 注释如实、KPI 飞猪税前标。

对比度断言按 WCAG 相对亮度公式在测试内计算（源码提取色值），
不信注释自述；源码钉模式锚关键形态。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1589_webui.py -q
"""
import os
import re
import sys

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
    assert "Math.min(0.40,(r-1)*2.2)" in p, "暗色日历 alpha 上限未收 0.56"


# ---- P2-3 触控热区 ----

def test_touch_targets_hotzone():
    p = _page()
    assert ".pvx::after,a.vw::after{content:'';position:absolute;inset:-9px -8px}" in p, \
        "a.vw 纵向热区未补到触控基准"
    assert ".demoBar a{color:#9a6200;font-weight:700;padding:5px 0}" in p


# ---- P2-4/P2-5 switchView 回程补拍 ----

def test_switchview_mon_return_repaints():
    p = _page()
    m = re.search(r"if\(v==='mon'&&_from==='cfg'\)\{(.{0,400}?)\}",
                  p, re.S)
    assert m, "switchView 缺 cfg→mon 回程补拍块"
    blk = m.group(1)
    assert "if(MONTAB==='trend')chart();" in blk, "回程未补走势重绘"
    assert "xhint" in blk and "scrollWidth" in blk, "回程未补健康线重判"


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
    assert "brief.plat==='fliggy'?'<span class=\"pretax\"" in p, \
        "KPI 卡飞猪价缺税前标注"
    assert "FLIGGY_TAX_PAD>0 时 qual/推送用含税 eff 价" in p, \
        "pad 同步律注释缺失"
