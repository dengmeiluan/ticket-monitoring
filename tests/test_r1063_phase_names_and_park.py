# -*- coding: utf-8 -*-
"""r1063 T78：分段读数自洽 + 收尾提速（真机实测）。

真机（智行 10.26.2，SHA→PEK，整轮 **42.5s**，2026-11-08 10:45）：

| 阶段 | 耗时 |
|---|---|
| 耗时·运行时 | 1.5s |
| 耗时·前置 | 8.3s |
| 耗时·日历 | 7.6s（打开 5.5 + 等价 2.1）|
| 日历（路径账口径：emit + 进明细） | 12.4s |
| 耗时·明细 | 12.4s |
| 耗时·收尾 | **5.5s**（改前 8–10s）|

两条经验：

1. **阶段名不能与路径名同名**。"日历" 既是路径名又是阶段名，而 `path_note`
   的自动打点会把"两条账之间的间隔"记到上一条账的名字上 → 两个来源汇进
   同一个桶，出现「外层 20.3s、内部子段只有 7.8s」这种自相矛盾的读数。
   现在手动打点统一 `耗时·xxx` 前缀，一眼分得清。
2. **收尾可以更快**：成功拿到明细后 App 停在列表页，按**一次** BACK 就回首页，
   不必走"点 Tab + 最多 8×(2.5s+dump)"的轮询。实测 8–10s → 5.5s。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
              encoding="utf-8").read()


def test_manual_phases_are_namespaced():
    """手动打点必须带 `耗时·` 前缀（与路径名隔离，否则读数自相矛盾）。"""
    for name in ("耗时·运行时", "耗时·前置", "耗时·日历", "耗时·明细",
                 "耗时·收尾"):
        assert 'self.timed("%s")' % name in SRC, name
    # 不许再出现裸的 `self.timed("日历")`（会与路径账同名）
    assert 'self.timed("日历")' not in SRC


def test_calendar_subphases_are_separate():
    assert 'self.timed("耗时·日历·打开")' in SRC
    assert 'self.timed("耗时·日历·等价")' in SRC


def test_park_has_single_back_fast_path():
    """收尾快路径：一次 BACK 就回首页，失败再走既有梯子。"""
    i = SRC.index("def _park_at_home")
    seg = SRC[i:i + 2600]
    assert "单次 BACK 快路径" in seg
    assert 'dev.keyevent("KEYCODE_BACK")' in seg
    assert "一次 BACK 已回首页" in seg
    # 既有梯子必须仍在（快路径失败要能兜住）
    assert 'find(nodes(xml), "机票")' in seg


def test_back_fast_path_returns_before_tab_loop():
    """顺序必须是「先 BACK 判首页」→ 再 Tab 轮询，不能反。"""
    i = SRC.index("def _park_at_home")
    seg = SRC[i:i + 2600]
    assert seg.index("单次 BACK 快路径") < seg.index('find(nodes(xml), "机票")')
