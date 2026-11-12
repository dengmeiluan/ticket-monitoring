# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r286_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import pytest
import re
import sys


# ---- merged from tests/test_r286_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r285_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---------- P2-1: 1440 带 KPI 空腔（源码钉 + 病灶带行为钉） ----------

def test_kpi_widen_1440_source_pin():
    """源码钉：1280 解锁块承载 grid/kpisum 放宽处方（与 wrap 托底
    释放同拍，晚于 660 块 --kpiw 限宽声明，同特异性后者胜）；≥1920
    块互指注记在场（同值 no-op 保留先例，与 statline 形态同构）。"""
    src = _page_src()
    m = re.search(
        r"@media\(min-width:1280px\)\{\.statline,#pulseLegend,\.pulsewrap"
        r"\{max-width:min\(1440px,100%\)\}\s*\.grid,\.kpisum"
        r"\{max-width:min\(1440px,100%\)\}\}",
        src)
    assert m, "1280 解锁块内 grid/kpisum 放宽处方缺席（r302 W1 四族同上限）"
    i_660 = src.find(".grid{grid-template-columns:repeat(2,minmax(0,1fr))")
    assert 0 < i_660 < m.start(), \
        "放宽处方必须晚于 660 块 --kpiw 限宽声明（层叠序）"
    # 禁复活：1440 独占带形态=解锁与 wrap 渐进脱拍（带界空腔回潮）
    assert "min-width:1440px" not in src, \
        "1440 独占带复活（解锁断点须与 wrap 渐进带 1280 同拍）"
    # ≥1920 块互指注记（同值 no-op 保留，防单侧删改回插再限宽）
    assert re.search(
        r"min-width:1920px[\s\S]{0,900}?\.grid,\.kpisum"
        r"\{max-width:min\(1440px,100%\)\}", src), \
        "≥1920 块原声明退役（应转互指保留形态）"




# ---------- P2-2: 空态行 nowrap 裁切（源码钉 + 390 行为钉） ----------

def test_erow_nowrap_source_pin():
    """源码钉：.erow td 基础规则带 white-space:normal（与 .xrow td
    同族同位——th,td nowrap 基础规则特异度 (0,0,2) 低于 (0,1,1)，
    基础规则处补词即胜，无需置尾）。"""
    src = _page_src()
    m = re.search(r"\.erow td\{[^}]*\}", src)
    assert m, ".erow td 基础规则缺席"
    assert "white-space:normal" in m.group(0), \
        ".erow td 未补 white-space:normal（空态句仍被裁）"




# ---------- P2-3: 健康格触屏扩带 ≤900（源码钉 + 768 行为钉） ----------

def test_hc_coarse_band_extended_source_pin():
    """源码钉：W1 块媒体门扩带 ≤900（iPad 竖屏 768/810/820 真空带
    入覆写域）；覆写块位置晚于窄带 5px 基础声明（≤760 带层叠行为
    零变化：同特异性置尾胜）。"""
    src = _page_src()
    # r339d D5 起块内合法增厚（.rthead 36 地板同块）——匹配放宽到
    # 「块头到 .hc 声明」（窗口钉对插入敏感，LESSONS 卅一§3 同律），
    # 语义担保不变：扩带门 + .hc 9px 覆写声明在块内
    m = re.search(
        r"@media\(pointer:coarse\) and \(max-width:900px\)\{"
        r"[^@]*?\.hc\{width:9px;flex:none\}", src)
    assert m, "W1 块未扩带 ≤900（或块内声明形态漂移）"
    i_base = src.find(".hc{width:5px}")
    assert 0 < i_base < m.start(), "覆写块必须晚于窄带 5px 基础声明"


