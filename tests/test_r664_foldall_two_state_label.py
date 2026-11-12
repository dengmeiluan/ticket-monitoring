# -*- coding: utf-8 -*-
"""r664 配置页「全部收齐」按钮：两态同宽同坐标 + 词面说真话。

实测缺陷（1512 档，cfg 视图，浏览器量渲染几何）：
  · 词面 全部收齐(83px) → 已收齐 31(85.1px) → 已全部展开(94px)，
    右对齐工具条里按钮自身左移最多 11px、左侧邻居跟着挪 2.1~11px。
    用户三令五申「展开和收起都不在同一个位置，明显是一个按钮多态」。
  · 2.2s 后无条件复位成「全部收齐」：此时区块仍全收着，按钮描述的动作
    是「收起」，按下却会「全部展开」——按钮在报一个不会发生的动作。
"""
import re
import webui


def _fn():
    src = webui.PAGE
    i = src.index("function cfgFoldAll(){")
    return src[i:src.index("\nfunction ", i + 10)]


def test_fold_all_label_is_two_symmetric_action_words():
    seg = _fn()
    assert "t.textContent=hide?'全部展开':'全部收齐'" in seg, \
        "词面不是两个等长动作词——长度一变，右对齐工具条整排跟着横移"
    # 计数反馈只能出现在 toast，不能塞回按钮词面
    assert "已收齐 '+n" not in seg.split("toast(")[0], \
        "按钮词面里又塞了计数（宽度会随 n 的位数变化）"


def test_fold_all_label_matches_next_action_on_both_states():
    seg = _fn()
    # hide=true（刚把全部收起来）→ 下一次动作是展开；hide=false → 下一次是收齐
    assert "hide?'全部展开':'全部收齐'" in seg
    assert "setAttribute('aria-expanded',hide?'false':'true')" in seg


def test_fold_all_does_not_reset_label_to_a_stale_word():
    seg = _fn()
    assert "setTimeout(()=>{const x=$('cfgFoldAllTxt')" not in seg, \
        "又有 2.2s 复位：全收着时复位成「全部收齐」，描述的动作与实际相反"
    # 计数仍必须播报（只是改由 toast 承担）
    assert "已收齐 '+n+' 个分区" in seg


def test_fold_all_label_never_shifts_rendered_width():
    """浏览器实测口径留给 tests/test_ui；这里守源码层的等长约束。"""
    seg = _fn()
    seg = re.sub(r"\s+", " ", seg)
    labels = re.findall(r"'全部(收齐|展开)'", seg)
    assert len(labels) >= 2, seg
