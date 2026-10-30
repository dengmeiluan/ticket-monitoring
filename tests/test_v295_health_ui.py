# -*- coding: utf-8 -*-
"""v1.5.295: health diagnosis is server-classified and never guesses in JS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_server_diag_and_selfcheck_present():
    src = _src()
    for s in ('out["diag"] = classify_round', "/api/channel/selfcheck",
              "channel_evidence.jsonl", "_cookie_states",
              "j.diag", "diagSelfcheck"):
        assert s in src, s


def test_render_no_longer_regex_classifies():
    src = _src()
    start = src.index("function renderHealthDiag")
    end = src.index("async function diagSelfcheck")
    body = src[start:end]
    assert "179991|IP|403" not in body
    assert "j.diag" in body
    assert "不猜测" in body
