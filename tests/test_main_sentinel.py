# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r288_sentinel.py
- tests/test_r320_sentinel_anchor.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import main as _m
import os
import sys

from types import SimpleNamespace as _NS


# ---- merged from tests/test_r288_sentinel.py ----

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


# ---- merged from tests/test_r320_sentinel_anchor.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _argv_mono(name):
    """argv 模拟入口形态（pytest 进程的 argv 是 pytest 自身）。"""
    return [f"/some/where/{name}"]


def test_bypass_entry_diverts_outside_repo(monkeypatch):
    """旁路形态（探针脚本入口）+ 未设重定向 → 落点不在仓库 data/。"""
    monkeypatch.setattr(sys, "argv", _argv_mono("my_probe.py"))
    monkeypatch.delenv("SENTINEL_STATE_FILE", raising=False)
    p = _m._sent_state_path()
    assert not os.path.normpath(p).startswith(
        os.path.normpath(_REPO)), p
    assert not os.path.normpath(p).startswith(
        os.path.normpath(os.path.join(_REPO, "data"))), p


def test_explicit_redirect_always_wins(monkeypatch, tmp_path):
    """显式重定向永远放行（压测/探针设它落独立文件，旁路形态同放行）。"""
    monkeypatch.setattr(sys, "argv", _argv_mono("my_probe.py"))
    red = os.path.join(str(tmp_path), "sent.json")
    monkeypatch.setenv("SENTINEL_STATE_FILE", red)
    assert _m._sent_state_path() == red


def test_prod_entry_keeps_default_path(monkeypatch):
    """生产形态（main.py 入口）默认路径不变（data/sentinel_state.json）。"""
    monkeypatch.setattr(sys, "argv", _argv_mono("main.py"))
    monkeypatch.delenv("SENTINEL_STATE_FILE", raising=False)
    assert os.path.normpath(_m._sent_state_path()) == os.path.normpath(
        _m._SENT_PATH)


def test_frozen_entry_keeps_default_path(monkeypatch):
    """打包 exe（frozen）同属生产形态。"""
    monkeypatch.setattr(sys, "argv", _argv_mono("TicketMonitor.exe"))
    monkeypatch.setattr(_m.sys, "frozen", True, raising=False)
    monkeypatch.delenv("SENTINEL_STATE_FILE", raising=False)
    assert os.path.normpath(_m._sent_state_path()) == os.path.normpath(
        _m._SENT_PATH)


def test_end_to_end_save_guard(monkeypatch, tmp_path):
    """端到端最强形态：旁路形态进程 _sent_save() 后生产文件字节不变
    （生产哨状态文件先行种入，保存动作落临时目录）。"""
    import json
    monkeypatch.setattr(sys, "argv", _argv_mono("my_probe.py"))
    monkeypatch.delenv("SENTINEL_STATE_FILE", raising=False)
    prod = os.path.join(str(tmp_path), "prod_repo_data")
    os.makedirs(prod, exist_ok=True)
    sent = os.path.join(prod, "sentinel_state.json")
    with open(sent, "w", encoding="utf-8") as f:
        json.dump({"ctrip|meal": ["2026-10-16", 3]}, f)
    before = open(sent, "rb").read()
    monkeypatch.setattr(_m, "_SENT_PATH", sent)
    monkeypatch.setattr(_m, "_SENT_LAST", {("tuniu", "zrow"): "2026-10-16"})
    _m._sent_save()
    assert open(sent, "rb").read() == before, (
        "旁路进程写穿了生产哨状态文件（资格门未拦）")
    # 落点在临时目录且内容是本进程内存态
    diverted = _m._sent_state_path()
    assert os.path.exists(diverted) and diverted != sent
    assert "tuniu|zrow" in json.load(open(diverted, encoding="utf-8"))


def test_load_reads_diverted_path(monkeypatch, tmp_path):
    """读侧同走 helper：旁路形态读落点文件（防读写劈叉）。"""
    import json
    monkeypatch.setattr(sys, "argv", _argv_mono("my_probe.py"))
    red = os.path.join(str(tmp_path), "sent.json")
    with open(red, "w", encoding="utf-8") as f:
        json.dump({"qunar|meal": ["2026-10-15", 2]}, f)
    monkeypatch.setenv("SENTINEL_STATE_FILE", red)
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    _m._sent_load()
    assert _m._SENT_LAST.get(("qunar", "meal")) == "2026-10-15"
    assert _m._SENT_CNT.get(("qunar", "meal")) == 2


def test_logger_arg_unused_safety():
    """helper 为纯函数（无 logger 依赖）——签名防漂移备案钉。"""
    import inspect
    sig = inspect.signature(_m._sent_state_path)
    assert len(sig.parameters) == 0, sig
