# -*- coding: utf-8 -*-
"""r536b（r873 改版后）：诊断卡「展开说明」的正文必须紧贴触发钮，中间无任何常驻盒。

用户原话：「例如检索页面的说明按钮，又是一样的错误，说明的展开是在
检索控制台的下面！展开收起怎么能中间有元素呢？」

r536b 的实现是「说明挂在卡外 + 负 margin 吃掉三层底部留白」。
r873 起换成更彻底的做法：说明进到来源条 `#srccap` 里、绝对定位贴在
动作行下方，卡片用 `padding-bottom:calc(var(--noteh) + 16px)` 预留高度——
中间**结构上不可能**再夹盒子，也不必靠负 margin 抵空隙。

因此这里守的是同一条意图：① 说明与触发钮之间隔的就是卡片自己的底部
内衬（≤20px）；② 文字呼吸由自身承担，不靠容器留白；③ 说明不在卡头
flex 行里、也不在 .scacts 动作行里。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _note_rule():
    m = re.search(r"#srccap \.scnote\{([^}]*)\}", _src())
    assert m, "说明的定位规则不见了（r873 起为 #srccap .scnote）"
    return m.group(1).replace(" ", "")


def test_note_margin_covers_all_three_bottom_gaps():
    """说明与按钮之间的空隙只剩卡片自身底部内衬——不许再叠第三层留白。

    r873 方案：`.scnote` 绝对定位，卡片 `padding-bottom = noteh + 16px`
    （16 = 8 上呼吸 + 8 下内衬）。判据：定位规则带 left/right 锚（说明与卡同宽），
    且卡片预留高度写的是「说明高度 + 一个有限常量」而不是固定大值。
    """
    body = _note_rule()
    assert "position:absolute" in body, body
    assert "left:12px" in body and "right:12px" in body, body
    src = _src()
    m = re.search(r"#healthDiag #srccap\.scopen\{([^}]*)\}", src)
    assert m, "卡片没有按说明高度预留底部内衬（r873 的核心机制）"
    rule = m.group(1).replace(" ", "")
    assert "--noteh" in rule and "+16px" in rule, rule


def test_note_keeps_its_own_breathing_room():
    """贴边不等于贴字：文字呼吸由自身承担（行高 1.5），不靠容器留白。"""
    body = _note_rule()
    assert "line-height:1.5" in body, body


def test_note_still_outside_card_head_and_action_row():
    src = _src()
    i = src.index('<span class="scnote" id="scNote">')
    assert src.rindex("</div>", 0, i) < i, "说明被塞回卡头里了"
    acts = src.index('<span class="scacts">')
    assert i > src.index("</span>", acts), "说明又进了 scacts 行"
