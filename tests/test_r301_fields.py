# -*- coding: utf-8 -*-
"""r301 数据层两案（TDD 先行，测试全部先红后绿）：

F1 经停城市裸码 AIRPORT_CN 补录——数据观测 P2①：ctrip transCity='JGS'
×8（MU9714/FM9269 航班族，10-13 06:00 首现新形态）两道转写
（crawlers 层 CITY_NAME + normalize 层 AIRPORT_CN）均无 JGS 条目，
裸码透传渲染「经JGS中转」。AIRPORT_CN 有「数据观测补录」家族段
（WDS/UYN/LYA/YCU/MIG/YBP 先例），JGS=井冈山同律补录。

F2 经停停留不可能值守卫——数据观测 P2②：qunar 单行 MU136（共享
FM9269 执飞的营销号，同班同刻同经停点井冈山）stopTime='24小时45分'
vs 全程 '4时20分'——停留是全程的物理子量，≥ 全程必为渠道记录脏值
（恰差 24 小时的档位脏值形态）。normalize 尾段已有中转停留（layover）
同构守卫（lay >= dur 作废归零，qunar H5 %1440 回绕先例），经停停留
stopTimeT 同族扩展。与 layover 擦边档（dur-lay<60）不同型：经停停留
只加「≥ 全程」数学约束档——真值停留恒 < 全程，零误杀面；不加擦边档
（经停 45 分钟量级正常，擦边推理需 OD 相关性已越出数学约束）。
守卫挂 durM 派生之后（用渠道时长被起降差重算后的可信值判定）；
totalDuration 缺席且不可重算的早退分支不触发（宁缺勿错：无真值
可比对不弃值）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r301_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.flightnorm import normalize as _norm


# ---- F1：经停城市 JGS（井冈山）裸码转中文 ----
def test_trans_city_jgs_normalized():
    f = {"name": "上航FM9269", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "transCity": "JGS", "totalDuration": "4时20分"}
    _norm(f, "2027-01-30")
    assert f["transCity"] == "井冈山", f


def test_trans_city_chinese_kept():
    g = {"name": "上航FM9269", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "transCity": "井冈山", "totalDuration": "4时20分"}
    _norm(g, "2027-01-30")
    assert g["transCity"] == "井冈山", g


# ---- F2：经停停留 ≥ 全程必为渠道脏值，stopTimeT 不落 ----
def _base(**kw):
    f = {"name": "东航MU136", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "totalDuration": "4时20分", "stopCitys": "井冈山",
         "stopTime": "24小时45分"}
    f.update(kw)
    return f


def test_stop_time_ge_total_invalid():
    f = _base()
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f
    # 行本体信息不受牵连：经停城市与健康行一样保留
    assert f.get("stopCity") == "井冈山", f
    # 幂等：第二遍 normalize 终态一致（不复活）
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_healthy_kept():
    f = _base(stopTime="45分", code="FM9269", name="上航FM9269")
    _norm(f, "2027-01-30")
    assert f.get("stopTimeT") == "0:45", f


def test_stop_time_equal_total_invalid():
    # 恰等于全程同样是脏值（停留吃满全程=两段飞行 0 分钟，不存在）
    f = _base(stopTime="4时20分")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_no_dur_no_guard():
    # 缺起降时刻走早退分支（durM 永不派生）：守卫不触发，宁缺勿错
    f = {"name": "东航MU136", "price": 1750, "stopCitys": "井冈山",
         "stopTime": "24小时45分"}
    _norm(f, "2027-01-30")
    assert f.get("stopTimeT") == "24:45", f


def test_stop_time_dur_recomputed_guard_holds():
    # totalDuration 缺席但起降在场：时长被起降差重算后守卫仍判定
    f = _base()
    f.pop("totalDuration")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_threedigit_minute_guard_holds():
    # Soldier m2 收口钉：派生侧 :02d 对「N小时M分」M≥100 类词面产
    # 3 位分钟（"6:0"形态族），守卫分钟域 \d+ 宽收不漏（窄于 \d{2}
    # 时此形态静默失明）。样本 4小时120分=360 分钟 ≥ 全程 260 分钟
    f = _base(stopTime="4小时120分")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f
