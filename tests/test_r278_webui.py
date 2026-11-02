# -*- coding: utf-8 -*-
"""r278 WebUI 精细化：KPI 卡跨日期组等高（3px 节奏差收口）。

r278 WebUI 审计 P3-1：航班信息行 .muted.fb 含徽章（bagtag/stoptag，
inline-block 行高 19px）时比纯文本行（16px）高 3px——跨日期组 KPI
卡 131 vs 128 节奏差。.fb 统一 min-height:19px 归一（一行 CSS）。
"""


def test_kpi_fb_minheight_uniform():
    src = open("webui.py", encoding="utf-8").read()
    assert (".kpi .fb{color:var(--tx2);font-size:12px;"
            "margin-top:2px;min-height:19px}") in src.replace("\n", ""), \
        "KPI 卡 .fb 行未挂 min-height:19px（跨日期组 3px 节奏差）"
