# -*- coding: utf-8 -*-
"""r1824：`paced`（我方主动跳过）不许算成 error，也不许进成功率分母。

账本里 `paced` 是节流/TTL 跳过——**我们主动不发**，不是渠道出错。
`bump()` 原来把它落到 `else: node["error"] += 1`，于是：
- 健诊错误率被抬高；
- rate / rate_excl_empty 被拖低。

同时 `/api/three-rates` 的分母（r1822）也要剔除 unsupported/paced/skipped。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rates  # noqa: E402


def test_rates_skip_statuses_defined():
    assert rates.SKIP_STATUSES == ("unsupported", "paced", "skipped")


def test_snapshot_excludes_skips_from_denominator():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "rates.py"),
        encoding="utf-8").read()
    i = src.index("def snapshot(")
    seg = src[i:i + 3000]
    assert "path_status in (%s)" in seg, "没有把跳过状态单列统计"
    assert "max(0, _rec - _sk)" in seg, "分母没有扣除跳过"
    assert '"skipped_n"' in seg, "没有把剔掉多少条报出来"


def test_storage_counts_paced_separately():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "storage.py"),
        encoding="utf-8").read()
    i = src.index("def bump(node, status, last)")
    seg = src[i:i + 3000]
    assert 'elif status in ("paced", "skipped")' in seg, "paced 没有单列分支"
    assert 'node["paced"]' in seg, "没有 paced 计数"
    # error 分支必须还在（真故障仍要记）
    assert 'node["error"] += 1' in seg
