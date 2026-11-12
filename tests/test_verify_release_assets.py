# -*- coding: utf-8 -*-
"""tools/verify_release_assets.py 正/负控。"""
import hashlib
import io
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.verify_release_assets import (SUMS, ZIPS, _forbidden,
                                         verify)  # noqa: E402


def _make_dir(tmp):
    for name, exe in ZIPS.items():
        with zipfile.ZipFile(os.path.join(tmp, name), "w") as z:
            z.writestr(exe, b"x")
            z.writestr("_internal/core/x.py", b"x")
            z.writestr("_internal/tzdata/zoneinfo/UTC", b"x")
    lines = []
    for name in ZIPS:
        h = hashlib.sha256(
            open(os.path.join(tmp, name), "rb").read()).hexdigest()
        lines.append("%s  %s" % (h, name))
    io.open(os.path.join(tmp, SUMS), "w", encoding="utf-8",
            newline="\n").write("\n".join(lines) + "\n")


def test_valid_asset_dir_passes():
    with tempfile.TemporaryDirectory() as tmp:
        _make_dir(tmp)
        assert verify(tmp) == [], verify(tmp)


def test_forbidden_paths_are_top_level_only():
    assert not _forbidden("_internal/tzdata/zoneinfo/UTC")
    assert _forbidden("data/prices.db")
    assert _forbidden("config.yaml")
    assert _forbidden("user_data/qunar/Cookies")


def test_wrong_hash_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        _make_dir(tmp)
        p = os.path.join(tmp, SUMS)
        text = io.open(p, encoding="utf-8").read()
        text = "0" * 64 + text[64:]
        io.open(p, "w", encoding="utf-8", newline="\n").write(text)
        assert any("哈希不符" in e for e in verify(tmp))


def test_extra_file_and_missing_internal_are_reported():
    with tempfile.TemporaryDirectory() as tmp:
        _make_dir(tmp)
        io.open(os.path.join(tmp, "README.txt"), "w").write("x")
        assert any("多余资产" in e for e in verify(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        _make_dir(tmp)
        name = "ticket-monitoring-win64.zip"
        with zipfile.ZipFile(os.path.join(tmp, name), "w") as z:
            z.writestr("TicketMonitor.exe", b"x")
        assert any("_internal" in e for e in verify(tmp))
