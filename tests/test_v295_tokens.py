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
    src = _src()
    for token in ("--r-card:14px", "--r-container:12px", "--r-ctl:8px",
                  "--price-lg:24px", "--price-md:19px", "--price-sm:16px"):
        assert token in src, token
    assert ".ws-card{border-radius:var(--r-card)!important" in src
    assert "#loginRows .lgslot{background:transparent" in src


def test_watch_has_one_visible_title():
    src = _src()
    assert '<h2 class="ws-title" id="wsTitle">关注航班</h2>' not in src
    assert '<h2 class="ws-title sr-only" id="wsTitle">关注航班</h2>' in src
    assert 'aria-labelledby="wsTitle"' not in src
