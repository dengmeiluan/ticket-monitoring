"""v1.5.79 推送回归钉：审校 P2 三案（push_review_v179）。

①gap_txt 恰达线词面挂 TIER_FULL 投影（字面直写=模块头「改词必漏」
  同病；执行级双断言+源码钉——值今日同源，仅源码钉能防漂移）；
②_alert_body 装饰剥离清单补 ⚠️/⚠（图挂兜底「⚠️口径差异」行中形态
  VS16 剥除后剩裸 ⚠ 进短信/TTS）；
③DingTalkNotifier 落史补 ch="dingtalk"（控制台推送记录通道维度对齐，
  收口到 _append_push_history 单源）。
"""

import inspect
import json
import os

import core.alerter as A
import core.notifier as N
from core.alerter import TIER_FULL, gap_txt
from core.notifier import _alert_body, _append_push_history


def test_gap_txt_tier_projection():
    """①恰达线词面=投影非字面。"""
    assert gap_txt(1900, 1900, True) == TIER_FULL["qual"]
    assert gap_txt(1900, 1900, False) == TIER_FULL["mkt"]
    assert "TIER_FULL" in inspect.getsource(A.gap_txt), \
        "gap_txt 恰达线词面仍为字面直写（改 _TIER_TABLE 必漏此处）"


def test_alert_body_strips_warning_sign():
    """②行中 ⚠️ 剥净（含 VS16 合成符与裸符），TTS/短信不读「警告符号」。"""
    desp = ("直飞达标 低￥120，建议出手\n\n"
            "比价离群 ⚠️口径差异 已标注\n\n"
            "- 渠道 最低 ￥880")
    assert "⚠" not in _alert_body(desp)


def test_dingtalk_history_has_channel(tmp_path, monkeypatch):
    """③钉钉落史带 ch="dingtalk" 且收口到 _append_push_history 单源。"""
    monkeypatch.chdir(tmp_path)
    _append_push_history("t", "d", True, ch="dingtalk")
    with open(os.path.join("logs", "push_history.jsonl"), encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["ch"] == "dingtalk"
    src = open(N.__file__, encoding="utf-8").read()
    assert '_append_push_history(title, desp, ok, ch="dingtalk")' in src
    assert '"ok": ok, "title": title, "desp": desp}' not in src, \
        "钉钉内联落史块应删除（无 ch 字段的旧形态）"
