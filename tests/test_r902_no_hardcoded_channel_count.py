# -*- coding: utf-8 -*-
"""r902 门禁：用户可见文案不得写死渠道数量。

实测缺陷（2026-10-31）：接入两个 App 渠道后共 7 家，但页面上仍有多处
「五渠道 / 五平台」——用户读到「查五渠道明细」「正在发起五渠道采集」
「五渠道均未返回行」，与实际的 7 家对不上，属**谎报规模**。
同一批还有分母写死 5 的读数（7/5 超界）。

判据：只扫**用户看得见的字符串**（PAGE 里的 HTML/JS 字符串字面量），
注释与 docstring 不参与——历史注释里写「五渠道」是记录当时的事实，
不影响界面。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402

PAGE = webui.PAGE


def _strip_comments(src: str) -> str:
    """剥掉 /* */ 与 // 行注释（只处理 JS/CSS 风格，够用）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.split("\n"):
        # 只剥「整行以 // 开头」与「代码后面的 // 注释」，跳过 http://
        if line.strip().startswith("//"):
            continue
        out.append(re.sub(r"(?<![:\w])//.*$", "", line))
    return "\n".join(out)


BODY = _strip_comments(PAGE)


def test_no_hardcoded_channel_count_in_visible_copy():
    bad = []
    # 同类写死还有「四渠道 / 四平台」——接入 App 后同样过期。
    # 注意「四源」不在此列：它是一个**视图名**（four 视图把四种来源形态并排），
    # 不是渠道数量，扫进来会造出与渠道数无关的假红。
    for pat in ("五渠道", "五平台", "七个渠道", "七渠道",
                "四渠道", "四平台"):
        for m in re.finditer(re.escape(pat), BODY):
            ctx = BODY[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            bad.append("%s ← ...%s..." % (pat, ctx))
    assert not bad, (
        "界面文案写死了渠道数量（渠道数会随接入变化，应写「所选渠道/全部渠道」"
        "或按实际数量动态拼）：\n" + "\n".join(bad[:6]))


def test_coverage_denominator_is_not_a_literal_five():
    """渠道覆盖类读数：分母不许是字面量 5。"""
    assert "dataPlats+'/5'" not in BODY, "渠道覆盖分母仍写死 5（7 家时会出现 7/5）"
    assert "dataPlats/5*100" not in BODY, "渠道覆盖百分比仍写死分母 5"


def test_probe_result_renders_every_channel_with_data():
    """探针结果按**数据里的渠道集合**渲染，而不是每渠道白名单过滤。"""
    assert "SRX_PLAT_ORDER.filter(p=>(j.channels||{})[p])" not in BODY, (
        "探针结果仍用固定渠道表过滤——App 渠道的产物永远不会显示")
    assert "SRX_PLAT_ORDER.filter(p=>(lg.channels||{})[p])" not in BODY, (
        "组合探针结果仍用固定渠道表过滤，App 渠道结果会被丢掉")
