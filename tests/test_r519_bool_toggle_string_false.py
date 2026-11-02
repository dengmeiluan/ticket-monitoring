# -*- coding: utf-8 -*-
"""r519：开关写成字符串时不能静默失效（`bool("false") is True`）。

`config.yaml` 是用户手写的。写成

    crawler:
      health_penalty_enabled: "false"     # 带引号，YAML 里是字符串

时，旧代码 `bool(crw.get(...))` 得到 **True** —— 开关静默失效：
配置页把这个值回读成"已关闭"（前端按 `!== false` 判断），后端却仍在
按成功率降频。用户以为关掉了，实际没有。

修法：字符串按常见假值词判定（`0/false/no/off/""`），与 YAML 语义一致。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.pacing import Pacing, parse_pacing  # noqa: E402


def _cfg(v):
    return parse_pacing({"crawler": {"health_penalty_enabled": v}})


def test_string_false_words_turn_the_switch_off():
    for v in ("false", "FALSE", " False ", "no", "off", "0", ""):
        assert _cfg(v)["health_penalty_enabled"] is False, \
            "YAML 写成 %r 时开关仍是开的（bool(str) 恒真）" % (v,)


def test_string_true_words_keep_it_on():
    for v in ("true", "TRUE", "yes", "on", "1"):
        assert _cfg(v)["health_penalty_enabled"] is True, v


def test_real_booleans_unchanged():
    assert _cfg(True)["health_penalty_enabled"] is True
    assert _cfg(False)["health_penalty_enabled"] is False
    assert _cfg(0)["health_penalty_enabled"] is False
    assert _cfg(1)["health_penalty_enabled"] is True
    # 缺省仍取 DEFAULTS
    assert parse_pacing({})["health_penalty_enabled"] is True


def test_string_false_actually_disables_the_penalty():
    """行为级：关掉后不得再降频（这是「可开启可关闭」的实质）。"""
    for v in (False, "false"):
        p = Pacing({"crawler": {"health_penalty_enabled": v}})
        p.set_health("qunar", 0.1, 10)
        h = p._health.get("qunar") or {}
        assert h.get("penalty") == 1.0, \
            "cfg=%r 时仍在按成功率降频：%r" % (v, h)
        assert h.get("disabled") is True, h
    # 开启时必须真的降频（不能为了修关闭把功能关掉）
    p2 = Pacing({"crawler": {"health_penalty_enabled": True,
                             "health_min_samples": 5,
                             "health_ok_ratio": 0.7,
                             "health_slow_ratio": 0.4,
                             "health_slowest_factor": 3.0}})
    p2.set_health("qunar", 0.1, 10)
    assert (p2._health.get("qunar") or {}).get("penalty") == 3.0, \
        "开启时不再降频（把功能关掉了）：%r" % (p2._health.get("qunar"),)


def test_all_three_toggles_share_the_same_string_handling():
    """三个开关走同一个解析函数（r520）：只修一个会留下同类缺口。

    实测 `breaker.enabled` / `warmup.enabled` 原先也是 `bool(...)`，
    同样会把 `"false"` 当 True。
    """
    cases = [
        ("breaker_enabled", {"crawler": {"breaker": {"enabled": "false"}}}),
        ("warmup_enabled", {"crawler": {"warmup": {"enabled": "false"}}}),
        ("health_penalty_enabled",
         {"crawler": {"health_penalty_enabled": "false"}}),
    ]
    for key, cfg in cases:
        assert parse_pacing(cfg)[key] is False, \
            "%s 的 \"false\" 仍被当成开启" % key
        # 缺省/None 必须回到 DEFAULTS，不能被 _flag 误判成关闭
    assert parse_pacing({})["breaker_enabled"] is True
    assert parse_pacing({})["warmup_enabled"] is True
    assert parse_pacing({})["health_penalty_enabled"] is True


def test_flag_helper_is_single_source():
    """三处必须调用同一个 `_flag`，不允许再各写一份。"""
    import inspect
    from core import pacing as _p
    src = inspect.getsource(_p.parse_pacing)
    assert src.count("_flag(") == 3, \
        "应有三处走 _flag，实际 %d 处" % src.count("_flag(")
    assert "bool(brk.get(" not in src and "bool(warm.get(" not in src, \
        "仍有地方用 bool() 直接转配置值"
    assert callable(_p._flag)
