# -*- coding: utf-8 -*-
"""r741：浏览器渠道的 round_trip 声明必须有「返程证据」代码支撑。

来由（r740 实测）：同程在矩阵里写着 `round_trip = y`，唯一依据是
「报文里有 TT=RT/AD 这个参数」——但这并不能证明取到过往返价。实测
裸打恒 444「非法链接」，窗历只有单程，一行返程数据都没拿到。假声明
会让「哪些渠道没有往返」的提示少报一家，用户以为能查、跑起来是空的。

判据（每条都可独立证伪）：
  * 声明 y 的浏览器渠道，源码里必须存在**行级返程校验**——即要求返回
    行携带回程字段并与请求回程日比对（飞猪的 `backDate != ret_date`）；
  * 只是"把 ret_date 塞进 URL 参数"不算证据；
  * 声明 n 的渠道，必须真的有 unsupported 分支（防止只改声明不改行为）。
"""
import io
import os

import pytest

from core.channels import BROWSER_CHANNELS, dim_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 返回行级的返程证据字段：必须出现在「比对」的上下文里，并非请求参数
EVIDENCE_FIELDS = ("backDate", "retDate", "retFlightNo", "returnDate",
                   "backFlightNo")


def _src(plat: str) -> str:
    return io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                   encoding="utf-8", newline="").read()


@pytest.mark.parametrize("plat", BROWSER_CHANNELS)
def test_round_trip_y_requires_row_level_return_evidence(plat):
    """记 y 就必须有「拿返回行的回程字段跟请求比对」的代码。

    注意区分两种出现：把 `backDate` 写进**我们自己的输出**（行级标记）
    不算证据——证据是「读渠道返回的同名字段并比对」。这里用
    `.get("backDate")` / `["backDate"]` 这种「读」的形态判定。
    """
    if dim_state(plat, "round_trip") != "y":
        pytest.skip("%s 声明不是 y" % plat)
    src = _src(plat)
    reads = [f for f in EVIDENCE_FIELDS
             if ('.get("%s")' % f in src or "['%s']" % f in src
                 or '["%s"]' % f in src)]
    if not reads:
        pytest.skip("%s 不读返回行回程字段，走价差不变式那条判据" % plat)
    # 出现字段名还不够：必须真的在比对。取字段所在行的上下文判断。
    lines = src.splitlines()
    compared = False
    for i, ln in enumerate(lines):
        if any(('.get("%s")' % f in ln or "['%s']" % f in ln
                or '["%s"]' % f in ln) for f in EVIDENCE_FIELDS):
            window = "\n".join(lines[i:i + 6])
            if ("!=" in window or "==" in window) and "return None" in window:
                compared = True
                break
            if "!= ret_date" in window or "== ret_date" in window:
                compared = True
                break
    assert compared, (
        "%s 读了返回行的回程字段，但没有「与请求回程日/往返对」的比对分支"
        "——把渠道返回的任意行都当往返，仍是冒认" % plat)


# 有些渠道**不回显返程字段**（途牛 listFlight 的响应里没有任何 back/ret
# 字段），此时唯一能证明「这是往返总价」的是**价差不变式**：两段请求的
# 价格 = 单段价格 + 返程日反向最低价。这类渠道只要源码里留下了该判据
# 的实测记录（否则下一个人无法复核），也算达标——但必须同时有
# 「两段请求」的真实构造，不能只是嘴上说。
PRICE_IDENTITY_MARKERS = ("L_ret", "B = A +", "B−A", "B-A")


@pytest.mark.parametrize("plat", BROWSER_CHANNELS)
def test_round_trip_y_without_row_evidence_needs_price_identity(plat):
    """不靠行级字段的渠道，必须留下价差不变式的实测判据 + 两段构造。"""
    if dim_state(plat, "round_trip") != "y":
        pytest.skip("%s 声明不是 y" % plat)
    src = _src(plat)
    if any(f in src for f in EVIDENCE_FIELDS):
        pytest.skip("%s 有返回行字段可比对，走上面那条判据" % plat)
    assert any(m in src for m in PRICE_IDENTITY_MARKERS), (
        "%s 声明 y，既没有返回行回程字段，也没有价差不变式（%s）的实测记录"
        "——无法复核的口径不能叫证据" % (plat, "/".join(PRICE_IDENTITY_MARKERS)))
    assert "segmentList" in src and "back_date" in src, (
        "%s 没有真正构造两段请求，价差不变式也就无从成立" % plat)


@pytest.mark.parametrize("plat", BROWSER_CHANNELS)
def test_round_trip_n_has_explicit_unsupported_branch(plat):
    """记 n 就必须有不支持分支，否则声明与行为打架。"""
    if dim_state(plat, "round_trip") != "n":
        pytest.skip("%s 声明不是 n" % plat)
    src = _src(plat)
    assert ("unsupported" in src and "ret_date" in src), (
        "%s 声明 round_trip=n，源码里却没有 ret_date 的 unsupported 分支"
        % plat)


def test_fliggy_still_goes_through_the_strict_row_compare():
    """钉子：飞猪必须**读返回行 backDate 并比对**，不能被 skip 放过。

    r769 为途牛放宽了入口（它没有回程字段），但飞猪有——如果哪天飞猪的
    比对被删，这条要红，而不是静默退化成「靠价差」。
    """
    src = _src("fliggy")
    assert '.get("backDate")' in src, "飞猪不再读返回行 backDate"
    assert "bk != ret_date" in src or "!= ret_date" in src,         "飞猪不再比对回程日：其他回程日的行会被误认"


def test_tongcheng_domestic_round_trip_declared_after_api():
    """r815h 国内 book1/roundtrips；r926 国际 book1 RT 页 ts/list。

    国内：`book1/roundtrips` 的 atp 是组合总价（210/210）。
    国际：登录档案下 book1 RT 页的 `miflightapi/ts/list`，每条 res 的
    `tp` 是含税总价、`lng` 带去/返两段（2026-11-03 SHA→HKG 41 条 ¥1463）。
    矩阵 y 覆盖国内/国际，只采渠道总价，不做两段单程相加。
    """
    assert dim_state("tongcheng", "round_trip") == "y"
    src = _src("tongcheng")
    assert "book1/roundtrips" in src and "_parse_rt_fps" in src, (
        "声明国内往返 y，但代码里没有 roundtrips 接口/解析器")
    assert "_fetch_intl_rt" in src and "miflightapi/ts/list" in src, (
        "国际往返 y，但代码里没有 book1 RT 页/ts/list 通路")
    assert 'e.get("tp")' in src and 'e.get("lng")' in src, (
        "国际往返没有读 tp/lng（含税总价 + 去/返两段）")


DOCS_MAKING_CHANNEL_CLAIMS = ("docs/INTL_DESIGN.md", "docs/APP_CHANNELS.md",
                              "docs/HANDOFF_CAPABILITY_MATRIX.md")


@pytest.mark.parametrize("doc", DOCS_MAKING_CHANNEL_CLAIMS)
def test_docs_do_not_claim_tongcheng_supports_round_trip(doc):
    """文档不能把同程写成「支持往返」——代码已经取不到，用户会照着去查。

    只禁「同一行里既有同程又有『支持』且没有否定词」这种表述；
    「同程不支持」「同程……取不到」这类如实记录必须放行。
    """
    path = os.path.join(ROOT, doc)
    if not os.path.isfile(path):
        pytest.skip("%s 不在本工作树" % doc)
    src = io.open(path, encoding="utf-8").read()
    bad = []
    for line in src.splitlines():
        if "同程" not in line or "支持" not in line:
            continue
        if any(neg in line for neg in ("不支持", "取不到", "改判", "已否定",
                                       "n（", "round_trip=n")):
            continue
        bad.append(line.strip()[:120])
    assert not bad, "%s 把同程写成支持往返：%s" % (doc, bad[:3])
