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
- TM_RENDER_DIR（r240）：图表渲染写点按相对路径落 data/——
  触达渲染链路的用例把测试图表落进生产 data/（租户段 t 的
  flights_table_*.png 多轮残留）。
- 近期明细补位链（r252）：storage=None 时补位读默认 data/prices.db
  近 6h 真实行——夹具不完整的用例曾把生产数据面拼进合成池
  （URC→SHA 夜间 tongcheng 7840 中转行抬高三渠道锚，合成
  fliggy/ctrip 1600 tie 组被孤低价守卫双杀，v15133 钉白天绿、
  入夜红，随生产数据面漂移）。测试默认补位=空池（池=夹具行）；
  显式 mock 补位源或传真 storage 的用例按 LIFO 自覆。

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
def _isolate_recent_flights(monkeypatch):
    import report as _rep
    # 真身暂存模块属性：直调型测试（v193 SQL 时间窗钉）显式取回
    # _recent_platform_flights_raw 测函数本体，不经隔离面
    if not hasattr(_rep, "_recent_platform_flights_raw"):
        _rep._recent_platform_flights_raw = _rep.recent_platform_flights
    monkeypatch.setattr(_rep, "recent_platform_flights",
                        lambda *a, **k: {})


@pytest.fixture(autouse=True)
def _isolate_render_dir(tmp_path, monkeypatch):
    d = tmp_path / "render"
    d.mkdir()   # 渲染函数无 makedirs——夹具预建目录防测试踩空
    monkeypatch.setenv("TM_RENDER_DIR", str(d))


@pytest.fixture(autouse=True)
def _isolate_sentinel_state(tmp_path, monkeypatch):
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH",
                        os.path.join(str(tmp_path), "sentinel_state.json"))
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})


@pytest.fixture(autouse=True)
def _allow_test_webhook(monkeypatch):
    """钉钉发送资格门的会话级放行（与 PUSH_HISTORY_FILE 同构根治层）：
    单测大量持真实域名字符串 webhook + httpx.post 打桩，逐用例补
    setenv 注定漏；旁路 python 直跑脚本不在 pytest 入口、无此放行，
    被资格门拦住真实发送（r254 发送端生产资格门）。需验门本体的
    用例显式 delenv/setenv 自覆（monkeypatch LIFO）。"""
    monkeypatch.setenv("DING_WEBHOOK_ALLOW", "1")
