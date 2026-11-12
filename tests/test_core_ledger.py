# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r975_ledger_status_histogram.py
- tests/test_v15135_ledger.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import os
import sys

from core.notifier import _append_push_history
from core.yield_stats import default_ledger


# ---- merged from tests/test_r975_ledger_status_histogram.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _read(root, plat):
    with open(os.path.join(root, plat, "yield_stats.json"),
              encoding="utf-8") as fh:
        return json.load(fh)[plat]


def test_status_histogram_counts_each_kind(tmp_path):
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "航班明细", False, 0, status="empty")
    led.note("demo", "航班明细", False, 0, status="empty")
    led.note("demo", "航班明细", False, 0, status="error")
    led.note("demo", "航班明细", True, 7, status="ok")
    body = _read(str(tmp_path), "demo")
    bucket = body["paths"]["航班明细"]
    assert bucket["st"] == {"empty": 2, "error": 1, "ok": 1}, bucket
    # ok/fail 语义一个字都没动
    assert bucket["ok"] == 1 and bucket["fail"] == 3, bucket
    assert body["total"] == {"ok": 1, "fail": 3, "rows": 7}, body["total"]


def test_empty_still_counts_as_no_data(tmp_path):
    """直方图不是"洗白"：empty 仍然算没取到数（ok=False）。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "航班明细", False, 0, status="empty")
    body = _read(str(tmp_path), "demo")
    assert body["total"]["ok"] == 0 and body["total"]["fail"] == 1


def test_status_is_optional_and_backward_compatible(tmp_path):
    """不传 status（老调用点）照旧工作，且不产生空的 st 键。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "PC", True, 3)
    bucket = _read(str(tmp_path), "demo")["paths"]["PC"]
    assert bucket["ok"] == 1 and bucket["rows"] == 3
    assert "st" not in bucket, bucket


def test_old_ledger_without_st_is_readable(tmp_path):
    """老账本（没有 st 键）读取不得抛异常，rate/samples 照常。"""
    d = tmp_path / "demo"
    d.mkdir(parents=True)
    (d / "yield_stats.json").write_text(json.dumps({"demo": {
        "hours": {}, "total": {"ok": 2, "fail": 1, "rows": 9},
        "paths": {"PC": {"ok": 2, "fail": 1, "rows": 9, "last": 0.0}},
    }}), encoding="utf-8")
    led = default_ledger(str(tmp_path), "demo")
    assert abs(led.rate("demo") - 2.0 / 3.0) < 1e-9
    assert led.samples("demo", "PC") == 3


def test_callers_record_a_status():
    """两个采集器调用点必须真的把 status 传下去（否则一行都不会进直方图）。"""
    import io
    for f in ("crawlers/base.py", "crawlers/app_base.py"):
        src = io.open(os.path.join(ROOT, f), encoding="utf-8").read()
        assert "status=_st" in src, "%s 没把 status 传给 led.note" % f


# ---------------------------------------------------------------------------
# 顶行口径：非采集通路不进分母
# ---------------------------------------------------------------------------
def test_snapshot_excludes_non_sample_paths(tmp_path):
    """顶行只算"真的打了站点"的通路。

    实测（2026-11-05 生产账本）：app_qunar 的 `航班明细` 是 16/40（0.28），
    但 total 里混着 37 条 TRIP（往返不支持）与 35 条 unknown（app-silent
    上线前的旧轮次），顶行因此被压到 0.09，读起来像"整个渠道全挂"。
    """
    led = default_ledger(str(tmp_path), "demo")
    for _ in range(16):
        led.note("demo", "航班明细", True, 3, status="ok")
    for _ in range(24):
        led.note("demo", "航班明细", False, 0, status="empty")
    for _ in range(37):
        led.note("demo", "TRIP", False, 0, status="unsupported")
    for _ in range(35):
        led.note("demo", "unknown", False, 0)
    for _ in range(292):
        led.note("demo", "snap-restore", False, 0)

    old = led.snapshot()                      # 历史口径
    new = led.snapshot(exclude_infra=True)    # 真实采集口径
    assert old["demo"]["n"] == 16 + 24 + 37 + 35 + 292, old["demo"]
    assert new["demo"]["n"] == 40, new["demo"]
    assert new["demo"]["ok"] == 16, new["demo"]
    # 0.40 成功率 → Wilson 下界约 0.27，明显高于被污染时的 0.09
    assert new["demo"]["lower"] > 0.2, new["demo"]


def test_snapshot_default_keeps_old_behaviour(tmp_path):
    """默认（不带 exclude_infra）行为必须和以前一模一样，不能悄悄改语义。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "snap-restore", False, 0)
    led.note("demo", "航班明细", True, 5, status="ok")
    snap = led.snapshot()
    assert snap["demo"]["n"] == 2 and snap["demo"]["ok"] == 1, snap["demo"]


# ---- merged from tests/test_v15135_ledger.py ----

def _delenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUSH_HISTORY_FILE", raising=False)


def test_push_history_bypass_process_rejected(tmp_path, monkeypatch):
    """非生产入口（python 直跑脚本）未设隔离：拒写生产账本。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["_scratch/replay.py"])
    _append_push_history("t", "d", True, ch="probe")
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_bare_interpreter_rejected(tmp_path, monkeypatch):
    """python -c / 嵌入态（argv 无生产入口痕迹）：同样拒写。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["-c"])
    _append_push_history("t", "d", True, ch="probe")
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_empty_argv_rejected(tmp_path, monkeypatch):
    """argv 清空（嵌入解释器极端态）：fail-closed 拒写。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", [])
    _append_push_history("t", "d", True, ch="probe")
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_main_abs_path_default_path(tmp_path, monkeypatch):
    """main.py 绝对路径入口：endswith 语义放行默认路径。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv",
                        [str(tmp_path / "srv" / "main.py")])
    _append_push_history("t", "d", True, ch="dingtalk")
    assert (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_main_entry_default_path(tmp_path, monkeypatch):
    """main.py 入口未设变量：默认 logs/push_history.jsonl 行为不变。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["main.py"])
    _append_push_history("t", "d", True, ch="dingtalk")
    rec = json.loads(
        (tmp_path / "logs" / "push_history.jsonl")
        .read_text(encoding="utf-8").splitlines()[0])
    assert rec["ch"] == "dingtalk"


def test_push_history_webui_entry_default_path(tmp_path, monkeypatch):
    """webui.py 入口（生产控制台/演示服同形态）：默认路径放行。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv",
                        [str(tmp_path / "webui.py"), "--demo"])
    _append_push_history("t", "d", True, ch="dingtalk")
    assert (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_frozen_exe_default_path(tmp_path, monkeypatch):
    """打包 exe（sys.frozen）：argv[0] 是 exe 自身路径，恒放行。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", [str(tmp_path / "TicketMonitor.exe")])
    monkeypatch.setattr("sys.frozen", True, raising=False)
    _append_push_history("t", "d", True, ch="dingtalk")
    assert (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_explicit_redirect_beats_gate(tmp_path, monkeypatch):
    """显式 PUSH_HISTORY_FILE 重定向永远放行（压测/探针原契约）。"""
    _delenv(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["_scratch/replay.py"])
    probe = tmp_path / "ledger" / "probe.jsonl"
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(probe))
    _append_push_history("t", "d", True, ch="probe")
    assert probe.exists()
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()
