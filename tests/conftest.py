# -*- coding: utf-8 -*-
"""合成数据隔离（根治层，r234/r235 两案同律）：send 触达与哨兵
落盘类测试漏设隔离时，合成数据按模块默认路径写进生产文件。

- PUSH_HISTORY_FILE（r234）：_append_push_history 按 CWD 落 logs/
  生产账本——20 条合成记录曾混入生产 push_history（控制台推送
  记录可见假推送）。
- _SENT_PATH + _SENT_LAST/_SENT_CNT（r235）：哨兵告警链把模块级
  内存态全量落盘 data/sentinel_state.json——漏补丁用例曾把合成
  告警写进生产哨兵文件（真断链首日虚标「连续2日」、次日提前降
  INFO）；内存态跨测试残留还会让后续用例的保存把前序合成态
  一并带进生产文件。

autouse 重定向到每测试独立路径；显式 setenv/setattr 的用例照常
自覆（monkeypatch LIFO），「默认路径行为不变」类钉须模拟生产
形态显式恢复，语义担保不丢。"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_push_history(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSH_HISTORY_FILE",
                       str(tmp_path / "push_history.jsonl"))


@pytest.fixture(autouse=True)
def _isolate_sentinel_state(tmp_path, monkeypatch):
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH",
                        os.path.join(str(tmp_path), "sentinel_state.json"))
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
