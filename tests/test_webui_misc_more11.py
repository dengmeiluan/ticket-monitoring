# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r281_webui.py
- tests/test_v15278_ui.py

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


# ---- merged from tests/test_r281_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


SWEEP = ("#cfgview .cfpanel>.ucard,#cfgview #cfgform>.ucard,"
         "#cfgview #cfgform>.ucard>div")


# ---------- 源码钉 ----------

def test_cfgsearch_orphan_container_source_pin():
    src = _page_src()
    # 收尾扫与复位清单各一份（漏复位清单=清空后容器壳滞留 display:none）
    n = src.count(SWEEP)
    assert n == 2, (
        "容器族选择器须两处在场（cfgFilter 收尾扫 + cfgSearchClear 复位"
        "清单），count=%d" % n)
    # 收尾扫必须在孤儿头扫写入点之后（容器可见性判定消费头级 inline
    # 结果，顺序颠倒=按上一轮头状态判容器，假隐/假显）
    anchor = src.index("g.style.display=keep?'':'none';});")
    sweep_in_filter = src.find(SWEEP, anchor)
    assert sweep_in_filter > 0, (
        "cfgFilter 内缺容器收尾扫（孤儿头扫之后无容器族选择器）")
    # 复位清单（第一处）在收尾扫之前属正常（cfgSearchClear 定义在前）；
    # 额外验证收尾扫带「无内容行不参与」守卫（rows.length 空卡防误杀）
    body = src[sweep_in_filter:sweep_in_filter + 700]
    assert "rows.length" in body, (
        "容器收尾扫缺无内容行守卫（空态引导卡等无 ROWS 结构的卡"
        "会被误隐）")
    # Soldier Minor-1：renderHealth 空态分支必须清推送连败源
    # （账本空窗后 _ovPushStreak 残留=红帽常亮而指引落空）
    hs = src.index("function renderHealth(j){")
    empty_ret = src.index("暂无扫描记录", hs)
    seg = src[empty_ret:empty_ret + 400]
    assert "renderPushChannels({channels:{}})" in seg, (
        "renderHealth 空态分支缺推送源清零（红帽 stale 残留）")
    # Soldier Minor-2：cfgSearchClear 必须按 aria-expanded 重写手风琴
    ci = src.index("function cfgSearchClear()")
    cseg = src[ci:ci + 1400]
    assert "aria-expanded" in cseg, (
        "cfgSearchClear 缺手风琴态重写（容器族复位强制展开折叠卡，"
        "aria/视觉状态分裂）")


# ---------- 行为钉 ----------







# ---------- srv fixture（自包含，形态同 test_r279_webui.py） ----------

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




# ---- merged from tests/test_v15278_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_mirror_rows_carry_date_in_all_date_mode():
    s = _src()
    fn = s[s.index("function srxMirrorListHTML(ch,rows){"):s.index("function srxMirrorDetailHTML")]
    assert "!SRX.date&&f.date?' · '+he(f.date.slice(5)):''" in fn


def test_csv_and_json_label_only_observe_and_calendar_stale():
    s = _src()
    fn = s[s.index("async function srxExport(){"):s.index("async function srxExportEvidence()")]
    assert "'实时 · 仅观察'" in fn
    assert "'日历/薄行'+(srxIsStale(f)?' · 补位 '+f.stale+'h':''" in fn
    assert "f.fetchedAt||(srxIsStale(f)?'补位 '+f.stale+'h':'')" in fn
    ev = s[s.index("async function srxExportEvidence(){"):s.index("function srxPayload()")]
    assert "staleH:srxIsStale(f)?Number(f.stale||0):0" in ev
    assert "onlyObserve:!Number(f.th)&&!f.probe" in ev


def test_health_maintenance_never_green_100():
    s = _src()
    assert "const maintN=st.maint||0;" in s
    assert "maintN?(shownRate>=80?'mid':'bad')" in s
    assert ")+(maintN?' · 维护':'')" in s


def test_demo_probe_mode_and_matrix_orphan_close():
    s = _src()
    assert "const pm=$('srxProbeMode');if(pm)pm.textContent=SRX.probe?" in s
    assert "(demo?'DEMO · 合成':'监控数据')" in s
    fn = s[s.index("function srxRenderRows(){"):s.index("function srxMatrixHTML()")]
    assert "if(SRX.sel&&!rows.some(f=>srxKey(f)===SRX.sel))" in fn
    assert "srxUnlockBody()" in fn


def test_studio_actions_restore_focus():
    s = _src()
    assert "document.querySelector('[data-wstoggle=\"'+w.id+'\"]')" in s
    assert "document.querySelector('[data-wsnotify=\"'+w.id+'\"]')" in s
    assert "document.querySelector('[data-wsact=\"add\"]')" in s


def test_city_region_order_and_config_regions():
    s = _src()
    assert "const RO={'国内':0,'日韩':1,'东南亚':2" in s
    assert "return (ro(a)-ro(b))||sc(a)-sc(b)" in s
    assert "'日韩':2,'东南亚':2,'南亚':2,'中东':2,'亚洲':2" in s


def test_calendar_row_key_includes_price_to_avoid_collision():
    import webui
    a = {"isCal": True, "from": "SHA", "to": "SIN", "platKey": "ctrip",
         "date": "2026-11-16", "rawIdx": None, "price": 717}
    b = dict(a, price=818)
    assert webui._srx_row_key(a) != webui._srx_row_key(b)
    assert webui._srx_row_key(a).startswith("c|SHA|SIN|ctrip|2026-11-16|")


def test_trusted_icons_are_direct_img_bic():
    src = _src()
    assert "<img class=\"'+c+'\" data-plat=\"" in src
    assert "<img class=\"bic bic-air '+(cls||'')+'\" data-code=\"" in src


def test_css_no_clipping_and_short_desktop_note():
    s = _src()
    assert ".cwf-cand .mt{grid-area:meta;font-size:10px;color:var(--mut);white-space:normal" in s
    # r374 字号收口：9px 低于全站最小标注档（10px），价带说明提到 10px
    assert "#searchview .srx-band-note{font-size:10px;margin-top:4px}" in s
    assert "#searchview .srx-band-note a{display:none}" in s
    assert "word-break:keep-all;overflow-wrap:normal" in s
    assert "#searchview .srx-dtabs{flex-wrap:wrap!important;overflow-x:visible!important;row-gap:3px}" in s
    assert ".mdgrp{display:flex;flex-wrap:wrap;white-space:normal}" in s
