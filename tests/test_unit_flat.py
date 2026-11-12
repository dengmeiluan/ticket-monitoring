# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r359_flat_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import re


# ---- merged from tests/test_r359_flat_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def test_date_fields_are_content_sized_and_click_anywhere():
    for needle in (
        ".dpanel-row{grid-template-columns:168px auto 168px auto;justify-content:start}",
        ".dpanel-row.single{grid-template-columns:168px auto;justify-content:start}",
        ".dpanel-row input[type=date]{width:168px;max-width:100%;cursor:pointer}",
        ".dcompose{background:transparent;border:0;padding:0;gap:8px}",
        ".dctabs{background:color-mix(in srgb,var(--line) 7%,var(--card));border-color:transparent}",
    ):
        assert needle in STYLE, needle
    assert SRC.count('onclick="try{this.showPicker()}catch(e){}"') == 3
    assert "点字段唤起日历" in SRC


def test_departure_and_arrival_columns_line_up():
    assert "#searchview .srx-times{grid-template-columns:44px 8px 44px 15px;column-gap:3px}" in STYLE
    assert "#searchview .srx-times .arr{text-align:left}" in STYLE
    assert "#searchview .srx-times .xday{justify-self:start}" in STYLE


def test_flat_surfaces_and_segmented_chart_controls():
    for needle in (
        "#monview .ucard,#montab-watch .ws-card,#searchview .srx-list,#searchview .srx-mirror,#cfgview .ucard,#healthcard{border-color:transparent;box-shadow:none}",
        "#cfgview .rline{border-color:transparent;background:color-mix",
        "#cfgview .ractions{border-color:transparent;background:color-mix",
        ".ws-ranges{border-color:transparent;background:color-mix",
        ".ws-ranges button{border-right:0;border-radius:var(--r3);height:26px}",
    ):
        assert needle in STYLE, needle


def test_chart_subtitle_hides_zero_aggregation_and_says_coverage():
    assert "覆盖 '+_sp+' · '+_rawN+' 个采集点'+(_aggN?' · '+_aggN+' 个日聚合':'')" in SRC
    assert "实际覆盖" not in SRC
