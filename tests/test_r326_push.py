# -*- coding: utf-8 -*-
"""r326 推送面收口钉（审计 P3-1：特价推送绕过 sanitize_desp 消毒单源）。

main.py 特价路径是 alerter 全部 send 出口中唯一不过 sanitize_desp 的
绕行出口——特价文案拼装渠道自由词面（discount/airline），尖括号/
U+2026 家族可直通钉钉渲染层。钉面双段：裸直发禁复活 + 消毒实效档。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r326_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _main_src():
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "main.py"), encoding="utf-8") as f:
        return f.read()


def test_special_push_send_passes_sanitize():
    src = _main_src()
    # 实效档：特价推送经消毒单源出口（与 alerter 全部 send 同守卫）
    assert "a.notifier.send(sanitize_desp(title), sanitize_desp(desp))" in src
    # 禁复活：裸直发（未过 sanitize_desp）不得回归
    assert "a.notifier.send(title, desp)" not in src
