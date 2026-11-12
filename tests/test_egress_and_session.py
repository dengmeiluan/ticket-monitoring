# -*- coding: utf-8 -*-
"""按渠道绑出口 + 会话年龄（6/4 区）。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("egress-test")


def test_proxy_map_overrides_global_per_channel(tmp_path):
    cfg = {"user_data_dir": str(tmp_path), "delay_min": 0, "delay_max": 0,
           "proxy": "http://127.0.0.1:7897",
           "proxy_map": {"qunar": "http://127.0.0.1:7891"}}
    q = QunarCrawler(dict(cfg), _LOG)
    assert q.proxy == "http://127.0.0.1:7891"
    f = FliggyCrawler(dict(cfg), _LOG)
    assert f.proxy == "http://127.0.0.1:7897"      # 没配 → 回全局


def test_proxy_map_missing_keeps_global(tmp_path):
    cfg = {"user_data_dir": str(tmp_path), "delay_min": 0, "delay_max": 0}
    q = QunarCrawler(dict(cfg), _LOG)
    assert q.proxy == ""


def test_session_age_days_zero_without_snapshot(tmp_path):
    c = QunarCrawler({"user_data_dir": str(tmp_path), "delay_min": 0,
                      "delay_max": 0}, _LOG)
    assert c.session_age_days == 0.0
    assert c.session_max_days == 0
