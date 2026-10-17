# -*- coding: utf-8 -*-
"""r288 哨兵批（bag_direct 哨门槛与渠道量级匹配）：

 WATCH 复核定谳（_scratch/r288_observe.md 移交 fliggy|bag_direct
「生产从未响过」）：DB 近 14 天实证——fliggy 单轮中转行 max=16
（1499 轮 ≥50 轮数=0）、tongcheng ≥50 轮全部停在 10-03 之前；
50 门槛下四渠道集体失明（有出勤的不火、零出勤的不达门槛永不
评估）。门槛收 10 与全行哨对齐（同「小渠道逃逸」判例 50→20→10
先例），直挂筛选温度计对零出勤小渠道复明。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r288_sentinel.py -q
"""
import json

from types import SimpleNamespace as _NS

import main as _m


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, *a, **k):
        self.seen.append(a)

    def info(self, *a, **k):
        self.seen.append(a)


def _setup(monkeypatch, tmp_path):
    """哨兵状态隔离四件套（照抄 test_r252_sentinel 样板，含
    _SENT_SUPPLIED 供给基线）。"""
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


def _run(logger, plat, rows):
    _m._field_sentinel([_NS(platform=plat, extra=json.dumps(rows))], logger)


def _trans_rows(n):
    """中转行群夹具（照抄 r252 样板：旁哨观测键带值防噪音）。"""
    return [{"price": 1000, "transCity": "西安", "layover": 90,
             "depTerminal": "T2", "transferService": "免费改签",
             "transTerminal": "咸阳T3",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for _ in range(n)]


def test_bag_direct_small_channel_observed(monkeypatch, tmp_path):
    """fliggy 量级轮（12 中转行，≥10 新门槛/<50 旧门槛）断链必须
    开火——50 门槛下此形态永不评估=哨位失明。供给基线语义：先
    健康供给轮（写直挂基线），再零直挂轮——「曾供给后归零」真警；
    纯 never-supplied 轮静默（r316 窗粒度语义，见 r252 同注）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    rows = _trans_rows(10)
    for r in rows[:4]:
        r["transferBaggage"] = "direct"
    _run(lg, "fliggy", rows)
    assert not any("行李直挂" in str(a) for a in lg.seen), lg.seen
    lg2 = _L()
    _run(lg2, "fliggy", _trans_rows(12))
    assert any("行李直挂" in str(a) for a in lg2.seen), lg2.seen


def test_bag_direct_below_floor_silent(monkeypatch, tmp_path):
    """中转行群 <10 样本不足整批不观测（观测门槛随分母平移）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "fliggy", _trans_rows(9))
    assert not any("行李直挂" in str(a) for a in lg.seen), lg.seen


def test_bag_direct_healthy_channel_silent(monkeypatch, tmp_path):
    """直挂出勤健康形态（4/10=40%，qunar 实测 40%）不误火。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    rows = _trans_rows(10)
    for r in rows[:4]:
        r["transferBaggage"] = "direct"
    _run(lg, "qunar", rows)
    assert not any("行李直挂" in str(a) for a in lg.seen), lg.seen
