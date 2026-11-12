# -*- coding: utf-8 -*-
"""r1063 T226-T227：**通路级耗时落库**（`fetch_paths.elapsed_ms`）。

为什么：今天我用"相邻两条记录的 fetched_at 之差"当单次耗时，误判 `tuniu·PC`
白烧 80 分钟/天（其实那 98 秒大部分是中间穿插的 H5/API）。根因是**没有通路级耗时**：
`path_note(ms=...)` 一直在采，但 `save_fetch_path()` 的 INSERT 没有这一列，落库即丢。

修法：
1. `fetch_paths.elapsed_ms`（建表 + 迁移）；
2. `save_fetch_path(..., ms=0)` 写入，两处调用点从 `rec["ms"]` 传；
3. `path_note` 兜底：没显式给 ms 就用**本实例**上一条记账至今的间隔；
4. `path_reset()` 打起点——否则每次抓取的**第一条**记账还是 0。

真机（重启后）：
```
19:02:16  ctrip      PC        ok    ms=5641
19:02:16  ctrip      PC·周历   empty ms=8689
19:02:46  tongcheng  PC        ok    ms=9613
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()


def test_column_and_insert():
    s = _src("core/storage.py")
    assert "elapsed_ms INTEGER NOT NULL DEFAULT 0" in s, "缺列定义"
    assert '"http_status,rows,note,evidence_level,attempt_id,elapsed_ms)' in s, \
        "INSERT 必须带 elapsed_ms"
    assert "int(ms or 0)))" in s, "参数要写入"


def test_callers_pass_ms():
    m = _src("main.py")
    assert m.count('ms=int(rec.get("ms") or 0)') >= 1
    assert m.count('ms=int(_rec.get("ms") or 0)') >= 1


def test_path_note_fallback_and_start_marker():
    b = _src("crawlers/base.py")
    assert "_ms_fallback" in b or "耗时兜底" in b, "缺兜底逻辑"
    i = b.index("def path_reset")
    assert "_ms_prev" in b[i:i + 600], "path_reset 必须打起点，否则首条记账为 0"


def test_docstring_separates_from_cross_channel_trap():
    """注释里必须写清：同实例内部的间隔 **不等于** 今天踩过的"跨渠道时间差"。"""
    b = _src("crawlers/base.py")
    i = b.index("def path_note")          # 锚在 path_note 里，别命中 path_reset 的注释
    seg = b[i:i + 2600]
    assert "耗时兜底" in seg, "path_note 里应有耗时兜底"
    assert "跨渠道" in seg or "别的通路" in seg, "要把陷阱写清楚，避免后人重犯"
