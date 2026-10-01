# -*- coding: utf-8 -*-
"""r260 推送 P2-1：_mini_split 地板 token 语义对齐 + 行3/mini 地板收单源。

定谳（钉面形态的依据）：
1. 段形态可达性：审计样本「线￥N　差￥M」非 _mini_kpi 可产出形态；
   真实 tier_dot/gap_txt 构造的「低￥N*行情」单段超宽由**去注档**
   （丢 *行情 不丢数）先吃——逐字截地板在现实词面域内数学不可达
   （_scratch/r260_p21_grid_out.txt + 去注档推演）。
2. 收口内容：行3 引用块地板的内联 token 回滚与 mini 地板收单源
   _trunc_tokens（三十一§2 同律一处实现）；mini 地板语义从逐字截
   对齐为 token 边界贪心（变化仅在不可达域，未来词面扩长时差额
   词/短注要么完整要么缺席，不产「￥190」半金额）。
3. 钉面=档序（去注先于截断）+ helper 直调语义 + 金额完整性，
   不锁不可达域的伪行为。"""
import re
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import alerter as _al

_HEAD = "📍 10/06　"


def _trig(label, price, th):
    """按真实单源构造超宽段（tier_dot 点后带尾空格——手抄词面漏
    空格即 _disp_dw=40 不触发，测试假绿；直调单源防词面漂移）。"""
    diff = price - th
    seg = (f"{_al.tier_dot(False, diff, th)}{label} ￥{price} "
           f"{_al.gap_txt(price, th, False)}*行情")
    assert _al._disp_dw(_HEAD + seg) > 40, f"样本不触发: {seg!r}"
    return seg


# 网格实证的现实超宽形态（🟩×低￥N*行情，head+seg=41 恰超线）
_TRIGGERS = [_trig(lb, p, th)
             for lb in ("直飞", "中转")
             for p, th in ((1234, 19000), (2280, 19000), (12345, 19000))]


@pytest.mark.parametrize("seg", _TRIGGERS)
def test_mini_split_dennote_before_truncation(seg):
    """结果级锁：单段超宽输出差额词完整在场+短注缺席+预算内
    （去注档承载该形态；若降级链档序回退使截断先吃，金额完整性与
    预算断言同样收口）。"""
    out = _al._mini_split(_HEAD, [seg])
    body = out.strip()
    assert body, "地板档恒落位：行内容不得净失"
    assert _al._disp_dw(body) <= 40, body
    gap = re.search(r"[低差]￥\d+", seg).group(0)
    assert gap in body, f"差额词 {gap} 必须完整在场，got {body!r}"
    assert "*行情" not in body  # 去注档已丢短注
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in set(re.findall(r"￥(\d+)", seg)), \
            f"半截金额 ￥{amt} in {body!r}"


def test_trunc_tokens_token_boundary_greedy():
    """_trunc_tokens 单源语义钉：截点落 token 中部回退 token 起点
    （整 token 丢弃）、首 token 超预算逐字截保前缀（恒落位律）、
    全角分隔形态。"""
    assert _al._trunc_tokens("AA BBBB CC", 6) == "AA"      # BBBB 整删
    assert _al._trunc_tokens("AA BBBB CC", 8) == "AA BBBB"
    assert _al._trunc_tokens("BBBBBB CC", 4) == "BBBB"   # 首token逐字截
    assert _al._trunc_tokens("AA　BB", 5, sep="　") == "AA"


def test_mini_split_floor_tokens_whole_or_absent():
    """mini 地板 token 语义（函数级直调——现实域数学不可达，构造
    超预算形态验证）：非首 token 要么完整要么缺席，金额不截半。"""
    seg = "🎯 直飞 ￥12345 低￥6655"
    # 压缩 head 预算到金额必截带：head 用病理长词面吃满预算
    head = "📍 " + "长" * 12 + "　"
    out = _al._mini_split(head, [seg])
    body = out.strip()
    assert _al._disp_dw(body) <= 40, body
    whole = set(re.findall(r"￥(\d+)", seg))
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in whole, f"半截金额 ￥{amt} in {body!r}"


@pytest.mark.parametrize("seg", _TRIGGERS)
def test_mini_split_floor_amount_whole(seg):
    """输出中出现的 ￥金额必须是输入段的完整金额——「￥190」半截
    金额会被读成错误值（决策级信息损坏）。"""
    out = _al._mini_split(_HEAD, [seg])
    body = out.strip()
    whole = set(re.findall(r"￥(\d+)", seg))
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in whole, f"半截金额 ￥{amt} in {body!r}"
