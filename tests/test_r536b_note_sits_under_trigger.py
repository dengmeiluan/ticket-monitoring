# -*- coding: utf-8 -*-
"""r536b：诊断卡「展开说明」的正文必须紧贴触发钮，中间无任何常驻盒。

用户原话：「例如检索页面的说明按钮，又是一样的错误，说明的展开是在
检索控制台的下面！展开收起怎么能中间有元素呢？」
r536 用 -17px 负 margin 只吃掉了一部分；实测按钮底 346.5 / 说明盒顶
357.5，仍剩 11px，命中的是三层底部留白：
  .scfoot padding-bottom 8 + .srccap margin-bottom 10 + .uhead padding-bottom 10。
r536b 取 -28px，说明盒顶边与按钮底边重合（实测五档 gap=0.0、mid=None），
文字呼吸改由自身 padding-top:4px 承担。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _note_rule():
    m = re.search(r"#healthDiag>#scNote\{([^}]*)\}", _src())
    assert m, "说明的定位规则不见了"
    return m.group(1).replace(" ", "")


def test_note_margin_covers_all_three_bottom_gaps():
    body = _note_rule()
    neg = re.search(r"margin:(-?\d+)px", body)
    assert neg, body
    assert int(neg.group(1)) <= -28, (
        "负 margin 小于三层底部留白(8+10+10)，说明与按钮之间会重新露缝：%s"
        % body)


def test_note_keeps_its_own_breathing_room():
    """贴边不等于贴字：文字呼吸由自身 padding-top 给，不再靠容器留白。"""
    body = _note_rule()
    assert "padding-top:4px" in body, body


def test_note_still_outside_card_head_and_action_row():
    src = _src()
    i = src.index('<span class="scnote" id="scNote">')
    assert src.rindex("</div>", 0, i) < i, "说明被塞回卡头里了"
    acts = src.index('<span class="scacts">')
    assert i > src.index("</span>", acts), "说明又进了 scacts 行"
