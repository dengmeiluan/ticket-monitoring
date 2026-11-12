# -*- coding: utf-8 -*-
"""r281 推送 P2-1（r280 P2-1 维持立案，TDD 先行，审计
_scratch/r281_push_report.md §②）：

KPI 行 2（航班身份行）降级链地板档在病理名形态（超长名+全角括注/
超长营销名/未闭合括注）下从头部逐字截，吃掉行尾时刻/跨天辨识信息
——miss/near 形态 KPI 行 2 是时刻唯一载体，读者既不知哪班也不知当
日达/次日达=决策级误读（LESSONS 十九§9：跨天辨识信息宁可剥名字段
也不可被逐字截吃掉）。修法选形经 Wave 3 两向真实计宽实测（r281_
push_probe_l2fix）：修法 A（补剥全角括注对档）对最疼的双名括注
形态不可达（剥后仍 ~43 半角）且对语义括注（经停武汉）有剥语义害
——不采；修法 B（地板改「保尾截头」）10/10 形态时刻在场、9/10 跨
天在场——落地。地板语义：时刻+跨天锚定行尾（cross 形参由此真入
链，顺带修复地板档 cross 恒缺席的既有次生丢失），头部名段让位；
现实域 6 形态由剥「｜」档承接零漂移（重放已证）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r281_push.py
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.alerter import _disp_dw, _fit_line, _l2_fallbacks


def _pick(base, cross, d=""):
    tiers = _l2_fallbacks(base, cross, d)
    return _fit_line(base + cross + d, fallbacks=tiers)


# ---------- 病理域：时刻/跨天必在场（修法 B 新行为） ----------

PATHO_CASES = [
    # (航班名, 跨天括注)——r281_push_probe_l2fix 网格的翻车形态
    ("新海航｜海南航空 HU7849（大机型宽体直飞航班）", "(+1天)"),  # 双名+括注
    ("海南航空HU7849（宽体直飞航班机型展示）", "(+1天)"),         # 单名+括注
    ("大美新疆航旅｜海南航空HU7849宽体直飞", "(+1天)"),           # 超长营销名
    ("海南航空HU7849（宽体直飞", "(+1天)"),                       # 未闭合括注
    ("新海航｜海南航空HU7849（经停武汉）", "(+1天)"),             # 语义括注
]


@pytest.mark.parametrize("name,cross", PATHO_CASES)
def test_l2_floor_keeps_tail_times(name, cross):
    base = "%s 21:10→02:35" % name
    picked = _pick(base, cross, d=" 较上轮 ↓100")
    w = _disp_dw(picked)
    assert w <= 40, "地板档恒达标律破：%r w=%d" % (picked, w)
    assert "21:10" in picked and "02:35" in picked, (
        "病理名形态地板档吃掉时刻（%r）——时刻/跨天是决策级辨识信息，"
        "宁可剥名字段不可逐字截吃掉" % picked)
    assert cross in picked, (
        "地板档 cross 恒缺席（既有次生丢失未随修法 B 修复）：%r" % picked)


# ---------- 现实域零漂移：剥名档承接，地板不可达 ----------

REAL_CASES = [
    "南航CZ6976",
    "新海航｜天津航空HU7849",
    "新海航｜乌鲁木齐航空UQ3599",       # 生产最宽双名 27 半角
    "海南航空 HU7849/春秋9C8845",       # 联程名
]


@pytest.mark.parametrize("name", REAL_CASES)
def test_l2_real_domain_no_regression(name):
    cross = "(+1天)"
    base = "%s 21:10→02:35" % name
    picked = _pick(base, cross, d=" 较上轮 ↓100")
    w = _disp_dw(picked)
    assert w <= 40, "%r w=%d" % (picked, w)
    assert "21:10" in picked and "02:35" in picked
    assert cross in picked
    # 剥名档承接（现实域不走保尾地板）：航班号完整在场
    import re
    assert re.search(r"[A-Z0-9]{2}\d{3,4}", picked), (
        "现实域航班号丢失（%r）——现实形态应落剥名档非地板" % picked)
