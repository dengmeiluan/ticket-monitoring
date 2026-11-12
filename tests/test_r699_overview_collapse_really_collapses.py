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
    """判据是「有一个零宽撑杆把触发器顶到右缘」，不是某一种实现写法。

    r830 之前撑杆是 `.srx-band-h::after{flex:1 1 auto;order:1}`；r830 把
    触发器挪到标题之后、其余控件挪到触发器之后，撑杆随之变成真实元素
    `.srx-band-fill`（`order:2`，触发器 `order:3`）。两种都能满足意图：
    隐藏左邻后触发器仍贴右缘（实测两态同为 left=1338.5 / top=256.9）。
    """
    joined = "\n".join(_collapsed_rules())
    has_spacer = (
        ("::after" in joined and "flex:1 1 auto" in joined)
        or (".srx-band-fill" in SRC and "flex:1 1 auto" in SRC)
    )
    assert has_spacer, (
        "没有撑杆：隐藏左邻后 margin-left:auto 推不动，触发器会掉到标题右侧")
    assert ("srx-foldbtn{order:2}" in joined) or ("srx-ovtoggle" in SRC and "order:3" in SRC), (
        "撑杆没排在触发器之前，会把按钮挤到左边")


def test_title_row_height_pinned_so_trigger_does_not_shift_vertically():
    joined = "\n".join(_collapsed_rules())
    assert re.search(r"\.srx-band-h\{min-height:34px\}", joined), (
        "标题行在收起态会矮 2px，触发器随之纵移 1px（两态须同坐标）")


def test_collapsed_grid_keeps_no_empty_tracks():
    """收起态只有「标题 + 触发器」，不能被空轨道撑出高度。

    实测缺陷（r832 改 grid 后，1512）：其余成员虽 `display:none`，但
    `grid-area:3/1/4/2` 这类显式放置仍会**建立轨道**，8px 行距把两条空
    轨道一起算进高度——标题行 34→107px，触发器下方多出 73px 空白，
    读起来像「收起了却还留着一条空带」。判据：收起态必须收敛成单轨道
    且行距为 0（`grid-template-rows:auto` + `row-gap:0`）。
    """
    joined = "\n".join(_collapsed_rules())
    body = ""
    for m in re.finditer(
            r"#searchview\.srx-ov-collapsed[^{]*\.srx-band-h\{[^}]*\}", SRC):
        if "grid-template-rows" in m.group(0) or "row-gap" in m.group(0):
            body = m.group(0)
    assert body, "收起态没有单独收敛标题行轨道的规则"
    assert "grid-template-rows:auto" in body, (
        "收起态没有收敛轨道：空的第 3/4 行会把标题行撑高")
    assert "row-gap:0" in body, "收起态仍有行距，空轨道会被撑开"
    assert "min-height:34px" in joined
