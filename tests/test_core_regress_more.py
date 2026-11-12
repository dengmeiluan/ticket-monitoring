# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1136_wave4_coverage_unity.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import csv
import io
import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1136_wave4_coverage_unity.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _payload():
    from core.channels import channel_dims_payload
    return channel_dims_payload()


def _missing_notes(payload):
    bad = []
    for c in payload["channels"]:
        for d, v in c["cells"].items():
            if v != "y" and not (c.get("dim_notes", {}).get(d) or c.get("dim_scopes", {}).get(d)):
                bad.append("%s/%s=%r" % (c["plat"], d, v))
        for s, v in (c.get("surface_cells") or {}).items():
            if v != "y" and not (c.get("surface_notes", {}).get(s) or ""):
                bad.append("%s/surface-%s=%r" % (c["plat"], s, v))
    return bad


def test_universe_single_source_and_notes():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.channel_links import PLATS
    from core.demo import DEMO_SCAN_PLATS
    ps = list(BROWSER_CHANNELS) + list(APP_CHANNELS)
    assert len(ps) == 10 and len(set(ps)) == 10, ps
    assert set(PLATS) == set(BROWSER_CHANNELS), (PLATS, BROWSER_CHANNELS)
    assert set(DEMO_SCAN_PLATS) == set(ps), (DEMO_SCAN_PLATS, ps)
    p = _payload()
    assert len(p["channels"]) == 10
    assert p["dims"] == ["domestic", "intl", "calendar", "detail", "round_trip", "multi_city", "low_fare"]
    for c in p["channels"]:
        assert set(c["cells"]) == set(p["dims"]), c["plat"]
        assert all(v in ("y", "n", "") for v in c["cells"].values()), c["plat"]
    assert _missing_notes(p) == [], "non-y cells without reason: %s" % _missing_notes(p)[:8]


def test_negative_missing_note_is_caught():
    p = _payload()
    target = next((c, d) for c in p["channels"] for d, v in c["cells"].items() if v != "y")
    c, d = target
    c["dim_notes"][d] = ""
    c["dim_scopes"][d] = ""
    assert _missing_notes(p) != []
    restored = _payload()
    assert _missing_notes(restored) == []


def test_push_names_10_unique():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.alerter import Alerter
    ps = list(BROWSER_CHANNELS) + list(APP_CHANNELS)
    names = [Alerter.plat_cn(p) for p in ps]
    assert all(names), names
    assert len(set(names)) == 10, names


def test_contract_strict_no_n():
    r = subprocess.run([sys.executable, "-m", "core.channel_contract", "--strict"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








def test_demo_site_and_readme_10_channels():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS, CHANNEL_CN
    names = [CHANNEL_CN[p] for p in list(BROWSER_CHANNELS) + list(APP_CHANNELS)]
    site = open(os.path.join(ROOT, "docs", "site", "index.html"), encoding="utf-8").read()
    for n in names:
        assert n in site, "demo site missing %s" % n
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "10 家" in readme or "10 渠道" in readme
    for n in names:
        if " App" in n:
            continue
        assert n in readme, "README missing %s" % n
