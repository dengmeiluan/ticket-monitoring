# -*- coding: utf-8 -*-
"""r1063 T75：账本要能回答「为什么失败」。

真实取证（飞猪 App，2026-11-08 10:14 / 10:20 两次真机运行）：

| 路径 | 状态 | 原因 |
|---|---|---|
| `app-block` | blocked | 飞猪返回「访问被拒绝」安全页；需人工处理 |
| `app-form`  | timeout | 首页点机票后未到 Flutter 表单 |

修复前账本只留 `st={'blocked': 1}` —— **"被什么挡"彻底丢了**，仪表上只能
看出"失败过一次"，看不出"要人去点一下"还是"我们点错了地方"。
"""
import json
import os
import tempfile

from core.yield_stats import YieldLedger


def _ledger():
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "y.json")
    return YieldLedger(p), p


def test_reason_is_persisted():
    led, path = _ledger()
    led.note("plat", "app-block", False, status="blocked",
             detail="飞猪返回「访问被拒绝」安全页；需人工处理")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["app-block"]
    assert rec["why"].startswith("飞猪返回「访问被拒绝」"), rec
    assert rec["st"] == {"blocked": 1}


def test_reason_is_truncated():
    led, path = _ledger()
    led.note("plat", "p", False, status="error", detail="x" * 500)
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert len(rec["why"]) == 120


def test_reason_keeps_only_the_latest():
    led, path = _ledger()
    led.note("plat", "p", False, status="blocked", detail="第一次：安全页")
    led.note("plat", "p", False, status="timeout", detail="第二次：表单没到")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert rec["why"] == "第二次：表单没到"
    assert rec["st"] == {"blocked": 1, "timeout": 1}, "直方图仍要累计"


def test_no_detail_does_not_invent_one():
    led, path = _ledger()
    led.note("plat", "p", True, rows=2, status="ok")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert "why" not in rec, "没给原因就不要编一个"


def test_old_ledger_without_why_still_reads(tmp_path=None):
    """老账本没有 `why` 键——读侧必须 .get 兜底，不许炸。"""
    led, path = _ledger()
    led.note("plat", "p", False, status="error")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert rec.get("why", "") == ""
