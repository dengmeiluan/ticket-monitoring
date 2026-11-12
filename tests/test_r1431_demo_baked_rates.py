# -*- coding: utf-8 -*-
"""r1431：烘焙演示站的三率一险必须是**合成数据**，不能是空表。

背景：`docs/demo_build.py` 原先烘焙的是 `core.rates.snapshot()`——它读**真库**。
在没有账本的机器/CI 上烘出来是空表，于是公开演示页（GitHub Pages）的
「三率一险」卡片永远是空壳；而 demo 服务器那条同源 bug 已在 r1421 用
`core.rates.demo_snapshot()` 修好，烘焙侧漏了同一个修。

契约：
1. 烘焙 JSON 里 `rates` 必须 `ok/demo` 为真且有行；
2. 每行要带渠道与通路（页面靠它渲渠道图标与中文通路名）；
3. 烘焙源必须调用 `demo_snapshot`（不许再回头读真库）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "docs", "site", "index.html")


def _site():
    assert os.path.isfile(SITE), "缺少烘焙站（先跑 python docs/demo_build.py）"
    return io.open(SITE, encoding="utf-8", errors="replace").read()


def test_baked_rates_are_demo_and_non_empty():
    s = _site()
    assert '"rates": {"ok": true, "demo": true' in s, \
        "烘焙站的三率不是演示合成数据（公开演示页会显示空表）"
    assert '"by_path": [{"plat":' in s, "烘焙站的三率没有行"


def test_bake_uses_demo_snapshot_not_real_db():
    src = io.open(os.path.join(ROOT, "docs", "demo_build.py"),
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
