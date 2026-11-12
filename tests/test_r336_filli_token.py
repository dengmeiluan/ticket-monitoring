# -*- coding: utf-8 -*-
"""r336 WebUI P1：--fill-i 令牌定义在场钉。

消费点 .t-i（明细行「国际」tag 两渲染位）与 .rintl（配置页国际徽标）
引用 var(--fill-i)，但该令牌声明曾丢失（r325 孤儿注释粘在 --fill-c
行尾、声明行缺位）——白字落透明底，亮色主题对比 ≈1.0:1 文字不可读
（r336 波2-b computed 实证 + 截图存证）。修复=亮/暗两令牌区各补一条
紫系声明（白字 11px ≥4.5:1 同族律）；本钉锁「消费点在场 ∧ 定义在
场」双方位，定义再次丢失当日红。"""
import os
import re

_PAGE = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()


def test_filli_consumers_present():
    assert ".t-i{background:var(--fill-i)}" in _PAGE
    assert ".rintl{background:var(--fill-i)" in _PAGE


def test_filli_defined_in_both_themes():
    # 亮色区 + 暗色区各一条声明（var() 引用无 fallback——定义缺失
    # 即整条 background 塌陷为透明，判例二十一§9「值没了」族）
    defs = re.findall(r"--fill-i:\s*(#[0-9a-fA-F]{3,8})", _PAGE)
    assert len(defs) == 2, f"--fill-i 声明数 {len(defs)} ≠ 2（亮/暗各一）"
    # 紫系第三色相（与直飞蓝/中转橙/日历青灰分档）：R>B>G 的紫系
    # 特征粗校——曾走丢的声明若被人以蓝/灰值复活，此校提示复核色相
    for v in defs:
        r, g, b = int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16)
        assert b > g and r > g, f"--fill-i={v} 非紫系（第三色相分档破缺?）"


def test_filli_wcag_white_text():
    """白字 11px 正文级 AA（≥4.5:1）双主题预验（同族令牌注释契约）。"""
    defs = re.findall(r"--fill-i:\s*(#[0-9a-fA-F]{3,8})", _PAGE)
    for v in defs:
        r, g, b = (int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
        assert 1.05 / (lum + 0.05) >= 4.5, \
            f"--fill-i={v} 白字对比 {1.05/(lum+0.05):.2f}:1 < 4.5（AA 破线）"


def test_no_orphan_comment_on_fillc_line():
    """孤儿注释禁复活：--fill-c 行尾不得再粘紫系注释（声明丢失的
    考古指纹——注释在册而声明缺位=本案原始病灶形态）。"""
    for line in _PAGE.splitlines():
        if "--fill-c:" in line:
            assert "国际 tag" not in line, \
                f"--fill-c 行尾粘紫系孤儿注释：{line.strip()[:80]}"
