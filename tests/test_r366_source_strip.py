# -*- coding: utf-8 -*-
"""v1.5.283 source-access strip: compact one-line layout, note on demand."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_source_access_is_compact_strip_not_three_tall_cards():
    assert "#srccap{display:flex;align-items:center;gap:8px 12px" in SRC
    assert ("#srccap .scnode{display:inline-flex;flex-direction:row;"
            "align-items:center") in SRC
    assert "#srccap .scnode em{display:none}" in SRC
    assert "#srccap .scnote{display:none" in SRC
    assert 'id="scNoteBtn"' in SRC and 'id="scNote"' in SRC
    assert "function srxToggleScNote(btn){" in SRC
    assert 'title="PC 网页已于 2026-10-10 停服"' in SRC


def test_source_access_mobile_is_two_row_grid_without_tall_stack():
    assert "#srccap .scpath{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)" in SRC
    assert "#srccap .scnode.gate{grid-column:1/-1;justify-content:flex-start}" in SRC
    assert "#srccap .scarr{display:none}" in SRC
