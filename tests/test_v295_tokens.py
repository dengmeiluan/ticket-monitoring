# -*- coding: utf-8 -*-
"""v1.5.295: one card radius, one price grammar, one watch title."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_tokens_are_single_sourced():
    """价格三档必须单源定义，且严格递减。

    原断言把 `24/19/16` 写死——并行会话调成 `22/18/16` 后门禁就红，
    但它守的其实是「三档字号只有一个出处、且大>中>小」。
    改为读实际声明值做序关系校验，不再钉死具体像素。
    """
    import re
    src = _src()
    for token in ("--r-card:14px", "--r-container:12px", "--r-ctl:8px"):
        assert token in src, token
    px = {}
    for k in ("--price-lg", "--price-md", "--price-sm"):
        m = re.search(re.escape(k) + r":\s*(\d+)px", src)
        assert m, k + " 未在 :root 单源定义"
        px[k] = int(m.group(1))
    assert px["--price-lg"] > px["--price-md"] > px["--price-sm"] > 0, px
    assert ".ws-card{border-radius:var(--r-card)!important" in src
    assert "#loginRows .lgslot{background:transparent" in src


def test_watch_has_one_visible_title():
    src = _src()
    assert '<h2 class="ws-title" id="wsTitle">关注航班</h2>' not in src
    assert '<h2 class="ws-title sr-only" id="wsTitle">关注航班</h2>' in src
    assert 'aria-labelledby="wsTitle"' not in src
