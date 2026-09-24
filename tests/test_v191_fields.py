# -*- coding: utf-8 -*-
"""渠道字段第九批回归：fliggy「有餐食」正向标签（has-food-label 双
态——机型行同 <p> 容器 innerText 同位，10-05/10-06 dump 实证 CZ6917
等 4 班在打正向标，推翻「渠道只标无餐食」旧定性）并入既有 meal 键，
消费端（normalize/webui/推送）零改动。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v191_fields.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402

_LOG = logging.getLogger("t1591")


# ---- fliggy：has-food-label 双态 ----

def test_fliggy_meal_positive_label():
    """机型行同行尾「有餐食」正向标签落 meal 既有键，值与负向同槽；
    无标签行仍不落（不打标）。"""
    txt = ("南航CZ6917\n中型机 737 有餐食\n09:15\n13:50\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥920 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "CZ6917"]
    assert hit and hit[0]["meal"] == "有餐食", rows


def test_fliggy_meal_negative_label_unregressed():
    """负向「无餐食」行为不变（双态扩充零回归）。"""
    txt = ("春秋9C7006\n中型机 320 无餐食\n15:15\n21:30\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥620 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "9C7006"]
    assert hit and hit[0]["meal"] == "无餐食", rows


def test_fliggy_meal_transfer_second_leg_positive():
    """中转块二段机型行「有餐食」随 pend 搬运进合并行（与负向同值
    域同路径），首段已标时不覆盖（setdefault）。"""
    txt = "\n".join([
        "南航CZ8232", "中型机 73N",           # 首段（pend，无标签）
        "南航CZ8232", "中型机 73N 有餐食",    # 二段（cur，正向）
        "10月06日 08:00", "10月06日 11:05",   # 首段起/落
        "10月06日 12:20", "10月06日 14:30",   # 二段起/落
        "乌鲁木齐天山国际机场", "兰州中转", "虹桥国际机场T2",
        "100.0%", "约7小时",
        "¥1180 5.5折", "¥120机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    hit = [r for r in rows if r.get("code") == "CZ8232/CZ8232"]
    assert hit and hit[0].get("meal") == "有餐食", rows


# ---- tuniu：discount 空串占位键卫生（观测 before：35/611≈5.7% 空串
# 落键，avgDelay 无值不落键同族） ----

_TN_FLIGHT = {
    "airlineCompany": "东航",
    "departureTime": "20:20", "arrivalTime": "01:15",
    "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
    "flightTime": "295",
}


def _tn_row_disc(fare_discount):
    d = dict(_TN_FLIGHT)
    raw = {"data": {"fareList": [{
        "flightOptions": [{"flightNos": "MU8370"}],
        "flightPriceList": [{"fareBreakdownList": [
            {"baseFare": 3600, "psgType": "ADT",
             "discount": fare_discount}]}],
    }], "flightList": {"MU8370#2026-10-06#URC#SHA": d}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows
    return rows[0]


def test_tuniu_discount_value_kept():
    """有值「6.7折」照落（正路零变化）。"""
    assert _tn_row_disc("6.7折")["discount"] == "6.7折"


def test_tuniu_discount_empty_no_key():
    """空串：无值不落键（avgDelay 同族键卫生）。"""
    assert "discount" not in _tn_row_disc("")


def test_tuniu_discount_zero_placeholder_no_key():
    """「0」占位：_adt_fare 既有过滤后落空串——一并转无键。"""
    assert "discount" not in _tn_row_disc("0")


def test_tuniu_discount_missing_no_key():
    """报文无 discount 字段：不落键（原空串占位形态关闭）。"""
    d = dict(_TN_FLIGHT)
    raw = {"data": {"fareList": [{
        "flightOptions": [{"flightNos": "MU8370"}],
        "flightPriceList": [{"fareBreakdownList": [
            {"baseFare": 3600, "psgType": "ADT"}]}],
    }], "flightList": {"MU8370#2026-10-06#URC#SHA": d}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows and "discount" not in rows[0]


def test_fliggy_meal_transfer_conflict_conservative():
    """中转两段餐食标签相反：合并行保守仲裁为「无餐食」（一段无
    餐食=全程存在无餐食段，正向优先会掩蔽该事实）。"""
    txt = "\n".join([
        "南航CZ6646", "中型机 32N 无餐食",    # 首段（pend）负向
        "南航CZ6646", "中型机 32N 有餐食",    # 二段（cur）正向（掩蔽场景）
        "10月06日 08:00", "10月06日 11:05",   # 首段起/落
        "10月06日 12:20", "10月06日 14:30",   # 二段起/落
        "乌鲁木齐天山国际机场", "兰州中转", "虹桥国际机场T2",
        "100.0%", "约7小时",
        "¥1180 5.5折", "¥120机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    hit = [r for r in rows if r.get("code") == "CZ6646/CZ6646"]
    assert hit and hit[0].get("meal") == "无餐食", rows
