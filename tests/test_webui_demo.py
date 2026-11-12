# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r498_demo_db_sweep.py
- tests/test_r628_demo_payload_has_pacing_switches.py
- tests/test_r652_demo_payload_covers_all_channels.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webui


# ---- merged from tests/test_r498_demo_db_sweep.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _mk(dirpath, name, age_s):
    import time as _t
    p = os.path.join(dirpath, name)
    with open(p, "wb") as f:
        f.write(b"x" * 32)
    ts = _t.time() - age_s
    os.utime(p, (ts, ts))
    return p


def test_sweep_removes_only_stale_non_current(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: d)
    cur = _mk(d, "ticket_demo_prices_8765.db", 7200)   # 本次端口但很旧
    old = _mk(d, "ticket_demo_prices_1111.db", 7200)   # 旧且非本次
    fresh = _mk(d, "ticket_demo_prices_2222.db", 60)   # 新
    other = _mk(d, "prices.db", 7200)                  # 不像 demo 库
    keep_me = _mk(d, "monitor.log", 7200)

    n = webui._demo_db_sweep(8765, max_age_s=3600)

    assert n == 1, "应只清理 1 个历史库，实际 %d" % n
    assert os.path.exists(cur), "删掉了本次端口的库（会打断当前实例）"
    assert not os.path.exists(old), "历史库未清理"
    assert os.path.exists(fresh), "删掉了 1 小时内活跃的库（正在运行的实例会被打断）"
    assert os.path.exists(other), "删了不相关的数据库文件"
    assert os.path.exists(keep_me), "删了不相关的日志文件"


def test_sweep_is_noop_on_empty_dir(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: d)
    assert webui._demo_db_sweep(8765) == 0


def test_sweep_never_raises(monkeypatch):
    """目录不可读时也不得抛（启动路径不能因为清理失败而崩）。"""
    def boom():
        raise OSError("nope")
    monkeypatch.setattr(tempfile, "gettempdir", boom)
    assert webui._demo_db_sweep(8765) == 0


def test_entry_calls_the_sweep_before_building():
    """入口必须先清理再建库，否则新库会被自己刚建的逻辑影响。"""
    import io
    w = webui_full_src()
    i = w.index("_swept = _demo_db_sweep(args.port)")
    j = w.index("db = _demo_db_path(args.port)", i)
    assert i < j, "清理必须发生在建库之前"


# ---- merged from tests/test_r628_demo_payload_has_pacing_switches.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 配置页会读、且 `!== false` 判定的节流开关：缺一个就必然谎报「开」
_REQUIRED = ("warmup_enabled", "breaker_enabled", "health_penalty_enabled",
             "warmup_platforms", "warmable")


def test_demo_payload_contains_pacing_keys():
    """静态：演示载荷必须并入节流六项（不许再手抄漏项）。"""
    w = webui_full_src()
    i = w.index("def _demo_config_payload()")
    j = w.index("def ", i + 10)
    body = w[i:j]
    assert "_demo_pacing_globals()" in body, (
        "演示载荷没有再并入节流开关（会重现「恒显示开」）：\n%s" % body[:400])


def test_demo_pacing_globals_has_every_key_and_follows_cfg():
    import webui
    from core.pacing import DEFAULTS
    webui._State.cfg = {"crawler": {
        "warmup": {"enabled": False, "platforms": ["qunar", "ctrip"]},
        "breaker": {"enabled": False},
        "health_penalty_enabled": False,
    }}
    g = webui._demo_pacing_globals()
    for k in _REQUIRED:
        assert k in g, "演示载荷缺 %s（配置页会把它当「开」）" % k
    # 必须跟着 _State.cfg 走，不能写死 True
    assert g["warmup_enabled"] is False, g
    assert g["breaker_enabled"] is False, g
    assert g["health_penalty_enabled"] is False, g
    # 名单：ctrip 没有入口要进 ignored，不能混进可用名单
    assert "ctrip" not in g["warmup_platforms"], g
    assert "ctrip" in g["warmup_ignored"], g
    # 阈值也在（r485 的可配项在演示下同样要能显示真实值）
    assert g["health_ok_ratio"] == DEFAULTS["health_ok_ratio"], g




# ---- merged from tests/test_r652_demo_payload_covers_all_channels.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _registry():
    from crawlers import REGISTRY
    return set(REGISTRY.keys())


def test_demo_payload_lists_every_real_channel():
    import webui

    got = set(webui._demo_pacing_payload()["channels"].keys())
    want = _registry()
    missing = sorted(want - got)
    assert not missing, (
        "演示节流载荷缺这些真实渠道（访客看到的全貌是残的）：%s" % missing)


