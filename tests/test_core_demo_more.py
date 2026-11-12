# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r681_demo_site_shows_pacing.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import pytest
import sys

from pathlib import Path


# ---- merged from tests/test_r681_demo_site_shows_pacing.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SITE = Path(ROOT) / "docs" / "site" / "index.html"


def _need_site():
    if not SITE.exists() or SITE.stat().st_size < 10000:
        pytest.skip("docs/site/index.html 未烘焙（先跑 tools/demo_build.py）")


def test_bake_covers_pacing_endpoint():
    """源码层：shim 必须拦截 /api/pacing，且烘焙字典带 pacing 载荷。"""
    src = (Path(ROOT) / "tools" / "demo_build.py").read_text(
        encoding="utf-8", errors="replace")
    assert "u.indexOf('/api/pacing')===0" in src, \
        "shim 未拦截 /api/pacing——演示站节流面板会渲染「读取失败」"
    assert '"pacing": webui._demo_pacing_payload()' in src, \
        "烘焙字典没有 pacing 载荷（单源复用 _demo_pacing_payload）"


