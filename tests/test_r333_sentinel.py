# -*- coding: utf-8 -*-
"""r333 域级全断哨（zdom）：qsup 让渡分支的盲区根治。

实录（observe r333 备案①）：tuniu dom 10-14 起断供、intl 10-18 恢复
——zrow 输入=平台合计行数（intl 出数即合计>0 恒静默）、qsup 对
sup=0 让渡 zrow（域级全断无人评估）→ dom 断供 5 天零告警。

修法：qsup 的 sup<=0 分支拆域级全断评估，两道门防误报——
①防双响门：平台内任一其他域有记录才归本哨（全平台零记录=zrow 领地，
  哨词面与本哨天然互斥，不双响）；
②供给基线门：该域本轮进程内曾见 sup>0 才评估（窗口诞生起恒零=
  tongcheng intl 结构性零载体形态，静默——判例卅二§1 窗粒度供给
  基线）。恢复出数（sup>0）即 streak 归零+基线记位。"""

import os
import sys

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

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
