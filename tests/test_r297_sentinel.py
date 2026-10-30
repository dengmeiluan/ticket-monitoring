# -*- coding: utf-8 -*-
"""r297 OBS-1 渠道部分断供哨（qsup，TDD 先行；观测立案
_scratch/r297_w2_observe.md §OBS-1）：

渠道行数聚合层按渠道合计观测（zrow/行数塌方/no_det 三面）对
「部分 (route,date) 断供」失明——实录 tuniu 179991 期间 02-13
单查询薄样本在场、其余 3 查询零记录，合计非零整哨静默。qsup 把
观测粒度降到查询级：有记录查询数/启用查询数 <50% 连续 ≥2 轮
WARNING（当日去重、连续 ≥3 日降 INFO、恢复归零，与 zrow 同纪律）；
**全断（0 查询有记录）归 zrow 领地，qsup 不双响**（互斥分工防
同一故障两条告警）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r297_sentinel.py -q
"""
import sys

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

import main as _m  # noqa: E402


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _setup(monkeypatch):
    monkeypatch.setattr(_m, "_QSUP_STREAK", {})
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)


def test_partial_supply_two_rounds_fires_once(monkeypatch):
    """1/4 查询有记录连续 2 轮 → WARNING 恰一次；同日第 3 轮去重；
    streak 持续累计。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel(
        {"tuniu": {"dom": [1, 4]}, "qunar": {"dom": [4, 4]}}, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), \
        "单轮部分断供不报（瞬时风控常态）：" + str(lg.seen)
    _m._channel_partial_sentinel(
        {"tuniu": {"dom": [1, 4]}, "qunar": {"dom": [4, 4]}}, lg)
    hits = [m for lv, m in lg.seen if lv == "W" and "部分断供" in m]
    assert len(hits) == 1 and "tuniu" in hits[0], lg.seen
    assert "1/4" in hits[0], "词面须带查询比率辨识信息：" + hits[0]
    # 同日去重：第 3 轮不再报，streak 继续
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)
    assert sum(1 for lv, m in lg.seen
               if lv == "W" and "部分断供" in m) == 1
    assert _m._QSUP_STREAK.get(("tuniu", "dom")) == 3


def test_full_outage_belongs_to_zrow_not_qsup(monkeypatch):
    """全断（0/4）不开 qsup（zrow 领地，互斥防双响）；streak 不累计。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4]}}, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), lg.seen
    assert _m._QSUP_STREAK.get(("tuniu", "dom"), 0) == 0


def test_boundary_half_supply_no_fire(monkeypatch):
    """2/4=50% 与 3/4 不属部分断供（严格 <50%）；恢复满勤 streak 归零。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [2, 4]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [2, 4]}}, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), lg.seen
    # 恢复满勤 → streak 归零
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [4, 4]}}, lg)
    assert _m._QSUP_STREAK.get(("tuniu", "dom"), 0) == 0


def test_recovery_after_fire_resets(monkeypatch):
    """开火后恢复（≥50%）→ streak 归零，再入部分断供从单轮重新计数。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)
    assert any("部分断供" in m for _lv, m in lg.seen)
    _m._channel_partial_sentinel({"tuniu": {"dom": [3, 4]}}, lg)
    assert _m._QSUP_STREAK.get(("tuniu", "dom"), 0) == 0
    lg.seen.clear()
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), \
        "恢复后重计：单轮不开火"


def test_no_query_channel_skipped(monkeypatch):
    """本轮零查询的渠道（停用/未订阅）跳过评估，不误报。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 0]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 0]}}, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), lg.seen


def test_full_outage_gap_breaks_partial_streak(monkeypatch):
    """部分断供→全断→部分：全断层把部分断供 streak 清零（全断是
    另一 régime，zrow 在管；连续性被断后部分断供须重新累计两轮，
    Soldier r297 Minor-2：隐性接续曾让恢复即火提前一轮）。
    变异验证在案：严格 <50% 变异 ≤50% 被 test_boundary 抓获。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)   # 部分断供 1 轮
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4]}}, lg)   # 转全断（zrow 领地）
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)   # 回到部分：重新计 1
    assert not any("部分断供" in m for _lv, m in lg.seen), \
        "全断层未清 streak，恢复即火提前：" + str(lg.seen)
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4]}}, lg)   # 第 2 轮才火
    assert any("部分断供" in m for _lv, m in lg.seen)
