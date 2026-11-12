# -*- coding: utf-8 -*-
"""1.5.276 cabin parity / demo probe / poll de-dup / JSON gzip."""
import io
import os

import webui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(webui.__file__, encoding="utf-8").read()


def test_discount_cabin_maps_to_economy_for_watch_coverage():
    from core.flighthist import cabin_class
    assert cabin_class("7.0折") == "经济"
    assert cabin_class("4.7折") == "经济"
    assert cabin_class("全价") == "经济"
    assert cabin_class("特价") == "经济"
    assert cabin_class("空客A320") == ""
    assert cabin_class("公务舱 · 7折") == "公务"
    assert cabin_class("头等舱") == "头等"


def test_demo_probe_entry_is_disabled():
    assert "go.disabled=demo" in SRC
    assert "演示模式不发起真实外网探针" in SRC


def test_srx_watch_get_has_inflight_guard():
    assert "pending:false" in SRC
    assert "if(SRX_WATCH.pending)return;" in SRC
    assert "finally{if(seq===SRX_WATCH.seq)SRX_WATCH.pending=false}" in SRC


def test_large_json_responses_gzip():
    assert 'if len(body) > 1024 and "gzip" in (' in SRC
    assert 'self.send_header("Content-Encoding", "gzip")' in SRC
    assert 'self.send_header("Vary", "Accept-Encoding")' in SRC
