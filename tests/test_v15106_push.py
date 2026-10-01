# -*- coding: utf-8 -*-
"""推送历史账本路径重定向（r106 推送审计 P1-1 防再犯面）。

判例：压测/探针经真实 send 路径会把合成记录落进生产 push_history
主账本（09-23/24 段 13 条污染，渲染定律重放 331 行假阳全部出自该
段；前轮已清洗同族一段）。防线：账本路径支持环境变量重定向——
压测脚本设 PUSH_HISTORY_FILE 即落独立账本，主账本零污染；不设时
行为不变（生产路径零改动）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15106_push.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import _append_push_history  # noqa: E402


def test_push_history_probe_redirect(tmp_path, monkeypatch):
    """PUSH_HISTORY_FILE 指向独立文件：记录落独立账本、主账本不产生。"""
    probe = tmp_path / "probe.jsonl"
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(probe))
    # 默认账本路径按 CWD 解析（logs/push_history.jsonl）；不切 CWD 时
    # 「主账本不产生」断言恒真（默认写根本不会落进 tmp_path）——切到
    # tmp_path 后，若重定向回归失效，默认写会落 tmp_path/logs，该断言
    # 才具备一跑即红的判别力
    monkeypatch.chdir(tmp_path)
    _append_push_history("t", "d", True, ch="probe")
    assert probe.exists()
    rec = json.loads(probe.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ch"] == "probe"
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_default_path_unchanged(tmp_path, monkeypatch):
    """生产形态入口（main.py）不设环境变量：默认 logs/push_history.jsonl
    行为不变（r235 写入门后 argv 需模拟生产形态；门本身另钉）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUSH_HISTORY_FILE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py"])
    _append_push_history("t", "d", True, ch="dingtalk")
    rec = json.loads(
        (tmp_path / "logs" / "push_history.jsonl")
        .read_text(encoding="utf-8").splitlines()[0])
    assert rec["ch"] == "dingtalk"
