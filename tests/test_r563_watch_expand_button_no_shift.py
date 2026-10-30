# -*- coding: utf-8 -*-
"""r563：关注航班卡的「展开详情」钮，展开前后必须在同一位置。

用户原话：「现在比如展开探针，展开应该是展开的感觉，怎么位置都发生了
偏移，明显不是一个按钮多态的设计」。

实测根因：`.ws-row-act` 原是 `<article class="ws-row">` 的直接子级，
用 `top:50%` 相对整个 article 垂直居中；展开详情后 article 变高
（1512：82→298），钮中心随之下移 —— 实测 +108px（390 档 +263px）。
修法：动作钮挂进恒高的 `.ws-row-main`，`.ws-row-main` 加
`position:relative` 作为定位容器；两态都以内容行为锚，位置不动。
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = SRC.read_text(encoding="utf-8")


def _rule(sel):
    i = TEXT.index(sel)
    j = TEXT.index("}", TEXT.index("{", i))
    return re.sub(r"/\*.*?\*/", "", TEXT[i:j + 1], flags=re.S)


def _row_html():
    """取出拼装 .ws-row 的那段源码（从 `<article class="ws-row` 到 `</article>`）。"""
    i = TEXT.index('<article class="ws-row')
    j = TEXT.index("</article>'", i)
    return TEXT[i:j + len("</article>'")]


def _main_close(seg):
    """从 `class="ws-row-main"` 起，按 div 开/闭配对找它的闭合位置。"""
    start = seg.index('class="ws-row-main"')
    # 定位这个 div 的起始 '<div'
    open_at = seg.rindex("<div", 0, start)
    depth = 0
    i = open_at
    while i < len(seg):
        if seg.startswith("<div", i):
            depth += 1
            i += 4
            continue
        if seg.startswith("</div>", i):
            depth -= 1
            if depth == 0:
                return i
            i += 6
            continue
        i += 1
    raise AssertionError("未找到 .ws-row-main 的闭合标签")


def test_action_buttons_live_inside_main_row():
    """动作钮必须是 .ws-row-main 的后代，不能是 article 的子级。"""
    seg = _row_html()
    act_at = seg.index('class="ws-row-act"')
    close_main = _main_close(seg)
    assert act_at < close_main, (
        "动作钮仍在 .ws-row-main 之外——展开后会随 article 变高而下移")


def test_main_row_is_positioning_context():
    body = _rule(".ws-row-main{")
    assert "position:relative" in body.replace(" ", ""), body


def test_action_buttons_still_vertically_centred_on_main():
    body = _rule(".ws-row-act{")
    flat = body.replace(" ", "")
    assert "position:absolute" in flat, body
    assert "top:50%" in flat, body
    assert "translateY(-50%)" in flat, body


def test_detail_stays_outside_main_row():
    """展开体必须留在 article 层，不能被塞进内容行（否则行高会被撑开）。"""
    i = TEXT.index('class="ws-row-main"')
    j = TEXT.index("</article>", i)
    seg = TEXT[i:j]
    main_start = 0
    close_main = seg.index("</div>", seg.index('class="ws-row-act"'))
    detail_at = seg.index('class="ws-detail"')
    assert detail_at > close_main, "展开体被塞进了内容行"
