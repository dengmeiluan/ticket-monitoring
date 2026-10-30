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
    assert re.search(r"\.srf-time\{[^}]*justify-content:space-between", SRC), (
        "拉高后的余量会全堆在卡底（实测 114px 死白），内容需要均布")


def test_second_row_cards_distribute_their_extra_space():
    """第二排同排等高后，价格带/检索特有也被拉高——内容贴顶会让卡底空
    100+ 而左卡只空 12px（实测 110.6 / 104.5 vs 12）。同样要均布。"""
    # 同名选择器有多条规则（grid-column / border-top / 本条的 justify），
    # 只取第一条会命中 grid-column 那条，断言永远为假。
    bodies = re.findall(
        r"\.srf-price,#searchview \.srf-evidence\{([^}]*)\}", SRC)
    assert bodies, "找不到 .srf-price/.srf-evidence 合并规则"
    assert any("justify-content:space-between" in b for b in bodies), (
        "第二排的余量会全堆在卡底（实测 110.6/104.5px），需与左卡同律均布")
