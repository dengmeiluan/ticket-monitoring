# -*- coding: utf-8 -*-
"""r1063 T132：`python -m core.channel_matrix` —— 渠道 × 通路矩阵。

为什么做：面板上的信息是分散的（健康卡/降级行/会话窗口/登录卡），排查要来回看。
这个命令把 `/api/pacing` **已有字段**按"渠道 × 通路"摆成一张表，不新增任何采集逻辑。

踩过的坑（写下来）：`/api/pacing` 的通路对象只有 `rate / attempts / why /
last_ok_at`，**没有 status、也没有 rows**。第一版按 `status/rows` 取，结果整列是 `-`。
现在改成**按 rate + 原因关键词推导**可读状态。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_matrix as CM  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_state_from_rate():
    assert CM._derive_state(1.0, "") == "成功"
    assert CM._derive_state(0.87, "") == "时好时坏"
    assert CM._derive_state(0.45, "") == "时好时坏"


def test_state_from_reason_keywords():
    assert CM._derive_state(0, "需登录（97 分钟内不再重试）") == "需登录"
    assert CM._derive_state(0, "风控验证页") == "被拦"
    assert CM._derive_state(0, "本轮等待预算用尽（已 268s）") == "主动让位"
    assert CM._derive_state(0, "日期超出 App 视野") == "不支持"
    assert CM._derive_state(0, "返回「访问被拒绝」安全页") == "被拦"
    assert CM._derive_state(None, "") == "无数据"


def test_table_has_header_and_rows():
    rows = [
        {"plat": "fliggy", "path": "PC", "rate": 1.0, "n": 140,
         "state": "成功", "why": "sjipiao.fliggy.com 国际列表", "last_ok_at": ""},
        {"plat": "app_fliggy", "path": "app-login", "rate": 0, "n": 2,
         "state": "需登录", "why": "需登录（97 分钟内不再重试）", "last_ok_at": ""},
    ]
    txt = CM._table(rows)
    assert "渠道" in txt and "通路" in txt and "成功率" in txt
    assert "fliggy" in txt and "app-logging" not in txt
    assert "100%" in txt and "0%" in txt


def test_table_filter_by_plat():
    rows = [{"plat": "a", "path": "PC", "rate": 1.0, "n": 1, "state": "成功",
             "why": "", "last_ok_at": ""},
            {"plat": "b", "path": "PC", "rate": 0, "n": 1, "state": "需登录",
             "why": "", "last_ok_at": ""}]
    txt = CM._table(rows, "b")
    assert "b" in txt and "a " not in txt


def test_empty_rows_message():
    assert "没有数据" in CM._table([])


def test_no_hardcoded_ports_only_defaults():
    """允许通过 --port 指定，但默认探测 8765/8000/5000（别写死一个）。"""
    assert 8765 in CM.DEFAULT_PORTS
    assert len(CM.DEFAULT_PORTS) >= 2
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--plat" in src and "--json" in src
