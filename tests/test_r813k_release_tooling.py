# -*- coding: utf-8 -*-
"""r813k: release-align tooling gates (quotePath / TLS / digest fallback).

These guard the three tooling fixes made while preparing v1.5.307:
  * `git ls-files` quoting silently dropped the Chinese test filename;
  * local Python/OpenSSL had no CA, so GitHub API checks must use curl/Schannel
    without disabling TLS verification;
  * a release-asset URL 502 must fall back to the server-side API digest,
    labelled explicitly, instead of a false red or a silent skip.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "docs"))

import release_align_check as rac  # noqa: E402


def test_git_z_keeps_non_ascii_test_path():
    paths = [p for p in rac.git_z("ls-files", "-z", "tests")
             if p.startswith("tests/test_") and p.endswith(".py")]
    assert "tests/test_r643_干预覆盖每个可见渠道.py" in paths


def test_curl_keeps_tls_verification_and_stdin_config(monkeypatch):
    seen = {}

    class P:
        returncode = 0
        stdout = b"{}"
        stderr = b""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["input"] = kw.get("input")
        return P()

    monkeypatch.setattr(rac.subprocess, "run", fake_run)
    rac._curl("https://api.github.com/x", token=False)
    cmd = seen["cmd"]
    assert "-k" not in cmd and "--insecure" not in cmd
    assert "--config" in cmd and "-" in cmd
    assert cmd[-1] == "https://api.github.com/x"
    assert b"User-Agent: release-align-check" in (seen["input"] or b"")


def test_digest_fallback_flags_body_drift():
    assets = [
        {"name": "a.zip", "digest": "sha256:" + "a" * 64},
        {"name": "b.zip", "digest": "sha256:" + "b" * 64},
        {"name": "SHA256SUMS.txt", "digest": "sha256:" + "c" * 64},
    ]
    checked, total, missing = rac._digest_fallback(assets, "a" * 64)
    assert checked == 2 and total == 2
    assert missing == ["b.zip"]
