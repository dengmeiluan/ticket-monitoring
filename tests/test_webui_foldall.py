# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r640b_foldall_user_card.py
- tests/test_r664_foldall_two_state_label.py
- tests/test_r834_foldall_login_card.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import re
import webui


# ---- merged from tests/test_r640b_foldall_user_card.py ----

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


# ---- merged from tests/test_r664_foldall_two_state_label.py ----

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


# ---- merged from tests/test_r834_foldall_login_card.py ----

SRC = webui.PAGE


def test_fold_all_handles_uhead_cards():
    i = SRC.index("function cfgFoldAll()")
    seg = SRC[i:i + 9000]
    assert "_uheadBodies" in seg, (
        "cfgFoldAll 没有处理 .uhead 卡头——登录/渠道入口两张卡收不起来")
    assert "ucard>.uhead" in seg, seg[:200]
    # 判据（_anyOpen）也必须包含这一类，否则第二次点击会判成「还有敞着」
    assert "_uheadBodies(h).some(b=>b.style.display!=='none')" in seg


def test_fold_state_is_replayed_after_rebuild():
    i = SRC.index("function applyFolds()")
    seg = SRC[i:i + 2600]
    assert "FOLD.uhead" in seg, "重建后没有回放 .uhead 折叠存档"


def test_collapsed_uihead_keeps_its_head_visible():
    """收齐后卡头必须留在屏上（回到内容的入口），只收正文。"""
    i = SRC.index("panel.querySelectorAll('.ucard>.uhead').forEach(h=>{\n   const body=_uheadBodies(h);if(!body.length)return;")
    seg = SRC[i:i + 400]
    assert "_setFold(h,body,hide)" in seg, seg
