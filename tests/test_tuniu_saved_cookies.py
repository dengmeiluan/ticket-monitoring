# -*- coding: utf-8 -*-
"""Tuniu saved-session cookies must not be overwritten by synthetic _tac*."""
import httpx
import pytest

from crawlers.tuniu import TuniuCrawler


def _crawler():
    c = object.__new__(TuniuCrawler)
    c.logger = None
    return c


def test_saved_login_taca_and_tac_cookies_are_preserved(monkeypatch):
    c = _crawler()
    monkeypatch.setattr(TuniuCrawler, "_fetch_udid",
                        classmethod(lambda cls, client: pytest.fail("network udid fetch")))
    client = httpx.Client()
    saved = {
        "udid": "U1",
        "_taca": "LOGINMS.1.2.3",
        "_tacb": "B1",
        "_tact": "T1",
        "_tacau": "A1",
        "_tacz2": "Z1",
    }
    for k, v in saved.items():
        client.cookies.set(k, v, domain=".tuniu.com", path="/")
    c._install_tac_cookies(client)
    for k, v in saved.items():
        assert client.cookies.get(k) == v, k
    assert client.cookies.get("_tacc") == "1"
    client.close()


def test_anonymous_client_gets_synthetic_cookies(monkeypatch):
    c = _crawler()
    monkeypatch.setattr(TuniuCrawler, "_fetch_udid",
                        classmethod(lambda cls, client: "ANON"))
    client = httpx.Client()
    c._install_tac_cookies(client)
    taca = client.cookies.get("_taca") or ""
    assert taca.endswith(".1") and taca.count(".") == 3
    assert client.cookies.get("udid") == "ANON"
    assert client.cookies.get("_tacc") == "1"
    client.close()
