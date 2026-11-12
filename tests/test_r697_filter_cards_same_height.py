# -*- coding: utf-8 -*-
"""r697 筛选面板同排两卡必须等高（用户实报「上下不对齐、廉价感」）。

实测缺陷（1512 / 1280）：
  · `.srf-common` 底边 529.4，`.srf-time` 底边 427.3 —— **底端差 102px**
    （1280：562.4 vs 427.3 = 135px），右列上半段塌成半张卡 + 一大块空。
  · 根因：`.srf-grid{align-items:start}` 且 `.srf-time{align-self:start}`
    —— r544 只让右栏**最后一张**卡吸收余量，第一张仍按内容收缩。
  · 拉平后余量全落在卡底（实测 114px 死白），故又让内容在卡内均布。

判据（源码规则 + 渲染几何各一条）：全页搜索唯一选择器，不做字符窗口切片
——切片会随注释/规则增删而落空，造出「规则明明在、断言够不着」的假红。
"""
import re

import webui

SRC = webui.PAGE


def test_grid_stretches_same_row_cards():
    m = re.search(r"#searchview \.srf-grid\{[^}]*\}", SRC)
    assert m, "找不到 #searchview .srf-grid 规则"
    assert "align-items:stretch" in m.group(0), (
        "srf-grid 回到 start——同排两张卡会各按内容收缩，底边必然参差：%s"
        % m.group(0)[:120])


def test_time_card_no_longer_pins_to_start():
    found = re.findall(r"\.srf-time\{[^}]*align-self:([a-z]+)[^}]*\}", SRC)
    assert found, "找不到 .srf-time 的 align-self 规则"
    assert all(v == "stretch" for v in found), (
        ".srf-time 仍是 align-self:%s——网格 stretch 会被它自己覆盖掉" % found)


def test_time_card_distributes_its_extra_space():
    """拉高后的余量不能变成卡内孤立空洞（实测 114px 死白）。

    r876：原用 `justify-content:space-between` 把余量摊到每段之间——右侧
    「起降时段」的两组时段因此被推得离标题很远，右栏第 1 行与左栏第 1 行
    差 13.6px（292 vs 278.4），读作「上下不对齐」。
    现改成内容整体贴顶：两栏首行同线，余量落在卡底（与左卡内容贴顶一致）。
    判据由 test_r836_filter_card_voids 实测卡内无 >34px 的孤立空洞来守；
    这里只守「不得回到把余量摊进组间的写法」。
    """
    assert re.search(r"\.srf-time\{[^}]*justify-content:flex-start", SRC), (
        "起降时段卡又用 space-between——组间间距会随卡高漂移，两栏首行错位")


def test_second_row_cards_distribute_their_extra_space():
    """r836 起第二排改为「加工与历史 | 价格带+检索特有竖向堆叠」。

    原判据要求 `.srf-price`/`.srf-evidence` 用 space-between 均分余量；
    实测那样会在两张稀疏卡里各留 57.3 / 100.5px 的大洞（用户报「衔接空格
    很大很空」）。现改为两张卡按内容收缩堆叠，卡内最大空档回到 8px。
    这里同时守住「不被拉回等高」与「两卡仍在」，避免有人只删掉 CSS 就算。
    """
    assert "srf-stack" in SRC, "第二排的堆叠容器不见了"
    m = re.search(r"#searchview \.srf-stack\{[^}]*\}", SRC)
    assert m, "找不到 .srf-stack 规则"
    assert "flex-direction:column" in m.group(0), (
        "价格带/检索特有又变回平铺——卡内会重新出现 57/100px 的洞")
    # 两张卡不得再声明 grid-area（它们是 stack 的 flex 子项，不是网格项）
    for cls in ("srf-price", "srf-evidence"):
        assert not re.search(r"#searchview \.%s\{[^}]*grid-area:(price|evidence)" % cls, SRC), (
            "%s 仍钉在旧网格区域上，会被拉回等高" % cls)
