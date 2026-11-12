# -*- coding: utf-8 -*-
"""r1568：App 段失败必须留界面证据（否则账本只剩一行「113652ms timeout」）。

来源：2026-11-11 同程 App 连续 app-city 超时。账本看不出屏上是什么，
只能手工 adb 截图才发现前台是 `ctrip.android.view`（携程系共享机票模块）。
本门禁守：失败落 dump、成功不落、每渠道最多 6 份。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402


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
