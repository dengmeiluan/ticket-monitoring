# -*- coding: utf-8 -*-
"""r640b：一键收齐必须收干净用户卡内的全部正文，只留 grouplab 标题。

用户原话：「各个 tab 展开状态没有办法一键全部收齐」。

实测（1512，demo）：点一次「全部收齐」后 `panel-users` 里 uhead2 的卡体
仍有 315px 敞着（卡高 3281→615，本该 ~315=6 个标题），而卡头 aria 已写
false —— 按钮在报一个没发生的状态。

根因：卡内 `glab()` 不带 data-sec（面板级 `.grouplab[data-sec]` 循环碰不到），
而 uhead2 分支只隐藏「第一个标题之前 + 最后一个标题之后」的两段，
标题之间的正文（A 用户名的推送设置等）全部留在屏幕上。
修法：卡体里除 .grouplab 之外的子块一律收起。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _ufold_block():
    src = _src()
    i = src.index("panel.querySelectorAll('.uhead2[data-u]').forEach(h=>{\n   if(hide){")
    j = src.index("   else{h.setAttribute('aria-expanded','true');", i)
    return src[i:j]


def test_user_card_body_hides_every_non_header_child():
    blk = _ufold_block()
    assert "k.classList.contains('grouplab')" in blk, "又回到「只处理首尾两段」"
    assert "[...body.children].forEach" in blk, (
        "卡体必须遍历全部子块，而不是只取第一个/最后一个标题之外的两段")
    # 旧实现的两个切片必须消失
    assert "kids.indexOf(last)+1" not in blk, "旧的首尾切片逻辑又回来了"
    assert "const heads=kids.filter" not in blk, "旧的 heads 过滤又回来了"


def test_user_card_header_state_matches_body():
    """收齐时 header aria 与卡体必须同源变化（不能报没发生的状态）。"""
    blk = _ufold_block()
    assert "h.setAttribute('aria-expanded',String(!hide))" in blk, blk[:200]


def test_group_headers_survive_as_entry_points():
    """标题必须留在屏幕上——它是回到内容的唯一入口（r459b 契约）。"""
    blk = _ufold_block()
    assert "grouplab" in blk and "return" in blk
