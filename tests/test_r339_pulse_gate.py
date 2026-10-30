# -*- coding: utf-8 -*-
"""r339 观测立案修案：Pulse 写入端生产资格门。

r339c 数据观测立案 5（修）：test_pulse_round_lifecycle 用 Pulse() 未
注入 store → 每次 pytest 向生产 data/pulse.json 追加 1 条合成轮
（实录 ~14 条 qunar70/fliggy0 假轮，pid 各异=各次 pytest 进程），
叠加「生产轮只在整链完成时落盘」语义，控制台脉冲卡显示的全是 pytest
假轮。根治层=写入端生产资格门（notifier._append_push_history 同律
七§6：非生产形态进程拒写默认账本，显式注入 store 永远放行），
逐用例补隔离注定漏——新用例照抄无隔离样板就复发。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339_pulse_gate.py -q
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.pulse as P


def _fresh(tmp_path, monkeypatch, store_override=None):
    """重定向模块 STORE 到 tmp（防任何分支触达真实生产文件）后新建
    实例；返回 (实例, 账本路径)。"""
    tgt = str(tmp_path / "pulse.json")
    monkeypatch.setattr(P, "STORE", tgt)
    return P.Pulse(store=store_override), (store_override or tgt)


def test_pytest_form_rejects_default_store(tmp_path, monkeypatch):
    """非生产形态进程（pytest）+ 默认路径 → end() 不落盘（合成轮
    不入生产账本）。"""
    p, tgt = _fresh(tmp_path, monkeypatch)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=False):
        p.begin()
        p.channel("qunar", 70, 8.2)
        p.end()
    assert not os.path.exists(tgt), "合成轮写入默认账本=污染复发"


def test_prod_form_writes(tmp_path, monkeypatch):
    """生产形态（exe/main.py/webui.py 入口）+ 默认路径 → 照写
    （产品语义不丢：生产轮持久化）。"""
    p, tgt = _fresh(tmp_path, monkeypatch)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=True):
        p.begin()
        p.channel("qunar", 70, 8.2)
        p.end()
    assert os.path.exists(tgt)
    rounds = json.load(open(tgt, encoding="utf-8"))
    assert rounds and rounds[-1]["chans"]["qunar"]["rows"] == 70


def test_explicit_store_always_allowed(tmp_path, monkeypatch):
    """显式注入 store（压测/探针独立账本）→ 资格门不拦（显式重定向
    永远放行，与 push history 契约同）。"""
    alt = str(tmp_path / "alt_pulse.json")
    p, _ = _fresh(tmp_path, monkeypatch, store_override=alt)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=False):
        p.begin()
        p.channel("ctrip", 5, 1.0)
        p.end()
    assert os.path.exists(alt)
    rounds = json.load(open(alt, encoding="utf-8"))
    assert rounds and rounds[-1]["chans"]["ctrip"]["rows"] == 5
