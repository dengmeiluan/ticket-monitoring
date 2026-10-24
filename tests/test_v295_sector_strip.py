# -*- coding: utf-8 -*-
"""v1.5.295: one sector strip component, used on three real surfaces."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_sector_strip_component_and_surfaces():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    for s in ("function sectorStripHTML", "class=\"sector-strip",
              "function spMonLow", "function wsRunway",
              "function monWatchCard"):
        assert s in src, s
    assert src.count("sectorStripHTML({") >= 3
