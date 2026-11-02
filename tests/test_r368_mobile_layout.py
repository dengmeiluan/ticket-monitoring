# -*- coding: utf-8 -*-
"""r368: monitor route cards must not force a 360px min column on 320/390."""
import webui


def test_route_grid_uses_viewport_clamped_min_column():
    src = webui.PAGE
    assert "repeat(auto-fit,minmax(min(360px,100%),1fr))" in src
    assert "repeat(auto-fit,minmax(360px,1fr))" not in src


def test_route_card_can_shrink():
    src = webui.PAGE
    assert ".monroute{min-width:0;" in src
