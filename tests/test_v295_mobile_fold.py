# -*- coding: utf-8 -*-
"""v1.5.295: fold state and mobile affordances are explicit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_fold_helper_syncs_aria_and_restores_text():
    src = _src()
    assert "function srxSetFold" in src
    assert "setAttribute('aria-controls',id)" in src
    assert "aria-expanded" in src
    assert "(folded?'展开':'收起')" in src


def test_mobile_calendar_and_chart_affordance():
    src = _src()
    for s in ("#searchview .srx-grid:has(.srx-mirror.srx-folded)",
              "#searchview .srx-brief .srx-src{flex:0 0 220px!important}",
              "spMonCalFit", "spMonTable",
              "role=\"img\" aria-label=\"特价监控走势\""):
        assert s in src, s
