# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1130_wave4_channel_surfaces.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r1130_wave4_channel_surfaces.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EXPECTED = ["ctrip", "qunar", "fliggy", "tongcheng", "tuniu",
            "app_zhixing", "app_qunar", "app_fliggy", "app_ctrip", "app_tongcheng"]
CN = ["携程", "去哪儿", "飞猪", "同程", "途牛",
      "智行 App", "去哪儿 App", "飞猪 App", "携程 App", "同程 App"]


def test_source_universe_is_10():
    from core.channels import BROWSER_CHANNELS, APP_CHANNELS
    from core.channel_links import PLATS
    assert set(BROWSER_CHANNELS) | set(APP_CHANNELS) == set(EXPECTED)
    assert set(PLATS) == set(BROWSER_CHANNELS)  # App 无网页入口，业务上不适用


def test_specials_push_export_demo_and_docs_cover_10():
    from core.specials import SPECIAL_CAPABILITY
    from core.demo import DEMO_SCAN_PLATS
    from core.alerter import Alerter
    assert sorted(SPECIAL_CAPABILITY) == sorted(EXPECTED)
    assert set(DEMO_SCAN_PLATS) == set(EXPECTED)
    for p, n in zip(EXPECTED, CN):
        assert Alerter.plat_cn(p) == n
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "'渠道'" in src and "f.plat" in src, "CSV 导出缺渠道列"
    for path in ("README.md", "README_EN.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            txt = f.read()
        assert "10" in txt
    with open(os.path.join(ROOT, "docs", "site", "index.html"), encoding="utf-8") as f:
        site = f.read()
    for n in CN:
        assert n in site, ("演示站缺渠道", n)


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




BASE = None


