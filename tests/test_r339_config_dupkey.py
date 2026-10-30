# -*- coding: utf-8 -*-
"""config.yaml 重复键拒收（r339 生产事故根治守卫）。

事故形态：并行会话写 config 丢 `- ` 块分隔符，同块重复 to_name/dates/
alert_direct 序列在 yaml last-wins 语义下静默吞掉 16 条航线并顶错 4 条
阈值——load_config 原为裸 safe_load，重复键零告警。守卫=加载层重复键
即拒（ConstructorError 带键名），让坏写入在启动/热重载当场炸而非静默
丢航线。
"""
import textwrap

import pytest
import yaml

from main import load_config

_CLEAN = textwrap.dedent("""\
    users:
    - name: 测试用户
      routes:
      - from: SHA
        from_name: 上海
        to: HAK
        to_name: 海口
        dates:
        - '2027-01-29'
        alert_direct: 1500
        alert_transfer: 1300
      platforms:
      - qunar
    schedule:
      interval_minutes: 30
    crawler:
      headless: true
    output:
      db_path: data/prices.db
      log_path: logs/monitor.log
    web:
      port: 8765
    """)

# 事故原文形态：BKK 块内出现第二组 to_name/dates/alert_direct（新加坡）
_MANGLED = textwrap.dedent("""\
    users:
    - name: 测试用户
      routes:
      - from: SHA
        from_name: 上海
        to: BKK
        to_name: 曼谷
        dates:
        - '2026-11-16'
        alert_direct: 900
        alert_transfer: 0
        to_name: 新加坡
        dates:
        - '2026-11-16'
        alert_direct: 950
        alert_transfer: 0
      platforms:
      - qunar
    schedule:
      interval_minutes: 30
    output:
      db_path: data/prices.db
      log_path: logs/monitor.log
    web:
      port: 8765
    """)


def test_clean_config_loads_and_keeps_routes(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_CLEAN, encoding="utf-8")
    cfg = load_config(str(p))
    rts = cfg["users"][0]["routes"]
    assert len(rts) == 1
    assert rts[0]["to_name"] == "海口"
    assert rts[0]["alert_direct"] == 1500


def test_duplicate_route_key_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_MANGLED, encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError) as ei:
        load_config(str(p))
    assert "to_name" in str(ei.value)


def test_duplicate_top_level_key_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_CLEAN + "\nschedule:\n  interval_minutes: 10\n",
                 encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_config(str(p))
