# -*- coding: utf-8 -*-
"""r320 哨状态写入面生产资格门（观测 r320 立案 1）：

sentinel_state.json 锚定仓库 data/ 且写入面无资格门——demo/重放/
探针类旁路进程（python 直跑，非 pytest 入口）import main 后
_sent_save() 直写生产哨状态：合成记录的供给基线写入「空窗四元组
化石键」（supplied|ctrip|page||| 实录）、tongcheng×5/fliggy×2 连续
计数被覆写回退。pytest 入口有 conftest autouse 隔离，本门在写入面
根治非 pytest 旁路（与 notifier._append_push_history 生产资格门
同构三§7）：显式重定向（SENTINEL_STATE_FILE）永远放行；未设重定向
且非生产形态（非 frozen、入口非 main.py/webui.py）落临时目录独立
文件（静默拒写生产面）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320_sentinel_anchor.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as _m  # noqa: E402

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
