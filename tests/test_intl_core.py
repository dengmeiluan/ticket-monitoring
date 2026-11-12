# -*- coding: utf-8 -*-
"""国际航班核心契约（r325）：scope 判定/价带分档/国际归一档。

设计单源 docs/INTL_DESIGN.md：
- §1.1 scope 全自动判定（MAINLAND_CODES 剔「中国」前缀条目）
- §1.2 明细元素自描述（intl/tz_dep/tz_arr/tax 键，调用方零改动）
- §1.3 价带分档（国内 50000 / 国际 200000，共享消费端走单源帮手）
- §1.4 flightnorm 国际档（时区修正时长；无时区键绝不朴素重算覆盖）
"""
import datetime as _dt

from core.intl import (INTL_CITY_NAME, INTL_TZ, is_intl_city, is_intl_route,
                       tz_offset_min)
from core.models import price_band_ok, price_max_for
from core.flightnorm import normalize, cross_days


# ---------- §1.1 scope 判定 ----------

def test_is_intl_city_basic():
    assert is_intl_city("NRT") is True
    assert is_intl_city("ICN") is True
    assert is_intl_city("BKK") is True
    assert is_intl_city("SHA") is False
    assert is_intl_city("URC") is False


def test_is_intl_city_hmt_goes_intl():
    # 港澳台在城市字典里带「中国」前缀——OTA 语境其票务走国际体系，
    # scope 判定必须剔除出 MAINLAND_CODES（INTL_DESIGN §1.1）
    assert is_intl_city("HKG") is True
    assert is_intl_city("MFM") is True
    assert is_intl_city("TPE") is True
    assert is_intl_city("KHH") is True


def test_is_intl_city_garbage_and_lower():
    # 非法码不判国际（宁缺勿错）；小写宽容归一
    assert is_intl_city("") is False
    assert is_intl_city("12") is False
    assert is_intl_city("上海") is False
    assert is_intl_city("nrt") is True


def test_is_intl_route():
    assert is_intl_route("SHA", "NRT") is True
    assert is_intl_route("SHA", "URC") is False
    assert is_intl_route("SHA", "HKG") is True
    assert is_intl_route("PVG", "TPE") is True
    assert is_intl_route("KHN", "SHA") is False


def test_intl_city_name_and_tz_invariant():
    # 字典自洽不变量：有名必有区（无区的目的地时长修正会静默失明）
    assert INTL_CITY_NAME["NRT"] == "东京成田"
    assert INTL_CITY_NAME["ICN"] == "首尔仁川"
    # 双场城市展示名=场级全名（官方全集合并只补充不覆盖——裸 update
    # 曾把精选正名盖回城市级短名：字面量在场而运行时被覆盖，钉字面量
    # 的钉抓不住，必须钉运行时真值）
    # R55b 用户令一切以携程为准：官方城市名「曼谷」（字典有 DMK 曼谷
    # 廊曼，无双场歧义；本场级全名钉随官方口径改写）
    assert INTL_CITY_NAME["BKK"] == "曼谷"
    assert INTL_CITY_NAME["DMK"] == "曼谷廊曼"
    assert INTL_CITY_NAME["LHR"] == "伦敦希思罗"
    for code in INTL_CITY_NAME:
        assert code in INTL_TZ, code


def test_tz_offset_min_dst_correct():
    # zoneinfo 实时算偏移：10 月中纽约仍在夏令时（EDT -240）、伦敦
    # 仍在 BST（+60，10 月最后周日切换）；11 月初双双落回标准时——
    # 静态数字表在这两处都会错 1 小时，必须钉 DST 双侧
    oct_day = _dt.datetime(2026, 10, 17, tzinfo=_dt.timezone.utc)
    assert tz_offset_min("NRT", oct_day) == 540
    assert tz_offset_min("LHR", oct_day) == 60      # BST 尾段
    assert tz_offset_min("JFK", oct_day) == -240    # EDT
    nov_day = _dt.datetime(2026, 11, 5, tzinfo=_dt.timezone.utc)
    assert tz_offset_min("LHR", nov_day) == 0       # GMT
    assert tz_offset_min("JFK", nov_day) == -300    # EST
    assert tz_offset_min("ZZZ") is None
    # 大陆码恒 +480（全国统一 UTC+8 无夏令时）——跨区判定需要两端
    # 偏移都已知；大陆码不在 INTL_TZ 表，缺这条恒值 SHA 端会拿 None
    assert tz_offset_min("SHA") == 480
    assert tz_offset_min("URC") == 480


# ---------- §1.3 价带分档 ----------

def test_price_max_for_scope():
    assert price_max_for("SHA", "URC") == 50000
    assert price_max_for("SHA", "NRT") == 200000
    assert price_max_for("SHA", "HKG") == 200000


def test_price_band_ok():
    assert price_band_ok(35000, "SHA", "URC") is True
    assert price_band_ok(60000, "SHA", "URC") is False
    assert price_band_ok(60000, "SHA", "NRT") is True
    assert price_band_ok(190000, "PEK", "LHR") is True
    assert price_band_ok(200001, "PEK", "LHR") is False
    assert price_band_ok(99, "SHA", "NRT") is False
    assert price_band_ok("abc", "SHA", "NRT") is False
    assert price_band_ok(None, "SHA", "NRT") is False


# ---------- §1.4 flightnorm 国际档 ----------

def _intl_lax_row(**over):
    f = {"intl": 1, "name": "东航MU583", "depTime": "12:00",
         "arrTime": "09:30", "depDate": "2026-10-17",
         "arrDate": "2026-10-18", "tz_dep": 480, "tz_arr": -420,
         "totalDuration": "36时30分", "price": 2880, "transCity": ""}
    f.update(over)
    return f


def test_intl_duration_tz_corrected():
    # PVG(+8) 12:00 → LAX(-7) 次日 09:30：真时长 36时30分=2190 分。
    # 本地朴素差只有 21时30分（差 15h 时区）——带时区键必须重算出真值
    f = normalize(_intl_lax_row())
    assert f["crossDayN"] == 1
    assert f["durM"] == 2190
    assert f["totalDuration"] == "36时30分"


def test_intl_duration_channel_trusted_without_tz():
    # 无时区键的国际行：本地朴素重算系统性错 ±小时级——渠道结构化
    # 时长必须原信（±15 分钟覆盖窗不得用朴素值触发，宁信渠道）
    f = normalize(_intl_lax_row(tz_dep=None, tz_arr=None,
                                totalDuration="36时30分"))
    assert f["durM"] == 2190          # 渠道值原样保留
    f2 = normalize(_intl_lax_row(tz_dep=None, tz_arr=None,
                                 totalDuration="12时30分"))
    assert f2["durM"] == 750          # 朴素重算会说 1290——不许覆盖


def test_intl_cross_day_cap_widened():
    # 长衔接国际行程 +5 天合法（国内档上限 3 不适用）
    f = _intl_lax_row(arrDate="2026-10-22", totalDuration="")
    assert cross_days(f, "2026-10-17") == 5
    assert normalize(dict(f))["crossDayN"] == 5


def test_domestic_row_untouched_by_intl_keys():
    # 国内行（无 intl 键）行为零变更：无时区键走原朴素重算路径
    f = {"name": "南航CZ6800", "depTime": "08:00", "arrTime": "11:30",
         "depDate": "2026-10-17", "totalDuration": "3时30分",
         "price": 800}
    g = normalize(f)
    assert g["crossDayN"] == 0
    assert g["durM"] == 210
    # 渠道时长谎报时国内档照旧用朴素重算纠正（±15 分钟窗外）
    f2 = dict(f, totalDuration="9时30分")
    assert normalize(f2)["durM"] == 210


def test_intl_element_carries_tax_keys_through():
    # tax/currency 是元素自由键：normalize 不得吞键/改写
    f = _intl_lax_row(tax=520, currency="CNY")
    g = normalize(f)
    assert g["tax"] == 520
    assert g["currency"] == "CNY"
