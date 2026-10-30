# -*- coding: utf-8 -*-
"""r557：渠道健康诊断卡的「自检」按钮，同一行内必须同一条基线。

用户原话：「渠道健康里又有不对齐的布局设计，自检按钮」。

实测根因：`.hdiag-st` 写着 `white-space:nowrap`，但 flex 子项默认
`min-width:auto` 不许收缩——卡宽 168px 时「飞猪演示 · 无符合条件的航班」
放不下，徽章把 `.hdiag-h` 顶成两行（17px→35px），五张卡的「自检」因此
差 17px（1100 档飞猪/同程 540 vs 其余 523）。
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = SRC.read_text(encoding="utf-8")


def _rule(sel):
    i = TEXT.index(sel)
    j = TEXT.index("}", TEXT.index("{", i))
    return re.sub(r"/\*.*?\*/", "", TEXT[i:j + 1], flags=re.S)


def test_status_pill_can_shrink_inside_header():
    body = _rule(".hdiag-h>.hdiag-st{")
    flat = body.replace(" ", "")
    assert "min-width:0" in flat, body
    assert "overflow:hidden" in flat, body
    assert "text-overflow:ellipsis" in flat, body


def test_channel_name_never_shrinks():
    body = _rule(".hdiag-h>b{").replace(" ", "")
    assert "flex:0 0 auto".replace(" ", "") in body, body
    assert "white-space:nowrap".replace(" ", "") in body, body


def test_header_has_pinned_min_height():
    body = _rule(".hdiag-h{")
    assert "min-height:17px" in body.replace(" ", ""), body


def test_status_pill_keeps_family_padding():
    """胶囊 1px 6px 是同族契约（test_r374 也守着），改收缩不能顺手改内边距。"""
    body = _rule(".hdiag-st{")
    assert "padding:1px 6px" in body, body


def test_header_carries_full_text_in_title():
    i = TEXT.index('class="hdiag-card ')
    seg = TEXT[i:i + 420]
    assert 'class="hdiag-st" title="' in seg, seg
