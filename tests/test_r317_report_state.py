# -*- coding: utf-8 -*-
"""r317 推送 P2-1（TDD 先行，审校报告 _scratch/r317_push_review.md）：

日报防重发落账读-改-写非原子 + 无写入方审计——10-13 实发同文日报
两份（09:01:27 落账 INFO 与 14:04:13 重推双证在账，state 键丢失即
重推）。三件修复（零重试语义零改动）：
1. 原子写：tmp+os.replace——写中崩溃不留半截 JSON，旧 state 完好；
2. 账本交叉校验：state 键丢失但账本已有今日日报「已推两态」（成功
   ok=True / 幽灵 ok=False+errcode=-1，与 state 落账语义精确同构）
   → 补写 state 不重推；网络异常（ok=False 无 errcode）不拦截，
   下轮重试语义保留；
3. state 路径环境变量锚 REPORT_STATE_FILE（与 PUSH_HISTORY_FILE
   同构）：conftest autouse 重定向，测试合成态永不落生产 data/。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r317_report_state.py
"""
import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import report


_TITLE_ANCHOR = "价格走势与明细"


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """state 与账本双重定向出仓库（生产 data/ 零触碰）。"""
    monkeypatch.setenv("REPORT_STATE_FILE", str(tmp_path / "report_state.json"))
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "push_history.jsonl"))
    return tmp_path


def _cfg():
    return {"users": [{"name": "日报演练",
                       "notifier": {"report_hour": 0, "digest": True},
                       "routes": []}]}


def _log():
    return logging.getLogger("r317_report_state")


def _notifier():
    class _N:
        last_errcode = None
    return _N()


def _ledger_line(ok, errcode=None, ch="dingtalk"):
    from datetime import datetime
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "ok": ok, "ch": ch,
           "title": "📈 %s｜%s" % (_TITLE_ANCHOR,
                                   datetime.now().strftime("%m/%d %H:%M")),
           "desp": "日报演练"}
    if errcode is not None:
        rec["errcode"] = errcode
    return json.dumps(rec, ensure_ascii=False)


def test_state_write_survives_midwrite_crash(iso, monkeypatch):
    """写中崩溃（序列化抛异常）旧 state 完好——tmp+os.replace 原子写；
    直接 open("w") 截断实现下旧 state 被毁=同文重推窗口。"""
    sp = iso / "report_state.json"
    sp.write_text(json.dumps({"日报演练": "2000-01-01"}),
                  encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    real_dump = json.dump

    def _boom(*a, **kw):
        raise OSError("模拟写中崩溃")

    monkeypatch.setattr(report.json, "dump", _boom)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    monkeypatch.setattr(report.json, "dump", real_dump)
    # 旧 state 完好（写中崩溃不毁既有落账）
    got = json.loads(sp.read_text(encoding="utf-8"))
    assert got.get("日报演练") == "2000-01-01", (
        "写中崩溃毁掉旧 state（同文重推窗口）： got=%r" % got)


def test_ledger_crosscheck_blocks_repush_when_state_lost(iso, monkeypatch):
    """state 键丢失但账本已有今日成功日报 → 补写 state 不重推。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(True) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 0, (
        "state 丢失且账本已有今日日报仍重推（10-13 双份日报形态）")
    sp = iso / "report_state.json"
    assert sp.exists(), "账本兜底路径未补写 state（明日防重发失锚）"
    got = json.loads(sp.read_text(encoding="utf-8"))
    from datetime import datetime
    assert got.get("日报演练") == datetime.now().strftime("%Y-%m-%d")


def test_ledger_ghost_minus1_counts_as_pushed(iso, monkeypatch):
    """账本今日 -1 幽灵行（ok=False+errcode=-1）=已推两态之一 → 不重推
    （与「-1 幽灵按已推落账」守卫语义精确同构）。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(False, errcode=-1) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 0, "账本 -1 幽灵行未按已推拦截，重推同文日报"


def test_ledger_network_err_keeps_retry(iso, monkeypatch):
    """账本今日网络异常行（ok=False 无 errcode）≠已推 → 正常重试语义
    保留（防交叉校验过度拦截「防丢失由下轮自然补」路径）。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(False) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 1, "网络异常行被误判已推，丢失了重试语义"


def test_multiuser_ledger_check_disabled(iso, monkeypatch):
    """Soldier M1：账本行无 user 维度——≥2 用户时校验诚实禁用，
    第二用户的日报不被首用户的账本行误吞。"""
    cfg = {"users": [
        {"name": "甲", "notifier": {"report_hour": 0, "digest": True},
         "routes": []},
        {"name": "乙", "notifier": {"report_hour": 0, "digest": True},
         "routes": []}]}
    (iso / "push_history.jsonl").write_text(
        _ledger_line(True) + "\n", encoding="utf-8")
    seen = []

    def _fake_push(cfg, logger, notifier, user=""):
        seen.append(user)
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(cfg, _log(), _notifier(), user="乙")
    assert seen == ["乙"], "多用户下账本行误吞了第二用户的日报：seen=%r" % seen


def test_state_hit_skips_ledger_scan(iso, monkeypatch):
    """Soldier m1：state 命中短路在先——稳态命中不扫账本
    （每轮白扫 4160 行 + 重写 state + INFO 刷屏的次优序退役）。"""
    from datetime import datetime
    sp = iso / "report_state.json"
    sp.write_text(json.dumps(
        {"日报演练": datetime.now().strftime("%Y-%m-%d")}), encoding="utf-8")
    scanned = {"n": 0}
    real = report._ledger_has_today_report

    def _spy(today):
        scanned["n"] += 1
        return real(today)

    monkeypatch.setattr(report, "_ledger_has_today_report", _spy)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert scanned["n"] == 0, "state 命中仍扫账本（次优序未退役）"
