# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1568_app_fail_evidence.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys

from crawlers.app_base import AppCrawler


# ---- merged from tests/test_r1568_app_fail_evidence.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Dev:
    def __init__(self, xml="<hierarchy/>"):
        self._xml = xml
        self.calls = 0

    def dump(self):
        self.calls += 1
        return self._xml


class _Fake(AppCrawler):
    name = "app_tongcheng"
    PATH_STATUS = {"ok", "timeout", "error", "login", "blocked", "calendar",
                   "paced"}

    def __init__(self, root):
        self.user_data_root = str(root)
        self.paths = []
        self._last_dev = _Dev()
        self._phase_prev = None

    def note_app_stall(self, detail=""):
        pass


def _files(root):
    d = os.path.join(str(root), "app_tongcheng")
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.startswith("app_fail_"))


def test_failure_dumps_evidence(tmp_path):
    c = _Fake(tmp_path)
    c.path_note("app-city", "timeout", detail="设城市超时")
    files = _files(tmp_path)
    assert files, "失败没有留下界面证据（下次还得手工 adb 才查得出原因）"


def test_success_does_not_dump(tmp_path):
    c = _Fake(tmp_path)
    c.path_note("app-city", "ok", rows=3)
    assert not _files(tmp_path), "成功路径不该写 dump（白占设备时间与磁盘）"


def test_evidence_capped_at_six(tmp_path):
    c = _Fake(tmp_path)
    for i in range(9):
        c._phase_prev = None
        c.path_note("app-city", "timeout", detail="第 %d 次" % i)
    files = _files(tmp_path)
    assert len(files) == 6, "dump 没做保留上限：%d 份" % len(files)


def test_dump_names_unique_even_with_frozen_clock(tmp_path, monkeypatch):
    """时钟被冻住时证据文件也不能互相覆盖。

    实测（2026-11-26 Windows）：`datetime.now()` 粒度约 15.6ms，9 次连续
    落盘 2000/2000 次拿到同一个 `%f`，文件名撞车后互相覆盖，保留上限
    从 6 份随机掉到 5 份（并行/串行都会偶发）。唯一性不能只靠时钟。
    """
    import crawlers.app_base as AB
    monkeypatch.setattr(AB, "_dump_stamp",
                        lambda: "20260101_000000_000000")
    c = _Fake(tmp_path)
    for i in range(9):
        c._phase_prev = None
        c.path_note("app-city", "timeout", detail="第 %d 次" % i)
    files = _files(tmp_path)
    assert len(files) == 6, "同一时钟刻度内被覆盖，只剩 %d 份" % len(files)
    assert len(set(files)) == len(files)
