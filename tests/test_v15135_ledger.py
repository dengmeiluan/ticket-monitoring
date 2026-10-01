# -*- coding: utf-8 -*-
"""推送账本写入门（r235 P2）：非生产进程未设 PUSH_HISTORY_FILE 时
拒写生产账本 logs/push_history.jsonl——旁路重放/调试脚本曾把合成
记录（title='t'）与 bug 复现期 urgent 落账混入生产账本（conftest
autouse 只拦 pytest 入口，python 直跑的脚本绕过它）。门的三面：
旁路拒写 / frozen 与 main.py、webui.py 生产形态放行 / 显式重定向
永远放行（压测/探针脚本设变量落独立账本的原契约不变）。"""
import json

from core.notifier import _append_push_history


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
