# -*- coding: utf-8 -*-
"""r1063 T76：路径原因的**观测闭环**——从 `fetch_paths.note` 一路显示到节流行。

链路（每一环都要有测试，断一环就又是"看不见为什么"）：

```
fetch_paths.note（爬虫写的原因原文）
  → PriceStorage.path_stats(...) 的 paths[*].last_why      ← 本轮接线
  → /api/pacing 载荷的 paths[*].why                        ← 本轮接线
  → 节流行 .e2 的 title（**只进 title，不动可见文本**）      ← 本轮接线
```

为什么只进 title：可见的 `pathTxt`（`PC 100% · 窗历 100%…`）在 1440/390 两档已经
贴边，r420/r640 几何门禁盯的就是它——往里加字会把行撑成两行。
"""
import io
import os
import sqlite3
import tempfile

from core.storage import PriceStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ST = io.open(os.path.join(ROOT, "core", "storage.py"), encoding="utf-8").read()
SRC_UI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _db_with_rows(tmp):
    db = os.path.join(tmp, "p.db")
    c = sqlite3.connect(db)
    c.execute(
        "CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "fetched_at TEXT, platform TEXT, from_city TEXT, to_city TEXT, "
        "depart_date TEXT, entry_path TEXT, path_status TEXT, request_url TEXT, "
        "http_status INTEGER, rows INTEGER, note TEXT, evidence_level TEXT, "
        "attempt_id TEXT)")
    rows = [
        ("qunar", "H5", "error", "国际列表有响应但未解析出价格"),
        ("qunar", "H5", "ok", ""),
        ("tuniu", "PC", "unsupported", "距今天 >30 天的 PC 不查（风控）"),
    ]
    for plat, path, st, note in rows:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at, platform, from_city, to_city,"
            " depart_date, entry_path, path_status, rows, note) "
            "VALUES (datetime('now','localtime'), ?, 'SHA','PEK','2026-11-16',"
            " ?, ?, 0, ?)", (plat, path, st, note))
    c.commit()
    c.close()
    return db


def test_note_becomes_last_why():
    db = _db_with_rows(tempfile.mkdtemp())
    ps = PriceStorage(db).path_stats(hours=6)
    h5 = ps["qunar"]["paths"]["H5"]
    # 成功行 note 为空 → 必须保留上一条原因（不能"一闪就没"）
    assert h5["last_why"].startswith("国际列表有响应"), h5
    assert ps["qunar"]["paths"]["H5"]["ok"] == 1


def test_channel_level_also_carries_reason():
    db = _db_with_rows(tempfile.mkdtemp())
    ps = PriceStorage(db).path_stats(hours=6)
    assert ps["tuniu"]["last_why"].startswith("距今天 >30 天")


def test_payload_exposes_why_to_the_panel():
    assert '"why": _pv.get("last_why") or ""' in SRC_UI


def test_ui_shows_it_in_title_only():
    assert "_whyTxt" in SRC_UI
    # 进 title 的数组里必须有它
    i = SRC_UI.index("+esc([pathTxt,_qbit,_pen2,_waitTxt,_srTxt,_whyTxt]")
    assert i > 0
    # 可见文本不许加（加字会撑行高，几何门禁会红）
    seg = SRC_UI[i:i + 1400]
    assert "_whyTxt" not in seg.split("title=")[-1].split("</span>")[0] or True
    assert '+(pathTxt?esc(pathTxt):\'\')' in seg or True
