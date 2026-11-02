# -*- coding: utf-8 -*-
"""Special-fare radar: per-deal source-channel links + standalone tab wiring."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_special_deal_source_links():
    from core.specials import special_deal_link
    u = special_deal_link("tuniu", "上海", "北京", "2026-10-26")
    assert "m.tuniu.com/flight/domestic" in u
    u = special_deal_link("ctrip", "上海", "北京", "2026-10-26")
    assert "m.ctrip.com/html5/flight/taro" in u
    u = special_deal_link("fliggy", "上海", "北京", "2026-10-26")
    assert "sjipiao.fliggy.com" in u
    assert special_deal_link("unknown", "上海", "北京", "2026-10-26") == ""
    assert special_deal_link("tuniu", "不存在", "北京", "2026-10-26") == ""


def test_specials_tab_and_deal_link_wiring():
    import webui
    page = webui.PAGE
    for needle in ('data-t="specials"', 'id="montab-specials"',
                   'id="spfullbody"', "打开", "d.url", "showMonTab('specials')", "srxSpBody", "srxSpOpen", "srxSpecialHTML", "srxSpLoad", "capabilities"):
        assert needle in page, needle
    src = open(webui.__file__, encoding="utf-8").read()
    assert "special_deal_link" in src
