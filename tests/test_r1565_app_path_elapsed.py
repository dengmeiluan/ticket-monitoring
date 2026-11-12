# -*- coding: utf-8 -*-
"""r1565：App 渠道的分段耗时不再恒为 0（否则「速度/p95」对 App 永远空白）。

现场：app_tongcheng 30 条通路记录 `elapsed_ms` 全是 0，而日志里每次实跑
30–60 秒。`path_note` 有 ms 参数但绝大多数调用点不传 → 台账没有耗时样本，
三率一险的速度口径对 App 渠道不可算。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402


class _Fake(AppCrawler):
    name = "app_ctrip"
    PATH_STATUS = {"ok", "timeout", "error", "login", "blocked", "calendar",
                   "paced"}

    def __init__(self):
        self.user_data_root = "user_data"
        self.paths = []

    def note_app_stall(self, detail=""):
        pass


def test_ms_derived_from_previous_phase_when_not_passed():
    c = _Fake()
    c.path_note("app-login", "ok")          # 第一拍：只有起点
    fake_prev = ("app-login", time.time() - 12.0)
    c._phase_prev = fake_prev
    c.path_note("app-list", "timeout")      # 第二拍：应带上 ~12s
    rec = c.paths[-1]
    assert rec["ms"] > 10_000, (
        "App 通路耗时没被补上（ms=%s）——三率一险的速度口径会永远空白"
        % rec["ms"])
    assert rec["ms"] < 20_000, rec["ms"]


def test_no_previous_phase_means_no_invented_ms():
    c = _Fake()
    c._phase_prev = None
    c.path_note("app-login", "timeout")
    assert c.paths[-1]["ms"] == 0, (
        "没有上一拍时不许凭空造耗时：%s" % c.paths[-1])


def test_explicit_ms_wins():
    c = _Fake()
    c._phase_prev = ("app-login", time.time() - 9.0)
    c.path_note("app-list", "ok", ms=1234)
    assert c.paths[-1]["ms"] == 1234, c.paths[-1]
