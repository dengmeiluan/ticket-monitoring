# -*- coding: utf-8 -*-
"""v1.5.295: closed facet panel must not rebuild its hidden DOM."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_facets_guard_and_perf_script():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert "if(!SRX.more&&!force)return;" in src
    assert os.path.isfile(os.path.join(ROOT, "docs", "perf_gate.py"))
