"""推送图文精细化：渠道列段序（tie 前置）。

背景：渠道列 92px 固定预算下「渠道·Nh前·同价×N」在 stale+tie 同现时，
×N 计数整段被省略号截掉（45/45 组合实测全灭）——同价渠道数是决策信息
（点哪家都一样的同价行，N 是唯一的比价结论），补位时长是次要信号。
档序律：次要段殿后，截断只吃尾巴。词面逐字不变、仅段序对调，
图版 _plat_tag 与文本版 plat_full 同步（两版「同词面同序」承诺）。"""

import pytest


def test_plat_tag_tie_precedes_stale():
    from report import _plat_tag
    cn = {"tongcheng": "同程", "qunar": "去哪儿"}
    # tie+stale 同现：tie 前置（被截的恒是 stale 尾段）
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 2,
                      "_stale_h": 99.0}, cn) == "同程·同价×2·99h前"
    # 无 stale / 无 tie 行形态不变
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 3}, cn) == \
        "同程·同价×3"
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 1.0}, cn) == \
        "同程·1h前"
    assert _plat_tag({"_platform": "qunar"}, cn) == "去哪儿"


def test_plat_full_tie_precedes_stale():
    # 文本版同序：两段同现时 tie 必在 stale 前；全形态超 40 半角走
    # 骨架档（渠道·同价×N）时 stale 可丢、tie 必保
    from core.alerter import Alerter
    f = {"_platform": "tongcheng", "_tie_n": 2, "_stale_h": 99.0,
         "price": 900, "name": "9C6928", "depTime": "08:30",
         "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(f, idx=1)
    i_tie, i_stale = line.find("同价×2"), line.find("99h前")
    if i_stale >= 0:
        assert 0 <= i_tie < i_stale
    else:
        assert i_tie >= 0
