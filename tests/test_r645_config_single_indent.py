# -*- coding: utf-8 -*-
"""r645：配置页对齐不得靠负 margin（会裁字）。

用户原话：「配置页面的交互排版层级似乎被改坏了，也没有对齐了」。

实测（1512）：卡头文字 333.5 / 分组标题 343.5 / 设置行 345.5 /
参数格标签 325.5 —— 四层各走一条线，最大差 20px。

**一次失败的修法（已回退，必须记下来）**：给 `.srow` / `.grouplab` 加
`margin-left:-10px` 后，left 坐标确实同线了，但 `.ucard` 带
`overflow:hidden`，向左推出的 10px 落在裁剪区——截图可见「用户名」被裁成
「户名」、「合并推送」被裁成「合推送」。数字对齐 ≠ 看得见。

结论：卡内比卡头右 10px 是「卡头有 22px 图标」的结构代价，不是缺陷。
真正需要修的是参数格（.glcell 自身 14px 内距造成的 325.5）。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def test_params_cell_uses_shared_indent_token():
    """参数格标签要与卡头同线：padding = --cfg-ico - 9px（=22px）。"""
    src = _src()
    m = re.search(r"#cfgview #cfgglobals \.glcell,#cfgview #cfgpacing \.glcell\{"
                  r"\s*padding-left:([^!]+)!important\}", src)
    assert m, "参数格缩进规则不见了"
    assert m.group(1).replace(" ", "") == "calc(var(--cfg-ico)-9px)", m.group(1)


def test_no_negative_margin_alignment_in_cfg_rows():
    """回归守卫：不得用负 margin 把行推出 overflow:hidden 容器（会裁字）。"""
    src = _src()
    for sel in ("#cfgview #cfgform .srow", "#cfgview #cfgform .grouplab"):
        for m in re.finditer(re.escape(sel) + r"\{([^}]*)\}", src):
            body = m.group(1).replace(" ", "")
            assert "margin-left:-" not in body, (
                "%s 又用负 margin 对齐了——.ucard 有 overflow:hidden，会裁掉首字：%s"
                % (sel, body))


def test_group_header_never_pushes_text_with_padding():
    """分组标题首个子元素是序号徽标；改 padding 会把它推出边界。"""
    src = _src()
    hits = list(re.finditer(r"#cfgview \.grouplab\{([^}]*)\}", src))
    assert hits, "分组标题基础规则不见了"
    body = hits[-1].group(1).replace(" ", "")
    assert "padding-left:0!important" in body, body
