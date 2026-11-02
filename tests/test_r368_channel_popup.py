# -*- coding: utf-8 -*-
"""r368: channel jumps open a popup and keep the workbench page."""
import webui


def test_channel_chip_uses_popup_helper():
    src = webui.PAGE
    assert "function srxOpenChannel(url,ev)" in src
    assert "window.open(url,name,'popup,width=1200" in src
    assert 'onclick="return srxOpenChannel(this.href,event)"' in src
    # modifier clicks keep the native new-tab path
    assert "if(ev&&(ev.ctrlKey||ev.metaKey||ev.shiftKey))return true" in src


def test_special_deal_open_uses_popup_helper():
    src = webui.PAGE
    assert 'onclick="return srxOpenChannel(this.href,event)">打开' in src
