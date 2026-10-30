# -*- coding: utf-8 -*-
"""goal 轮推送账本代际字段：boot 戳自证产出进程。

案发（goal 轮推送审校）：图挂兜底 10-17 10:35 实发由旧代际进程产出
（16:03 才重启载新码），账本记录无法自证代际——审校把旧形态误立为
现行缺陷需逐族定界（14894 行次历史超宽逐一定界实录）。补 boot 戳
（模块导入时刻≈进程启动）：同一 boot=同一内存镜像（版本号可能同号
异树，boot 戳无歧义）；零循环依赖（不读 main.__version__）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_goal_push_gen.py -q
"""
import json
import os

from core.notifier import _append_push_history  # noqa: E402


def _recs():
    with open(os.environ["PUSH_HISTORY_FILE"], encoding="utf-8") as f:
        return [json.loads(x) for x in f.read().strip().splitlines()]


def test_push_history_carries_boot_generation():
    _append_push_history("t", "d", True, ch="dingtalk")
    recs = _recs()
    assert recs[-1].get("boot"), recs[-1]
    # 同进程多笔记录 boot 一致（代际=内存镜像自证）
    _append_push_history("t2", "d2", False, ch="dingtalk", errcode=-1)
    recs = _recs()
    assert recs[-1]["boot"] == recs[0]["boot"], recs
    # 既有字段语义不回归
    assert recs[-1]["errcode"] == -1 and recs[-1]["ok"] is False
