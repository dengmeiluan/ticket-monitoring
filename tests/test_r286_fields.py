# -*- coding: utf-8 -*-
"""r286 数据层：qunar H5 餐食词面域补「小食」。

背景（2027 春节档 4 份 browser dump 221 行独立复核）：HO 系吉祥
小食班次 flightAdditionInfos 全集 = ['小食','免费托运20KG','廊桥登
机率--','起飞准点率--','平均延误--','WiFi未知']——「小食」是行内唯
一餐食词，现行提取门（含「餐/点心」）不命中 → meal 整键缺席，托运
键正常。值域全量普查：含「小食」子串的词仅「小食」本身，补词零误
采面。与 ctrip classinfor「有小食」跨渠道对齐。"""
import json

from crawlers.qunar import QunarCrawler, _meal_from_addons


def _h5_flight(add_names, code="HO1087"):
    """真实 dump 形态：HO 系小食班次 additionInfos 全集按 01-29 报文。"""
    return {
        "minPrice": 1760, "code": code,
        "flightAddInfoIntegration": {"flightAdditionInfos": [
            {"name": nm, "icon": "i"} for nm in add_names]},
        "binfo": {"depTime": "08:15", "arrTime": "11:05",
                  "depDate": "2027-01-29", "arrDate": "2027-01-29"},
    }


def test_meal_gate_recognizes_snack():
    """提取门认「小食」：现行门（餐/点心）不命中 → meal 缺席；
    补词后返回「小食」原文。"""
    integ = {"flightAdditionInfos": [
        {"name": "小食", "icon": "i"},
        {"name": "免费托运20KG", "icon": "j"}]}
    meal, baggage = _meal_from_addons(integ)
    assert meal == "小食", meal
    assert baggage == "免费托运20KG", baggage


def test_meal_gate_snack_not_shadowed_by_placeholder_words():
    """占位词不在场时不误抬：仅托运+监控占位词的行 meal 仍缺席。"""
    integ = {"flightAdditionInfos": [
        {"name": "免费托运20KG", "icon": "i"},
        {"name": "廊桥登机率--", "icon": "j"},
        {"name": "WiFi未知", "icon": "k"}]}
    meal, baggage = _meal_from_addons(integ)
    assert meal == "", meal
    assert baggage == "免费托运20KG", baggage


def test_h5_parse_meal_snack_lands():
    """全链路：解析出口 meal='小食' 落键（dump 实证形态 6/221 行）。"""
    text = json.dumps({"data": {"flights": [
        _h5_flight(["小食", "免费托运20KG", "廊桥登机率--",
                    "起飞准点率--", "平均延误--", "WiFi未知"]),
        # 对照行：真无餐食词的行键仍缺席（无值不落键收口不回退）
        _h5_flight(["免费托运20KG", "WiFi未知"], code="HO1273"),
    ]}})
    rows = QunarCrawler._parse_response_flights(text)
    assert rows[0]["meal"] == "小食", rows[0]
    assert "meal" not in rows[1], rows[1]
