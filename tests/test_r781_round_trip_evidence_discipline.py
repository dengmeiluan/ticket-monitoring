# -*- coding: utf-8 -*-
"""r781：判「往返取不到」之前，单程正控必须先成立（判据纪律）。

来由（2026-11-01 实测）：飞猪 `cheapestCalendar/pc` 从没被拿国内航线
打过。首次尝试「国内单程出数 / 国内往返返回 None」，看起来像「国内
往返不支持」；但**紧接着复跑连国内单程也被拒**（`cb({"success":false})`
65B 软频控体）。正控不成立时，那条「不支持」结论是假的。

同一天还踩了另一头：去哪儿国际带/不带 `backDate` **同时** 170001
超时，单程国际也落 login——同样是「测不出」，不是「不支持」。

这条门禁守的是**结论的形态**：一个渠道的往返能力若被记为 n，必须能
在同一份文档里找到「单程可用」的正面证据或明确的请求层拒绝（如
携程「返程日被前端丢弃」、同程「裸打恒 444」）；只写了「空/失败」
的不算。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "INTL_DESIGN.md")

# 能证明「这条 n 是结论而非故障」的证据词
POSITIVE = ("单程出数", "单程能正常出数", "单程正常", "仪器有效",
            "前端直接丢弃", "恒 444", "只有去程", "无航线",
            "请求体确为双段", "单程正控")
# 明确「测不出」的自述（允许写 n 但必须标注不可判定）
UNDECIDED = ("测不出", "不可判定", "无法判定", "通路本身不可用",
             "正控不成立")


def _doc():
    return io.open(DOC, encoding="utf-8").read()


def test_round_trip_n_rows_state_their_evidence():
    """判 n 的行要能说清「为什么是 n」；判通的不用。

    只挑**否定结论**的行：出现「不支持 / 取不到 / 暂不支持 / 仍 unsupported」
    而**没有**「实测接通 / 支持（」这类正面字样的行。
    """
    txt = _doc()
    rows = [ln for ln in txt.splitlines()
            if ln.startswith("|") and "往返" in ln]
    assert rows, "参数表里找不到任何往返相关行"
    NEGATIVE = ("不支持", "取不到", "暂不支持", "仍 unsupported", "仍为不支持")
    SUPPORTED = ("实测接通", "真报文")
    bad = []
    for ln in rows:
        if not any(w in ln for w in NEGATIVE):
            continue
        if any(w in ln for w in SUPPORTED):
            continue          # 判通的行不在此列
        if any(w in ln for w in POSITIVE) or any(w in ln for w in UNDECIDED):
            continue
        bad.append(ln[:110])
    assert not bad, (
        "这些行判了往返不行，却没给证据（单程可用/请求层拒绝）也没标"
        "「测不出」：%s" % bad)


def test_soft_reject_signature_is_named_as_soft_reject():
    """飞猪那条必须写明「软频控」，否则下次又被读成能力缺失。"""
    txt = _doc()
    assert "软频控" in txt or "success\":false" in txt, (
        "没把飞猪的 65B success:false 体标成软频控——会被误读成不支持")


def test_no_bare_unsupported_without_positive_control():
    """反向守：文档里出现「测不出」时，必须同时出现「正控」这个词。

    避免「测不出」被当成一个可以随手打的标签——它是有前提的：
    必须先试过单程。
    """
    txt = _doc()
    if "测不出" in txt:
        assert "正控" in txt, (
            "写了「测不出」却没提「正控」——判据纪律不完整，"
            "读者不知道测不出的前提是单程也失败")
