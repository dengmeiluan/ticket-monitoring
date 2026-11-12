# -*- coding: utf-8 -*-
"""r735 飞猪 H5 收到 ret_date 却静默按单程采 —— 会串味成「往返总价」。

用户原话：「主要原⑤渠道的 PC 和 H5 都要重点检查实现」。

现状：飞猪 PC 与 H5 是**两套会话、两个采集器**（`FliggyCrawler` /
`FliggyH5Crawler`），但 `CHANNEL_DIMENSIONS` 只有一行 `fliggy`，其中
`round_trip: y` 描述的是 **PC** 的能力。而 `FliggyH5Crawler.fetch` 的签名
收 `ret_date`，函数体里**一次都没用**——传了返程日，它照常跑单程，
返回的 price 是单程价。

下游（告警/走势/列表池）只看 `price` 与 `tripType`：把单程价当往返总价
写进去，就会出现凭空的价差与错误报警。本项目对这类「静默换口径」的处置
一贯是：**要么真做，要么显式 unsupported 落账，绝不假装**。

判据（与 ctrip / tuniu / app_base 同律）：
  * 传 ret_date 时**不得**发起单程查询；
  * 必须写一条 status=unsupported 的 path_note；
  * 返回空列表。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.fliggy_h5 import FliggyH5Crawler  # noqa: E402


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
                   encoding="utf-8").read()


def _body_of_fetch():
    src = _src()
    i = src.index("def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_fetch_body_does_not_ignore_ret_date():
    """守卫：函数体里必须出现 ret_date 的显式处置（不能只写在签名上）。"""
    body = _body_of_fetch()
    assert "ret_date" in body.split(":", 1)[1], (
        "FliggyH5Crawler.fetch 的签名收了 ret_date，函数体却没用——"
        "传返程日会被静默当成单程，单程价冒充往返总价")


def test_round_trip_is_recorded_as_unsupported(tmp_path, monkeypatch):
    """行为：传 ret_date → 不查单程、落 unsupported、返回空。"""
    inst = FliggyH5Crawler({"user_data_dir": str(tmp_path)},
                         __import__("logging").getLogger("t"))
    called = []

    def _boom(*a, **k):
        called.append(a)
        raise AssertionError("不该发起单程查询")

    monkeypatch.setattr(inst, "_fetch_one", _boom)
    # 会话文件不存在也要先走到 ret_date 判断（否则测不到守卫）
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], rows
    assert called == [], "往返请求仍然发起了单程查询"
    st = [p for p in (inst.paths or []) if p.get("status") == "unsupported"]
    assert st, "没有把「往返不支持」落账：%s" % (inst.paths,)
    assert "往返" in str(st[0].get("detail") or "")


def test_oneway_still_works(tmp_path, monkeypatch):
    """负控：不传 ret_date 时照常按单程走（别把单程也拦掉）。"""
    inst = FliggyH5Crawler({"user_data_dir": str(tmp_path)},
                         __import__("logging").getLogger("t"))
    seen = []

    def _fake(fc, tc, date):
        seen.append(date)
        return []

    monkeypatch.setattr(inst, "_fetch_one", _fake)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    inst.fetch("SHA", "BJS", ["2026-11-20"])
    assert seen == ["2026-11-20"], seen
