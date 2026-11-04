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


# 每个 y 渠道的「往返总价」证据形态不同：行级回程字段、价差不变式、
# 官方往返接口/产品总价、页面「往返总价」文案。这里按渠道钉真实实现，
# 不再用 skip 把不适用的分支跳过——不适用就断言它属于 n/""。
RT_EVIDENCE = {
    "ctrip": ("_fetch_rt", "containstax=1", "product_round_trip_total"),
    "qunar": ("_fetch_rt", "_parse_rt_body", "往返总价",
              "product_round_trip_total"),
    "tongcheng": ("book1/roundtrips", "_parse_rt_fps", "_fetch_intl_rt",
                  "miflightapi/ts/list", 'e.get("tp")', 'e.get("lng")'),
    "tuniu": ("avgTotalPrice", "product_round_trip_total"),
    "fliggy": ('.get("backDate")', "!= ret_date"),
}


@pytest.mark.parametrize("plat", BROWSER_CHANNELS)
def test_round_trip_y_has_channel_specific_evidence(plat):
    """记 y 就必须有可复核的「渠道自报往返总价」实现。

    证据按渠道取真实形态：飞猪/同程读行级回程字段并比对；携程/去哪儿
    用官方往返页/接口的产品总价；途牛用 avgTotalPrice。**不适用该分支
    的渠道断言其为 n/""，不再 skip**。
    """
    state = dim_state(plat, "round_trip")
    if state != "y":
        assert state in ("", "n"), state
        return
    src = _src(plat)
    missing = [t for t in RT_EVIDENCE[plat] if t not in src]
    assert not missing, (
        "%s 声明 round_trip=y，但缺少往返总价证据 %s；"
        "只把 ret_date 塞进 URL 不算证据" % (plat, missing))


def test_round_trip_states_are_exhaustive():
    """三态必须互斥且完整：y 有证据、n/"" 有明确声明，没有第四种。"""
    states = {p: dim_state(p, "round_trip") for p in BROWSER_CHANNELS}
    assert set(states.values()) <= {"y", "", "n"}, states
    for plat, st in states.items():
        assert st in ("y", "", "n"), (plat, st)


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
