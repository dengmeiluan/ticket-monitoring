# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r333_sentinel.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import main as _m
import os
import sys


# ---- merged from tests/test_r333_sentinel.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _setup(monkeypatch):
    monkeypatch.setattr(_m, "_QSUP_STREAK", {})
    monkeypatch.setattr(_m, "_DOMZERO_STREAK", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)


def test_zdom_partial_platform_fires_with_domain_word(monkeypatch):
    """tuniu 实录形态：dom 先满勤（记供给基线）后断供、intl 出数
    → 域级哨连续 2 轮 WARNING，词面带「国内窗」+「零记录」辨识。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [4, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    assert not any("零记录" in m and "国内窗" in m for _lv, m in lg.seen), \
        "断供首轮不报（瞬时风控常态）：" + str(lg.seen)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    hits = [m for lv, m in lg.seen if lv == "W" and "零记录" in m
            and "国内窗" in m]
    assert len(hits) == 1, lg.seen
    assert "tuniu" in hits[0], hits[0]
    assert _m._DOMZERO_STREAK.get(("tuniu", "dom")) == 2


def test_zdom_platform_total_zero_delegates_zrow(monkeypatch):
    """全平台零记录（dom+intl 双零）→ 域级哨静默（zrow 领地，防同一
    故障两条告警的双响）。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [4, 4], "intl": [2, 2]}}, lg)
    sup = {"tuniu": {"dom": [0, 4], "intl": [0, 2]}}
    for _ in range(3):
        _m._channel_partial_sentinel(sup, lg)
    assert _m._DOMZERO_STREAK.get(("tuniu", "dom"), 0) == 0, \
        "全平台零记录不得累计域级 streak"
    assert _m._DOMZERO_STREAK.get(("tuniu", "intl"), 0) == 0
    assert not any("零记录" in m for _lv, m in lg.seen), lg.seen


def test_zdom_never_supplied_structural_silent(monkeypatch):
    """tongcheng 结构零形态：intl 窗口诞生起恒零（本进程从未见
    sup>0）→ 静默，不得因 dom 满勤而误报结构性零载体。"""
    _setup(monkeypatch)
    lg = _L()
    sup = {"tongcheng": {"dom": [4, 4], "intl": [0, 20]}}
    for _ in range(3):
        _m._channel_partial_sentinel(sup, lg)
    assert _m._DOMZERO_STREAK.get(("tongcheng", "intl"), 0) == 0
    assert not any("零记录" in m for _lv, m in lg.seen), lg.seen


def test_zdom_recovery_resets_streak(monkeypatch):
    """断供告警后恢复出数 → streak 归零、再断重新累计（连续语义
    不跨恢复段接续）。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [4, 4], "intl": [2, 2]}}, lg)
    down = {"tuniu": {"dom": [0, 4], "intl": [2, 2]}}
    _m._channel_partial_sentinel(down, lg)
    _m._channel_partial_sentinel(down, lg)
    assert _m._DOMZERO_STREAK.get(("tuniu", "dom")) == 2
    _m._channel_partial_sentinel(
        {"tuniu": {"dom": [4, 4], "intl": [2, 2]}}, lg)
    assert _m._DOMZERO_STREAK.get(("tuniu", "dom"), 0) == 0, \
        "恢复出数即归零"
    assert not any("零记录" in m and "国内窗" in m
                   for lv, m in lg.seen if lv == "I"), lg.seen


def test_zdom_partial_supply_round_breaks_streak(monkeypatch):
    """拍手形态（Soldier P2-1）：零→1/4→零——中间轮实有记录，
    「连续 2 轮零记录」词面不得触发（与 zrow 同纪律：任一轮有记录
    即清零连续，词面与事实一致）。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [4, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    assert _m._DOMZERO_STREAK.get(("tuniu", "dom"), 0) <= 1, \
        "部分供给轮必须打断连续累计"
    hits = [m for lv, m in lg.seen if lv == "W" and "零记录" in m]
    assert not hits, "拍手形态不得产「连续 2 轮」假词面：" + str(hits)


def test_zdom_partial_supply_counts_as_supplied(monkeypatch):
    """薄样本供给（0<sup<tot）也算「曾供给」——部分断供期间渠道仍
    活着，随后整域断供须能评估（基线门不把薄供给误判为结构零）。"""
    _setup(monkeypatch)
    lg = _L()
    _m._channel_partial_sentinel({"tuniu": {"dom": [1, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    _m._channel_partial_sentinel({"tuniu": {"dom": [0, 4], "intl": [2, 2]}}, lg)
    hits = [m for lv, m in lg.seen if lv == "W" and "零记录" in m
            and "国内窗" in m]
    assert len(hits) == 1, lg.seen
