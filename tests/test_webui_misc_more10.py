# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r279_webui.py
- tests/test_r362_a11y.py
- tests/test_r536b_note_sits_under_trigger.py
- tests/test_r647_chart_gap_small_sample.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import pytest
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


# ---- merged from tests/test_r279_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- P2-1: .srow iOS 防放大守卫（源码序钉 + computed 行为钉） ----------

def test_srow_ios_zoom_guard_source_pin():
    src = _page_src()
    guard = ".srow .sctl input:not(.switch){font-size:16px}"
    # 实效档：三处触控块（≤900coarse / 901+coarse / ≤760）各一，
    # 与同块 height:38px 行同形高特异（同特异性置尾后者胜）
    n = src.count(guard)
    assert n == 3, (
        ".srow 16px 防放大守须三处触控块同批在场（count=%d，三处清单"
        "互指纪律：漏改任一块=该带 iOS 聚焦仍爆版）" % n)
    # 源码序：守卫声明必须晚于基础规则块（基础 .srow 规则第二行即
    # 13px——同特异性层叠胜负由源码序决定，守卫在前被压制）。
    # 锚用基础规则块头专属子串（首个 font-size:13px 是 .pill 规则，
    # 拿它当锚会把「守卫被挪到基础规则之前」的史病放成假绿）
    base = src.index(".srow .sctl input:not(.switch){height:34px")
    assert "font-size:13px" in src[base:base + 200], (
        "基础 .srow 规则形态漂移：块头 200 字符内无 13px 声明，"
        "源码序锚失效须随形态改写")
    assert src.index(guard) > base, (
        "16px 守卫声明必须置尾于基础 13px 声明之后，否则同特异性"
        "被前者压制（层叠败北复发）")
    # 三处触控块的姊妹高特异行（height:38px）仍各在——守卫与触控
    # 高度同族共生，触控块重构时两者须同步
    assert src.count(".srow .sctl input:not(.switch){height:38px}") == 3




# ---------- P3-1: demo_pulse 渠道族与 _PLATS 单源一致 ----------

def test_demo_pulse_channel_family_matches_health():
    """同一演示页的健康时间线与脉冲图必须是**同一组渠道**。

    预期不再钉 `_PLATS`：那个列表只是价格种子（下标参与价格偏移，
    扩它会改演示价），而「哪些渠道在跑」是另一件事——真实账本每轮
    7 家全在（app_qunar/app_zhixing 各 58/59 条）。2026-11-01 实测
    演示健康卡只画 5 家、两个 App 缺席，访客会以为它们不参与采集。
    单一事实源改成 DEMO_SCAN_PLATS，本钉守的是「两处一致」这个意图。
    """
    from core.demo import DEMO_SCAN_PLATS, demo_health, demo_pulse
    pulse = demo_pulse()
    pulse_plats = set(pulse["rounds"][0]["chans"].keys())
    health_plats = set(demo_health()["stats"].keys())
    expected = set(DEMO_SCAN_PLATS)
    assert pulse_plats == expected, (
        "demo_pulse 渠道族 %s 与 DEMO_SCAN_PLATS %s 不一致（概览脉冲图例"
        "渠道缺漏=同页两处渠道宇宙分裂）" % (sorted(pulse_plats), sorted(expected)))
    assert health_plats == expected, (
        "demo_health 渠道族 %s 与 DEMO_SCAN_PLATS %s 不一致" % (
            sorted(health_plats), sorted(expected)))
    # 两个 App 必须在演示的采集渠道宇宙里
    assert "app_zhixing" in expected and "app_qunar" in expected, (
        "演示采集渠道缺 App，健康卡/脉冲图会漏画它们")
    # 价格种子不应该被顺手扩掉（扩它会改演示价）
    from core.demo import _PLATS
    assert set(_PLATS) == {"qunar", "ctrip", "fliggy", "tongcheng", "tuniu"}, (
        "_PLATS 是价格种子，不该被扩成采集渠道列表")


def test_demo_pulse_dur_is_channel_mean():
    """dur 语义=轮墙钟时长均值（core/pulse.py 同形）：分母随渠道族
    单源（曾硬编码 /3——4 渠时代已 4/3 失真，补 ctrip 后 5/3 放大，
    statline「用时 Xs」与脉冲 tooltip 展示偏大 ~1.67 倍）。"""
    from core.demo import demo_pulse
    for r in demo_pulse()["rounds"]:
        lat = [c["lat"] for c in r["chans"].values()]
        expect = round(sum(lat) / len(lat), 1)
        assert abs(r["dur"] - expect) < 0.06, (
            "rounds[%s] dur=%s ≠ 渠道 lat 均值 %s（分母未随 chans 单源）"
            % (r["ts"], r["dur"], expect))


# ---------- srv fixture（自包含，形态同 test_r249_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.seek(0)
        return "".join(logf.readlines()[-20:])
    except Exception:
        return "<log 不可读>"




# ---- merged from tests/test_r362_a11y.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def test_top_layer_shortcut_guard():
    s = _src()
    i = s.index("document.addEventListener('keydown',e=>{\n /* Ctrl/Cmd+S")
    tail = s[i:i + 900]
    assert "typeof srxTopLayer==='function'&&srxTopLayer()" in tail
    assert tail.index("srxTopLayer()") < tail.index("e.key==='1'")


def test_detail_tabs_scoped_to_tablist():
    s = _src()
    i = s.index("$('srxDetail').addEventListener('keydown'")
    block = s[i:i + 900]
    assert "ev.target.closest('.srx-dtabs [data-dtab]')" in block
    assert "querySelectorAll('.srx-dtabs [data-dtab]')" in block
    assert "querySelector('.srx-dtabs [data-dtab=\"'+key+'\"]')" in block
    # 数据区动作钮仍可点击切到同班对照，只是不再参与键盘 tab 环
    assert "const tab=ev.target.closest('[data-dtab]');if(tab){" in s


def test_matrix_toggle_restores_focus():
    s = _src()
    i = s.index("if(ev.key==='m'||ev.key==='M')")
    block = s[i:i + 500]
    assert "srxToggleView()" in block
    assert "#srxRows .srx-row.sel" in block
    assert "#srxRows .mcell.sel" in block
    assert "$('srxViewBtn')" in block


def test_pulse_mobile_scroll_touch_cells():
    s = _src()
    i = s.index('@media(max-width:560px){\n  .pulsewrap{justify-content:flex-start')
    block = s[i:i + 520]
    assert 'overflow-x:auto' in block
    assert '.pbar{flex:0 0 24px;min-width:24px;max-width:none;align-items:center}' in block
    assert '.pbar .seg,.pbar .cap,.pbar.zero i{width:8px;max-width:8px}' in block
    assert '.pulsewrap .pbar::after{inset:0}' in block
    # 默认滚到最新轮，回看旧轮不被刷新抢位
    j = s.index("const _pw=$('pulsebars');")
    jb = s[j:j + 420]
    assert "_pw.scrollWidth>_pw.clientWidth+1" in jb
    assert "dataset.scrolled" in jb
    assert "_pw.scrollLeft=_pw.scrollWidth" in jb


def test_tg_tj_hit_areas_do_not_overlap():
    s = _src()
    assert '.tg{z-index:2}' in s
    assert '#ftable tbody tr[data-k]>td:nth-child(4) .stl.nw:has(.tj){display:block;margin-top:10px}' in s
    # tj 只向下扩 14px（触控 32px），不再向上压胶囊；tg 下沿热区
    # 与航线行上沿恰好相切（实测视觉间距 9px = tg 下扩 9px）
    assert '.tj::after{inset:0 0 -14px}' in s


def test_mobile_probe_submit_moves_above_channels():
    s = _src()
    i = s.index('grid-template-areas:"from from" "to to" "date go" "plat plat" "exit exit"')
    block = s[i:i + 320]
    assert '.srx-datefield{grid-area:date;max-width:none}' in block
    assert 'min-width:96px' in block
    # 城市字段仍整行：旧 ≤460 单列把提交钮排到渠道片之后（320 首屏不可见）
    assert 'grid-template-areas:"from" "to" "date" "plat" "go" "exit"' not in s


def test_watch_list_preserves_row_focus_on_rebuild():
    s = _src()
    i = s.index('function wsRenderList(){')
    block = s[i:i + 1900]
    assert "closest('#wsList [data-wsfocus]')" in block
    assert "closest('#wsList [data-wsexpand]')" in block
    j = block.index("box.innerHTML=list.map(wsRowHTML).join('');")
    tail = block[j:j + 450]
    assert "data-wsexpand=" in tail and "data-wsfocus=" in tail
    assert "focus({preventScroll:true})" in tail


# ---- merged from tests/test_r536b_note_sits_under_trigger.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _note_rule():
    m = re.search(r"#srccap \.scnote\{([^}]*)\}", _src())
    assert m, "说明的定位规则不见了（r873 起为 #srccap .scnote）"
    return m.group(1).replace(" ", "")


def test_note_margin_covers_all_three_bottom_gaps():
    """说明与按钮之间的空隙只剩卡片自身底部内衬——不许再叠第三层留白。

    r873 方案：`.scnote` 绝对定位，卡片 `padding-bottom = noteh + 16px`
    （16 = 8 上呼吸 + 8 下内衬）。判据：定位规则带 left/right 锚（说明与卡同宽），
    且卡片预留高度写的是「说明高度 + 一个有限常量」而不是固定大值。
    """
    body = _note_rule()
    assert "position:absolute" in body, body
    assert "left:12px" in body and "right:12px" in body, body
    src = _src()
    m = re.search(r"#healthDiag #srccap\.scopen\{([^}]*)\}", src)
    assert m, "卡片没有按说明高度预留底部内衬（r873 的核心机制）"
    rule = m.group(1).replace(" ", "")
    assert "--noteh" in rule and "+16px" in rule, rule


def test_note_keeps_its_own_breathing_room():
    """贴边不等于贴字：文字呼吸由自身承担（行高 1.5），不靠容器留白。"""
    body = _note_rule()
    assert "line-height:1.5" in body, body


def test_note_still_outside_card_head_and_action_row():
    src = _src()
    i = src.index('<span class="scnote" id="scNote">')
    assert src.rindex("</div>", 0, i) < i, "说明被塞回卡头里了"
    acts = src.index('<span class="scacts">')
    assert i > src.index("</span>", acts), "说明又进了 scacts 行"


# ---- merged from tests/test_r647_chart_gap_small_sample.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _gap_code():
    """只取 `const gap=` 那一行代码——注释里会引用旧写法做反例，不能算数。"""
    for line in _gaps_body().splitlines():
        st = line.strip()
        if st.startswith("const gap="):
            return st
    raise AssertionError("gap 判定行不见了")


def _gaps_body():
    src = _src()
    i = src.index("gaps(pts,gapMin){")
    j = src.index("segs.push(cur);return segs;},", i)
    return src[i:j]


def test_small_sample_falls_back_to_gap_min():
    body = _gaps_body()
    assert "iv.length>=3" in body, (
        "间隔样本不足时仍在用中位数判缺口——2 点会把 48h 空缺画成连续线：%s"
        % body[:200])
    assert "gapMin||Infinity" in body, body[:200]


def test_median_rule_kept_for_enough_samples():
    """样本足够时仍用「中位间隔 ×1.8」——不能为了修边界把正常断档改坏。"""
    body = _gaps_body()
    assert "med*1.8" in body, body[:200]


def test_gap_min_only_governs_small_samples():
    """gapMin 只用于**样本不足**时；样本足够时不许它主导判据。

    r647b：原先写 `Math.max(med*1.8, gapMin)`，航线图传 gapMin=分桶粒度
    （48h→144min）时会吃掉中位数判据，把真实 2h 采样的曲线判成逐点断开。
    现在：点数 ≥3 用中位数倍率，否则退回 gapMin。
    """
    code = _gap_code()
    assert "pts.length>=3&&med" in code, code
    assert "med*1.8:(gapMin||Infinity)" in code.replace(" ", ""), code
    assert "Math.max(med*1.8" not in code, "gapMin 又主导了中位数判据"


def test_sample_count_predicate_uses_points_not_intervals():
    """判据必须按**点数**——3 个点只有 2 个间隔，按间隔数判会误落入「样本不足」。

    实测：n3even（3 点、均匀 12h、gapMin=4h）曾被判成 [1,1,1]（整条线消失），
    应为 [3]。
    """
    code = _gap_code()
    assert "iv.length>=3" not in code, (
        "又用「间隔个数≥3」当样本量判据——3 个点只有 2 个间隔会误判")
