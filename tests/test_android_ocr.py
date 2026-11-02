# -*- coding: utf-8 -*-
"""Windows OCR 词块读取：平台/失败/编码兜底（不调真实 PowerShell）。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import ocr


class R:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def _payload():
    lines = [{"text": "09：00", "words": [
        {"t": "09", "x": 39, "y": 694, "w": 49, "h": 37},
        {"t": "：", "x": 95, "y": 709, "w": 7, "h": 21},
        {"t": "00", "x": 109, "y": 694, "w": 49, "h": 37},
    ]}]
    return json.dumps(lines, ensure_ascii=False, separators=(",", ":"))


def test_unsupported_platform_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr.sys, "platform", "linux")
    assert ocr.ocr_words(b"\x89PNG...") == []


def test_empty_png_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    assert ocr.ocr_words(b"") == []


def test_reads_gbk_json_and_flattens_words(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=_payload().encode("gbk")))
    words = ocr.ocr_words(b"\x89PNG...")
    assert [w["t"] for w in words] == ["09", "：", "00"]
    assert words[0]["x"] == 39 and words[0]["h"] == 37


def test_timeout_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("powershell", 1)

    monkeypatch.setattr(subprocess, "run", boom)
    assert ocr.ocr_words(b"\x89PNG...") == []


def test_bad_json_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: R(out=b"not json"))
    assert ocr.ocr_words(b"\x89PNG...") == []
