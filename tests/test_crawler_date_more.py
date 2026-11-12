# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r917_date_isolation.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import sys

from crawlers.app_base import AppCrawler


# ---- merged from tests/test_r917_date_isolation.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r917")


def _crawler(tmp_path, name="ctrip"):
    class _C(AppCrawler):
        pass
    _C.name = name
    _C.package = "ctrip.android.view"
    return _C({"user_data_dir": str(tmp_path)}, _LOG)


# ---------------------------------------------------------------------------
# 1. date_guard 本体
# ---------------------------------------------------------------------------
def test_date_guard_passes_through_on_success(tmp_path):
    c = _crawler(tmp_path)
    assert c.date_guard("2026-11-16", lambda: ["row"]) == ["row"]
    assert c.paths == []                    # 成功不额外记账


def test_date_guard_catches_and_records_timeout(tmp_path):
    c = _crawler(tmp_path)

    def _boom():
        raise RuntimeError("uiautomator 卡死")
    got = c.date_guard("2026-11-16", _boom)
    assert got == []
    assert len(c.paths) == 1
    rec = c.paths[0]
    assert rec["date"] == "2026-11-16"
    assert rec["status"] == "timeout"        # 不是 empty！
    assert "uiautomator" in rec["detail"] or "RuntimeError" in rec["detail"]


def test_date_guard_never_records_empty(tmp_path):
    """异常不能被记成 empty——那是账本红线（"没采到" ≠ "没票"）。"""
    c = _crawler(tmp_path)

    def _boom():
        raise ValueError("x")
    c.date_guard("2026-11-16", _boom)
    assert [p["status"] for p in c.paths] == ["timeout"]
    assert "empty" not in [p["status"] for p in c.paths]


def test_date_guard_default_for_tuple_channels(tmp_path):
    """智行返回 (rows, blocked)：异常时必须回到 ([], None)，调用方解包不变。"""
    c = _crawler(tmp_path, "app_zhixing")

    def _boom():
        raise RuntimeError("boom")
    rows, block = c.date_guard("2026-11-16", _boom, _default=([], None))
    assert rows == [] and block is None
    assert [p["status"] for p in c.paths] == ["timeout"]


def test_date_guard_passes_positional_and_kwargs(tmp_path):
    c = _crawler(tmp_path)
    seen = {}

    def _fn(dev, date, first=False):
        seen.update(dev=dev, date=date, first=first)
        return [1]
    assert c.date_guard("2026-11-16", _fn, "DEV", "2026-11-16", first=True) == [1]
    assert seen == {"dev": "DEV", "date": "2026-11-16", "first": True}


# ---------------------------------------------------------------------------
# 2. 接线：模拟 ctrip / 同程 / 飞猪 的三日循环
# ---------------------------------------------------------------------------
class _FakeChannel(AppCrawler):
    """按 ctrip 的循环形状复刻（date_guard 包住 _one_date）。"""
    name = "ctrip"
    package = "ctrip.android.view"

    def __init__(self, config, logger, bad_date=""):
        super().__init__(config, logger)
        self.bad_date = bad_date
        self.called = []

    def _one_date(self, dev, fc, tc, date):
        self.called.append(date)
        if date == self.bad_date:
            raise RuntimeError("设备抖了一下")
        return [{"price": 100, "depDate": date}]

    def fetch(self, fc, tc, dates, ret_date=""):
        out = []
        for date in dates:
            got = self.date_guard(date, self._one_date, None, fc, tc, date)
            if got:
                out.append(got)
        return [x for group in out for x in group]


def test_middle_date_failure_does_not_lose_the_rest(tmp_path):
    c = _FakeChannel({"user_data_dir": str(tmp_path)}, _LOG,
                     bad_date="2026-11-17")
    got = c.fetch("SHA", "NRT", ["2026-11-16", "2026-11-17", "2026-11-18"])
    # 第 2 天炸了，但第 1、3 天照常出数
    assert [r["depDate"] for r in got] == ["2026-11-16", "2026-11-18"]
    # 三天都被真正尝试过（没有提前退出）
    assert c.called == ["2026-11-16", "2026-11-17", "2026-11-18"]
    # 只有失败那天入账，且是 timeout
    assert len(c.paths) == 1
    assert c.paths[0]["date"] == "2026-11-17"
    assert c.paths[0]["status"] == "timeout"


def test_all_dates_failing_still_returns_empty_and_records_each(tmp_path):
    class _AllBad(_FakeChannel):
        def _one_date(self, dev, fc, tc, date):
            self.called.append(date)
            raise RuntimeError("boom")
    c = _AllBad({"user_data_dir": str(tmp_path)}, _LOG)
    assert c.fetch("SHA", "NRT", ["2026-11-16", "2026-11-17"]) == []
    assert len(c.called) == 2
    assert [p["status"] for p in c.paths] == ["timeout", "timeout"]
    assert [p["date"] for p in c.paths] == ["2026-11-16", "2026-11-17"]
