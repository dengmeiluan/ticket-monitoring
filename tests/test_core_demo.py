# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1431_demo_baked_rates.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os


# ---- merged from tests/test_r1431_demo_baked_rates.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "docs", "site", "index.html")


def _site():
    assert os.path.isfile(SITE), "缺少烘焙站（先跑 python tools/demo_build.py）"
    return io.open(SITE, encoding="utf-8", errors="replace").read()


def test_baked_rates_are_demo_and_non_empty():
    s = _site()
    assert '"rates": {"ok": true, "demo": true' in s, \
        "烘焙站的三率不是演示合成数据（公开演示页会显示空表）"
    assert '"by_path": [{"plat":' in s, "烘焙站的三率没有行"


def test_bake_uses_demo_snapshot_not_real_db():
    src = io.open(os.path.join(ROOT, "tools", "demo_build.py"),
                  encoding="utf-8").read()
    assert "_rates.demo_snapshot(" in src, "烘焙源没走 demo_snapshot"
    assert "_rates.snapshot(" not in src, \
        "烘焙源又回去读真库了（干净环境会烘出空表）"


def test_demo_snapshot_shape_matches_snapshot():
    """合成快照必须与真快照同结构，否则页面渲染会缺字段。"""
    import sys
    sys.path.insert(0, ROOT)
    from core import rates
    d = rates.demo_snapshot(hours=12)
    for k in ("ok", "demo", "hours", "kinds", "by_path", "by_plat", "totals"):
        assert k in d, "缺字段 %s" % k
    assert d["ok"] is True and d["demo"] is True
    assert len(d["by_path"]) >= 5, d["by_path"]
    row = d["by_path"][0]
    for k in ("plat", "path", "attempts", "ok_n", "rows", "yield", "eff",
              "p95_ms", "risk"):
        assert k in row, "行缺字段 %s" % k
    assert d["totals"]["attempts"] == sum(r["attempts"] for r in d["by_path"])
    assert d["totals"]["rows"] == sum(r["rows"] for r in d["by_path"])
