# -*- coding: utf-8 -*-
"""TLS 指纹出口：有 curl_cffi 用指纹通道，没有就平静退回 httpx。"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import net  # noqa: E402


class _Resp:
    status_code = 200
    text = "ok"
    headers = {}


def test_uses_curl_cffi_when_available(monkeypatch):
    seen = {}

    def _post(url, **kw):
        seen.update(kw)
        return _Resp()

    fake = types.SimpleNamespace(requests=types.SimpleNamespace(post=_post))
    monkeypatch.setitem(sys.modules, "curl_cffi", fake)
    r = net.post("https://example.invalid/x", headers={"a": "b"},
                 payload=b"{}")
    assert r.status_code == 200
    assert seen.get("impersonate") == "chrome"
    assert seen.get("data") == b"{}"


def test_falls_back_to_httpx_when_missing(monkeypatch):
    import httpx
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # import 失败
    seen = {}

    def _post(url, **kw):
        seen.update(kw)
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post)
    r = net.post("https://example.invalid/y", payload=b"{}")
    assert r.status_code == 200
    assert seen.get("content") == b"{}"


def test_impersonate_empty_skips_curl_cffi(monkeypatch):
    import httpx
    called = {}
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: called.setdefault("httpx", _Resp()))
    net.post("https://example.invalid/z", payload=b"{}", impersonate="")
    assert called.get("httpx") is not None


def test_new_client_maps_httpx_kwargs(monkeypatch):
    """follow_redirects/proxy/trust_env 要映射成 curl_cffi 认识的名字。"""
    seen = {}

    class _Sess:
        def __init__(self, **kw):
            seen.update(kw)

    def _session(**kw):
        s = _Sess(**kw)
        seen["obj"] = s
        return s

    fake = types.SimpleNamespace(requests=types.SimpleNamespace(Session=_session))
    monkeypatch.setitem(sys.modules, "curl_cffi", fake)
    c = net.new_client("chrome", headers={"a": "b"}, timeout=25,
                       follow_redirects=True, trust_env=False,
                       proxy="http://127.0.0.1:7897")
    assert seen.get("impersonate") == "chrome"
    assert seen.get("allow_redirects") is True
    assert "follow_redirects" not in seen
    assert "trust_env" not in seen
    assert seen.get("proxies") == {"http": "http://127.0.0.1:7897",
                                   "https": "http://127.0.0.1:7897"}
    assert seen.get("timeout") == 25


def test_new_client_falls_back_to_httpx_client(monkeypatch):
    import httpx
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    c = net.new_client("chrome", timeout=5, follow_redirects=True)
    assert isinstance(c, httpx.Client)
    c.close()
