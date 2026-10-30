# -*- coding: utf-8 -*-
"""r699 概览收起必须「真收起」，且触发器两态同坐标。

实测缺陷（1512）：
  · 点「收起概览」后 `#srxBand` 仍留 40px：收起规则只隐藏了价带主体，
    标题行里的 **466px 摘要 + 日期翻页 + 110px 出发日·采集日轴 + 52px
    渠道登录** 全都还在（15 个可见元素）——用户读作「点了收起什么都没变、
    整体收不回去」。
  · 只隐藏这些会让触发器失去 `margin-left:auto` 的推挤，left 从 1339
    掉到 197（触发器跳位，违反硬约束）；标题行也从 34 降到 32，纵移 1px。

修后实测：收起态可见元素 2（标题 + 触发器），触发器两态均为
left=1338.5 / top=256.9 / w=62 / h=26，位移 0。
"""
import re

import webui

SRC = webui.PAGE


def _collapsed_rules():
    return re.findall(r"#searchview\.srx-ov-collapsed[^{]*\{[^}]*\}", SRC)


def test_collapsed_state_hides_the_rest_of_the_title_row():
    joined = "\n".join(_collapsed_rules())
    for sel in ("#srxOvSum", "#srxBandMeta", ".srx-bandnav", ".srx-axis",
                ".srx-bandlogin"):
        assert sel in joined, (
            "收起态没有隐藏 %s——标题行会留下一整排操作控件，读作「收不回去」"
            % sel)


def test_trigger_stays_pinned_right_when_title_row_is_slimmed():
    joined = "\n".join(_collapsed_rules())
    assert "::after" in joined and "flex:1 1 auto" in joined, (
        "没有撑杆：隐藏左邻后 margin-left:auto 推不动，触发器会掉到标题右侧")
    assert re.search(r"srx-foldbtn\{order:2\}", joined), (
        "撑杆没排在触发器之前，会把按钮挤到左边")


def test_title_row_height_pinned_so_trigger_does_not_shift_vertically():
    joined = "\n".join(_collapsed_rules())
    assert re.search(r"\.srx-band-h\{min-height:34px\}", joined), (
        "标题行在收起态会矮 2px，触发器随之纵移 1px（两态须同坐标）")
