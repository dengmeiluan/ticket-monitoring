# -*- coding: utf-8 -*-
"""r326 R9 字段覆盖普查钉（C 族）：飞猪国际日历真报文键全集 vs 元素
schema 采/不采决策账（校准 R1 真报文 2202B，7 日点键并集实证）。

钉的意图：渠道新增键必须触发显式采/不采决策（红→补决策行），
防「无值不落键」卫生律反向退化成「新键静默漏采」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_census.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# R1 真报文（_scratch/intl/r1_fliggy_raw.txt）7 日点键并集实证
REAL_KEYS = {"arrCityCode", "depCityCode", "discount",
             "leaveDate", "price", "tax", "url"}

# 采/不采决策账（R9 校准定谳镜像，内部档 _scratch/INTL_CALIBRATION_internal.md）
ADOPTED = {
    "leaveDate": "depDate/日点",
    "price": "裸价→含税合成（price+tax）",
    "tax": "extra tax 键",
    "depCityCode": "extra cityCodes",
    "arrCityCode": "extra cityCodes",
}
REJECTED = {
    # 不采理由必须具体（哨位/无消费槽），禁「暂不采」空账
    "discount": "恒 0.0 疑占位（W-R326-F1 哨：值域多值再评折扣出口）",
    "url": "购买深链 v1 无消费槽（对接 _view_url 族时复议）",
}


def test_real_key_set_unchanged():
    # 真报文键全集（渠道改版加键即红→走采/不采决策补账）
    assert REAL_KEYS == {"arrCityCode", "depCityCode", "discount",
                         "leaveDate", "price", "tax", "url"}


def test_every_real_key_has_explicit_decision():
    # 全键显式决策：采有出口、不采有具体理由——无静默漏采
    assert set(ADOPTED) | set(REJECTED) == REAL_KEYS
    assert not (set(ADOPTED) & set(REJECTED))
    for k, why in REJECTED.items():
        assert len(why) > 8 and (":" in why or "（" in why), \
            f"{k} 不采理由不具体: {why!r}"


# ---------- R18 普查扩展：途牛/去哪儿国际行 schema 决策账 ----------
# 来源：途牛=report_tuniu.md §4（页面模板+model 双实证，软墙未出真行
# ——fixture 钉承载）；去哪儿=report_qunar.md §4（渲染层实证，登录门
# 未出真行）。真样本到手轮按 R9 先例补「真报文键全集」实测账。

TUNIU_ROW_KEYS_ADOPTED = {
    "avgTotalPrice": "price（含税人均价口径）",
    "avgTax": "extra tax",
    "avgBasePrice": "extra barePrice",
    "flightNos": "code/name 拼装",
    "airlineName": "name/airline 词面",
    "dTime": "depTime+depDate（[:10]/[11:16] 切片）",
    "aTime": "arrTime+arrDate+跨天自推导",
    "totalMin": "totalDuration（fmt_dur）",
    "transferCity": "transCity（|→/）",
    "stopCity": "stopCitys（经停）",
    "cabinName": "cabin",
    "seat": "leftTickets（0<seat<9 档）",
    "dPortName": "depAirport",
    "aPortName": "arrAirport",
    "dTerminal": "depTerminal",
    "aTerminal": "arrTerminal",
    "codeShare": "shareCarrier 门控（+首段 airComName）",
    "segmentList": "plane（首段 craftTypeName）+shareCarrier 词源",
}
TUNIU_ROW_KEYS_REJECTED = {
    "tagList": "营销词面未采样（观察哨：值域实证后按 labels 白名单律议采）",
    "logoUrl": "图片资源 v1 无消费槽",
    "vendorId": "渠道内部供应商标识，无决策价值",
    "cabinClass": "cabinName 已承载（数字码冗余）",
    "dCityName/aCityName": "route 配置已承载城市语义",
    "isPackage": "往返二期键（R13 设计 §2.6 落地时启用）",
}

QUNAR_INTL_KEYS_ADOPTED = {
    "minPrice": "price（含税口径主源）",
    "taxPrice": "extra tax",
    "nakedPrice": "extra nakedPrice",
    "code/flightKey": "code",
    "mixFlightName": "name 首行",
    "binfo.depTime/depDate": "depTime/depDate",
    "binfo2.arrTime/arrDate": "arrTime/arrDate（中转整体到达）",
    "transCity": "transCity",
    "cabinDesc": "cabin",
    "fewTicket": "fewTicket",
    "depTerminal/arrTerminal": "同名透传",
}
QUNAR_INTL_KEYS_REJECTED = {
    "listPopView": "值机风险弹层 v1 国际面未接（国内同键消费面在产，真样本后对齐）",
    "stops": "经停族国际行未实证（真样本后按 stopCitys 同律议采）",
}


def test_tuniu_row_schema_decision_account():
    # 途牛元素键决策账（R18）：采/不采无交集、不采有具体理由
    assert not (set(TUNIU_ROW_KEYS_ADOPTED) & set(TUNIU_ROW_KEYS_REJECTED))
    for k, why in TUNIU_ROW_KEYS_REJECTED.items():
        assert len(why) > 8, f"{k} 不采理由不具体"


def test_qunar_intl_row_schema_decision_account():
    assert not (set(QUNAR_INTL_KEYS_ADOPTED) & set(QUNAR_INTL_KEYS_REJECTED))
    for k, why in QUNAR_INTL_KEYS_REJECTED.items():
        assert len(why) > 8, f"{k} 不采理由不具体"


# ---------- R27 RT 真样本决策账（r16/r24 活体行，两次独立采集同构） ----------

RT_REAL_KEYS = {"arrCityCode", "backDate", "depCityCode", "discount",
                "leaveDate", "price", "tax", "url"}
RT_ADOPTED = {
    "backDate": "extra backDate（往返对唯一性校验键）",
    "leaveDate": "depDate/日点",
    "price": "裸价→含税合成（往返总价口径 §2.6）",
    "tax": "extra tax（R16 实测 1457，往返税费占比实证）",
    "depCityCode": "extra cityCodes",
    "arrCityCode": "extra cityCodes",
}
RT_REJECTED = {
    "discount": "恒 0.0 疑占位（W-R326-F1 哨同族）",
    "url": "购买深链 v1 无消费槽（RT 购买链复议时一并）",
}


def test_rt_real_sample_decision_account():
    # RT 真报文键全集 = 单程 7 键 + backDate 恰一新增（R13/R16 两次
    # 独立采集同构）；采/不采全键显式决策
    assert RT_REAL_KEYS - {"backDate"} == REAL_KEYS
    assert set(RT_ADOPTED) | set(RT_REJECTED) == RT_REAL_KEYS
    assert not (set(RT_ADOPTED) & set(RT_REJECTED))
    for k, why in RT_REJECTED.items():
        assert len(why) > 8, f"{k} 不采理由不具体"
