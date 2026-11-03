# -*- coding: utf-8 -*-
"""r917：App 渠道的**单日隔离**——一天失败不许拖垮整段。

背景：ctrip / 同程 / 飞猪 / 智行的日期循环原本是

    for date in dates:
        got = self._one_date(dev, ..., date)     # ← 一抛异常，整个 fetch 结束

于是「第 2 天设备抖了一下」会让第 3、4、5 天一起丢，账本上表现为整条航线
timeout，而实际只有 1 天有问题。这直接压爬取率。

钉住四件事：
  1. 异常日**只记这一天**，且记 timeout（绝不记 empty）；
  2. 其余日期照常出数；
  3. 返回元组的渠道（智行 `(rows, blocked)`）契约不变；
  4. 成功路径原样返回，不额外记账。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r917_date_isolation.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_base import AppCrawler  # noqa: E402

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
