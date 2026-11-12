# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r330_sentinel.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import main as _m
import sys

from types import SimpleNamespace as _NS


# ---- merged from tests/test_r330_sentinel.py ----

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _setup(monkeypatch, tmp_path=None):
    monkeypatch.setattr(_m, "_QSUP_STREAK", {})
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)
    if tmp_path is not None:
        monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))


# ────────────────── F1：qsup 域分流 ──────────────────

def test_qsup_structural_never_supply_no_fire(monkeypatch):
    """tongcheng 形态（c330 病例）：国内窗满勤 + 国际窗结构性全断
    → 合并口径 4/24 恒触发的结构性假火根治：国际窗零记录经 r333
    供给基线门静默（本进程从未见 sup>0=窗口诞生起恒零特征，判例
    卅二§1）、国内窗满勤不评估 → 零告警（连续 3 轮验证非单轮侥幸）。"""
    _setup(monkeypatch)
    lg = _L()
    sup = {"tongcheng": {"dom": [4, 4], "intl": [0, 20]}}
    for _ in range(3):
        _m._channel_partial_sentinel(sup, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), lg.seen


def test_qsup_intl_partial_fires_with_domain_word(monkeypatch):
    """国际窗真部分断供（3/20 连续 2 轮）→ WARNING 且词面带「国际窗」
    与比率辨识；streak 按域独立累计。"""
    _setup(monkeypatch)
    lg = _L()
    sup = {"qunar": {"dom": [4, 4], "intl": [3, 20]}}
    _m._channel_partial_sentinel(sup, lg)
    assert not any("部分断供" in m for _lv, m in lg.seen), \
        "单轮不报（瞬时风控常态）：" + str(lg.seen)
    _m._channel_partial_sentinel(sup, lg)
    hits = [m for lv, m in lg.seen if lv == "W" and "部分断供" in m]
    assert len(hits) == 1, lg.seen
    assert "国际窗" in hits[0], "词面须带域辨识：" + hits[0]
    assert "3/20" in hits[0], "词面须带查询比率：" + hits[0]
    assert _m._QSUP_STREAK.get(("qunar", "intl")) == 2
    assert _m._QSUP_STREAK.get(("qunar", "dom"), 0) == 0, \
        "满勤域 streak 不得被他域牵连"


def test_qsup_dom_partial_still_fires(monkeypatch):
    """国内窗部分断供（1/4 连续 2 轮）→ 既有行为保持，词面升级带
    「国内窗」辨识（r297 用例的域分流改写）。"""
    _setup(monkeypatch)
    lg = _L()
    sup = {"tuniu": {"dom": [1, 4], "intl": [0, 0]}}
    _m._channel_partial_sentinel(sup, lg)
    _m._channel_partial_sentinel(sup, lg)
    hits = [m for lv, m in lg.seen if lv == "W" and "部分断供" in m]
    assert len(hits) == 1 and "国内窗" in hits[0] and "1/4" in hits[0], lg.seen
    assert _m._QSUP_STREAK.get(("tuniu", "dom")) == 2, \
        "intl 空档（tot=0）不清 dom streak"


# ────────────────── F2：rowfall 门槛下探 ──────────────────

def _feed(plat, rows_per_round, monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _m._ROW_HIST.clear()
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    lg = _L()
    for n in rows_per_round:
        _m._field_sentinel([_NS(platform=plat, from_city="SHA",
                                to_city="HAK", depart_date="2027-01-29",
                                extra=json.dumps(
                                    [{"price": 1000, "cabin": "经济舱"}] * n))],
                           lg)
    return lg


def test_rowfall_thin_pool_base2_collapse_fires(monkeypatch, tmp_path):
    """薄池病例（c330 F2）：tongcheng 每池基线 2 行、连续 2 轮塌 0
    → 门槛下探后必须评估并告警（旧门槛 base>=10 数学上永不评估）。"""
    lg = _feed("tongcheng", [2, 2, 2, 0, 0], monkeypatch, tmp_path)
    hits = [m for lv, m in lg.seen if lv == "W" and "行数塌方" in m]
    assert len(hits) == 1, lg.seen
    assert "0/2" in hits[0], "词面带塌方后行数/基线：" + hits[0]


def test_rowfall_base1_never_evaluates(monkeypatch, tmp_path):
    """基线 1 行的极薄池不评估（1→0 归查询面/全断哨领地）——门槛
    数学下限 base>=2 的反测：base<2 时 30% 线无整数命中。"""
    lg = _feed("fliggy", [1, 1, 1, 0, 0], monkeypatch, tmp_path)
    assert not any("行数塌方" in m for _lv, m in lg.seen), lg.seen


def test_rowfall_thin_pool_partial_collapse_no_fire(monkeypatch, tmp_path):
    """薄池 2→1（50%）波动不报：塌方线 30% 与连 2 轮持续性门槛
    保持——单轮偶发零误杀纪律在薄渠道同样成立。"""
    lg = _feed("tongcheng", [2, 2, 2, 1, 1], monkeypatch, tmp_path)
    assert not any("行数塌方" in m for _lv, m in lg.seen), lg.seen
