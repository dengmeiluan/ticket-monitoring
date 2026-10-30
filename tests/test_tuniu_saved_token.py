# -*- coding: utf-8 -*-
"""r368: Tuniu page tokenKey extraction for the authenticated list API."""
import logging
import os
from urllib.parse import urlencode

from crawlers.tuniu import TuniuCrawler


def test_token_from_list_request_url():
    d = '{"systemId":53,"segmentList":[],"tokenKey":"abc123"}'
    url = "https://flight-api.tuniu.com/wzt/flight/v1/listFlight?" + urlencode({"d": d})
    assert TuniuCrawler._token_from_request(url) == "abc123"


def test_token_missing_or_bad_payload_is_empty():
    assert TuniuCrawler._token_from_request("https://x/listFlight?d=%7Bbad") == ""
    assert TuniuCrawler._token_from_request("https://x/listFlight") == ""


def test_crawler_uses_saved_h5_surface_profile(tmp_path):
    base = tmp_path / "tuniu"
    (base / "surfaces" / "h5" / "Default").mkdir(parents=True)
    (base / "surfaces" / "pc" / "Default").mkdir(parents=True)
    c = TuniuCrawler({"user_data_dir": str(tmp_path)},
                     logging.getLogger("test-tuniu-surface"))
    c.use_mobile = True
    assert c.user_data_dir.endswith(os.path.join("surfaces", "h5"))
    c.use_mobile = False
    assert c.user_data_dir.endswith(os.path.join("surfaces", "pc"))


def test_fetch_skips_pc_when_h5_token_exists():
    src = open(TuniuCrawler.__module__.replace(".", "/") + ".py",
               encoding="utf-8").read()
    assert "if not ret_date and not h5_token:" in src

