# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r368_mobile_layout.py
- tests/test_v295_mobile_fold.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import sys
import webui


# ---- merged from tests/test_r368_mobile_layout.py ----

def test_route_grid_uses_viewport_clamped_min_column():
    src = webui.PAGE
    assert "repeat(auto-fit,minmax(min(360px,100%),1fr))" in src
    assert "repeat(auto-fit,minmax(360px,1fr))" not in src


def test_route_card_can_shrink():
    src = webui.PAGE
    assert ".monroute{min-width:0;" in src


# ---- merged from tests/test_v295_mobile_fold.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_fold_helper_syncs_aria_and_restores_text():
    src = _src()
    assert "function srxSetFold" in src
    assert "setAttribute('aria-controls',id)" in src
    assert "aria-expanded" in src
    assert "(folded?'展开':'收起')" in src


def test_mobile_calendar_and_chart_affordance():
    src = _src()
    for s in ("#searchview .srx-grid:has(.srx-mirror.srx-folded)",
              "#searchview .srx-brief .srx-src{flex:0 0 220px!important}",
              "spMonCalFit", "spMonTable",
              # r374 画布可键盘聚焦，aria-label 补充了键位说明
              "role=\"img\" aria-label=\"特价监控走势",
              'id="spMonChart" tabindex="0"'):
        assert s in src, s
