# -*- coding: utf-8 -*-
"""r979：多态按钮文案统一——<展开|收起> + 同一名词，两态等长。

用户要求「推崇按钮可以多态文案统一设计」。旧实现里「更多筛选条件」只有
展开态前两项缺失动词、收起态又写成「收起筛选条件」，两态字数不同导致
按钮宽度跳动，也被读成两套控件。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


PAIRS = [
    ("展开筛选", "收起筛选"),
    ("展开更多条件", "收起更多条件"),
    ("展开概览", "收起概览"),
    ("展开溯源", "收起溯源"),
    ("展开更多工具", "收起更多工具"),
    ("展开渠道镜像", "收起渠道镜像"),
    ("展开探针", "收起探针"),
    ("展开进度", "收起进度"),
    ("展开说明", "收起说明"),
    ("展开详情", "收起详情"),
]


def test_pairs_share_noun_and_length():
    for a, b in PAIRS:
        assert a[:2] == "展开" and b[:2] == "收起", (a, b)
        assert a[2:] == b[2:], "两态名词不一致：%s / %s" % (a, b)
        assert len(a) == len(b), "两态字数不同会让按钮宽度跳动：%s / %s" % (a, b)


def test_more_conditions_trigger_uses_shared_pair():
    import webui
    src = webui.PAGE
    i = src.index('id="srxMoreBtn"')
    seg = src[i:i + 260]
    assert "展开更多条件" in seg, "更多条件触发器又回到无动词的「更多筛选条件」"
    assert "SRX.more?'收起更多条件':'展开更多条件'" in src, \
        "更多条件开合没有使用统一的两态文案"
    assert "更多筛选条件" not in src, "旧的不对称文案仍在"
    assert "收起高级筛选" not in src and "展开高级筛选" not in src, \
        "aria-label 仍与可见文案不同名"


def test_all_two_state_ternaries_are_symmetric():
    import webui
    src = webui.PAGE
    bad = []
    for a, b in re.findall(r"'收起([^']{0,8})'\s*:\s*'展开([^']{0,8})'", src):
        if a != b:
            bad.append(("收起" + a, "展开" + b))
    for a, b in re.findall(r"'展开([^']{0,8})'\s*:\s*'收起([^']{0,8})'", src):
        if a != b:
            bad.append(("展开" + a, "收起" + b))
    assert not bad, "存在两态名词不一致的按钮：%s" % bad
    # 负控：正则确实抓到了现存的多态文案，不是空集假绿
    total = len(re.findall(r"'收起[^']{0,8}'\s*:\s*'展开[^']{0,8}'", src)) + \
            len(re.findall(r"'展开[^']{0,8}'\s*:\s*'收起[^']{0,8}'", src))
    assert total >= 6, "只抓到 %d 组两态文案，正则可能失效" % total
