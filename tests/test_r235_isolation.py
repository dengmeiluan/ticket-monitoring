# -*- coding: utf-8 -*-
"""哨兵状态测试隔离（r235 观测 C 项）：哨兵告警链会把模块级
_SENT_LAST/_SENT_CNT 全量落盘 _SENT_PATH——漏打补丁的用例曾把
合成告警写进生产 data/sentinel_state.json（真断链首日虚标
「连续2日」、次日提前降 INFO；r234 PUSH_HISTORY_FILE 同族，
根治层在 conftest autouse，个案补钉防不住下一颗漏网）。"""
import json
import os

import main as _m

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROD_SENT = os.path.join(_REPO, "data", "sentinel_state.json")


def test_sentinel_state_path_redirected():
    """autouse 夹具必须把 _SENT_PATH 重定向出仓库 data 目录。"""
    assert not os.path.normpath(_m._SENT_PATH).startswith(
        os.path.normpath(_REPO)), _m._SENT_PATH


def test_sentinel_memory_state_fresh():
    """_SENT_LAST/_SENT_CNT 模块级全局不得跨测试残留——前序用例的
    合成告警态正是经由内存残留被后续漏补丁用例的 _sent_save
    带进生产文件。"""
    assert not _m._SENT_LAST, dict(_m._SENT_LAST)
    assert not _m._SENT_CNT, dict(_m._SENT_CNT)


def test_sentinel_save_never_touches_repo_data(tmp_path):
    """端到端：fliggy 空壳行触发告警链（当年污染生产文件的
    真实形态），生产 data/sentinel_state.json 必须逐字节不变。"""
    from types import SimpleNamespace as _NS

    # 构造事故形态：全新进程空内存态（import 时 _sent_load 读入的
    # 存量「当日已报」记录会让 _warn 首行短路，绕过落盘路径）
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    before = (open(_PROD_SENT, "rb").read()
              if os.path.exists(_PROD_SENT) else None)
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    rows = [{"price": 1000, "cabin": "经济舱", "stopover": True}
            for _ in range(25)]
    _m._field_sentinel([_NS(platform="fliggy", extra=json.dumps(rows))], _L())
    _m._sent_save()

    after = (open(_PROD_SENT, "rb").read()
             if os.path.exists(_PROD_SENT) else None)
    assert after == before, "生产哨兵文件被测试写入"
    # 落盘去向是重定向后的隔离文件，且合成键真实在盘
    with open(_m._SENT_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert any(k.startswith("fliggy|") for k in saved)
