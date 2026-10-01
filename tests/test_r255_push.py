# -*- coding: utf-8 -*-
"""r255 推送层两案 + 词面散点收口（审校报告 r255_audit_push.md）。

P3-1 multi 总表中转空态约束词面：主路径 meta4 漏带 arrival_max，
空态 fallback「次日 02:00」与组头实际约束（如次日23:59前到）同屏
矛盾——对齐 legacy 版（alerter 已有 arrival_max 双键形态）。
P3-2 钉钉网络异常轮不落账：except 分支补 errcode=-2 落账（未收到
响应），与 ServerChan/Email 异常落账对齐；发送路径零触碰——单发
零重试铁律不受影响（落账是记录，不是重发）。
⏱ 词面散点：「近 2.5 时」带空格漂移统一为「近2.5时」（与
test_core_units 既有钉「近2.5时口径」同族同形）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r255_push.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(path):
    return open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path),
        encoding="utf-8").read()


class TestMultiTableArrivalMax:
    def test_multi_meta4_carries_arrival_max(self):
        """P3-1：multi 版 meta4 与 legacy 版同构双键（layover_min +
        arrival_max）——空态词面按真实约束归因，不再恒落「次日 02:00」。
        搜索串缩进锁 multi 版（33 空格续行），防误配 legacy 同形串。"""
        src = _src("core/alerter.py")
        assert ('meta4 = {"layover_min": route.transfer_layover_min,\n'
                '                                 "arrival_max": '
                'route.transfer_arrival_max}' in src), \
            "multi 版 meta4 缺 arrival_max（与 legacy 版失同构）"

    def test_legacy_meta4_still_carries_both(self):
        """legacy 版既有双键形态保持（防同族回退）。"""
        src = _src("core/alerter.py")
        assert src.count('"arrival_max": route.transfer_arrival_max}') == 2


class TestDingtalkNetErrLedger:
    def test_network_exception_lands_in_ledger(self, monkeypatch, tmp_path):
        """P3-2：网络异常（httpx 抛错）轮落账 errcode=-2（未收到响应）
        ——控制台推送记录对这类轮不再失明。发送路径零改动：仍单发
        零重试，返回 False 由下轮心跳自然补。"""
        from core import notifier
        from core.notifier import DingTalkNotifier

        ledger = tmp_path / "push.jsonl"
        monkeypatch.setenv("PUSH_HISTORY_FILE", str(ledger))

        def boom(url, **kw):
            raise OSError("network unreachable")

        monkeypatch.setattr(notifier.httpx, "post", boom)
        dt = DingTalkNotifier("http://127.0.0.1:9/mock/robot",
                              logging.getLogger("t"))
        assert dt.send("t", "d") is False
        rows = [json.loads(l) for l in
                ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert rows, "网络异常轮应落账"
        r = rows[-1]
        assert r["ch"] == "dingtalk" and r["ok"] is False, r
        assert r.get("errcode") == -2, r


class TestTrendWindowLiteral:
    def test_no_spaced_window_literal(self):
        """「近 2.5 时」带空格漂移零残留（正文词面统一「近2.5时」，
        与日报 ⏱ 行既有钉同形）。"""
        assert "近 2.5 时" not in _src("report.py")
