# -*- coding: utf-8 -*-
"""r805ac：`detail` 维度按「有无航班级明细」判，不按字段丰富度判。

延续 r805z 的三方对照，本轮把 `detail` 一维量到底（账本全历史、
14,896 个 extra 元素）：

    plat          n      code   name   dep/arr  plane  cabin  baggage
    ctrip       4594    100%   100%    100%    100%   100%    89%
    tuniu       3033    100%   100%    100%     97%   100%     0%
    qunar       3335    100%   100%    100%     17%     1%    18%
    fliggy      3211     29%   100%    100%     29%     0%     0%
    tongcheng    515     93%   100%     93%     93%    93%    93%
    app_zhixing  180     47%    96%    100%      0%     0%     0%
    app_qunar     45     78%    78%    100%      0%     0%     0%

**结论：7 家都有真正的航班级明细**（航班号/时刻/价格齐备），所以
`detail=y` 对七家都成立。字段差异（机型/舱位/行李）是**丰富度**，
不是「有没有明细」——拿它降级 detail 会把「细节少」写成「没这个能力」。

两个容易误判的点，本文件各自钉一条：

1. **看起来缺航班号的行，多半是日历行**：fliggy 的 2,280 个「无 code」
   元素里，`name='日历最低价'`、`depTime=''` —— 日历行结构性没有航班
   时刻（同日历接口本身无航班级信息），不是解析漏项。`tongcheng` 的
   34 个同理。

2. **`name` 里出现航班号是兜底不是造假**：`app_zhixing._to_prices` 写
   `name = airline or flight_no`（国际页有时不返回航司名）。全库 1,087
   个（7.3%）元素命中，ctrip 也有——这是「航司名未知时用航班号占位」的
   显示兜底，下游按 depTime+arrTime 判班次、不依赖 name。把它当数据
   缺陷去"修"会误伤正常行。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_DIMENSIONS  # noqa: E402


def test_every_channel_declares_detail():
    """七家的 detail 都必须是 y：每一家账本里都有航班级明细。

    反向守卫：若哪天某家真的只剩日历（无时刻无航班号），这条会红，
    提醒把它降级——但现在没有这种情况。
    """
    # 2026-11-02 携程 App 修复「选择目的地」城市页判据后已连续两次 32/33
    # 行复验，现已写 y；保留集合给将来新增但尚未复验的可选渠道。
    unverified = set()
    for p in tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS):
        if p in unverified:
            assert CHANNEL_DIMENSIONS[p].get("detail") != "y", (
                "%s 已有连续复验后应移除 unverified 名单" % p)
            continue
        assert CHANNEL_DIMENSIONS[p].get("detail") == "y", (
            "%s 的 detail 不是 y（当前 %r）——账本里它有真实航班级明细"
            % (p, CHANNEL_DIMENSIONS[p].get("detail")))


def test_calendar_rows_are_not_counted_as_detail_defect():
    """日历行（name=日历最低价 / depTime 空）不算「明细缺失」。

    判据落在**构造器**上：日历元素必须显式标成日历产物，这样「无时刻
    无航班号」是可以解释的，而不是被读成解析失败。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert '"name": "日历最低价"' in src, (
        "日历元素的 name 标记没了：无时刻的行会被误判成解析漏项")
    fl = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                 encoding="utf-8").read()
    assert '"日历最低价"' in fl, "fliggy 的日历标记没了"


def test_name_falls_back_to_flight_no_is_intentional():
    """`name = airline or flight_no` 是有意兜底，别当造假去删。

    真机/账本：国际页有时只给航班号不给航司名。留空会让列表显示空白，
    拿航班号占位至少能定位到班次；下游判班次用 depTime+arrTime。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert 'airline or flight_no' in src, (
        "航司名兜底被删了：国际页缺航司名时 name 会变成空串")
    assert "编一个假航班号才是缺陷" in src or "国际页没有航班号" in src, (
        "兜底决策的注释被删了：后人不清楚这是有意的，会误删")
