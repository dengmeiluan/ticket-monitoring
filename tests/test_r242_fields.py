# -*- coding: utf-8 -*-
"""r242 数据层回归钉。

Q-1（渠道报文调研立案）：qunar PC 主路径 plane 词面源换源——
planeType 机读码（'73P'/'738'/'32Q' 读者读不出，新代 DB 422 条目
100% 机读形态）→ planeFullType 可读形态（'波音737(中)' 139/139
在场，其中 118 带体量括号 + 21 裸机型）；机读码源随换源退役，
垃圾占位词不落（宁缺勿错），无值不落键（r241 残留族同口径）。
消费面零改动：flightnorm.cabin_text .get 门 + alerter 跨渠道补全
白名单既有通道（渠道载荷形态差异由消费端宽容形态承载）。

样本形态取自生产冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r242_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("r242")
_QC = QunarCrawler({}, _LOG)


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（data.flights 普通数组形态）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    return json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_qunar_pc_plane_fulltype_readable():
    """可读形态照落：带体量括号 '波音737(中)'（与 H5 plane 同形）；
    planeSize 体量正则同源不受扰。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "738",
                              "planeFullType": "波音737(中)"})]),
        "2026-10-05")
    assert rows[0]["plane"] == "波音737(中)", rows[0]
    assert rows[0]["planeSize"] == "中型机", rows[0]


def test_qunar_pc_plane_bare_form_kept():
    """裸机型照落（planeFullType 是结构化满勤字段，'737-800' 读者
    可读——与 H5 binfo.name[1] 的 fullmatch 锚定拒裸形不同域：
    PC 换源后裸形是干净真值非脏形态）；体量正则不命中 planeSize
    不落（宁缺勿错既有门）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "73M",
                              "planeFullType": "波音737MAX8"})]),
        "2026-10-05")
    assert rows[0]["plane"] == "波音737MAX8", rows[0]
    assert "planeSize" not in rows[0], rows[0]
    rows2 = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "738",
                              "planeFullType": "737-800"})]),
        "2026-10-05")
    assert rows2[0]["plane"] == "737-800", rows2[0]


def test_qunar_pc_plane_junk_words_dropped():
    """渠道垃圾占位词不落（调研值域实证两形态）；planeSize 本就
    正则不命中，零连带。"""
    for junk in ("机型未定", "其他机型"):
        rows = QunarCrawler._parse_pc_flights(
            _pc_text([_pc_flight({"planeType": "",
                                  "planeFullType": junk})]),
            "2026-10-05")
        assert "plane" not in rows[0], (junk, rows[0])
        assert "planeSize" not in rows[0], (junk, rows[0])


def test_qunar_pc_plane_missing_fulltype_never_falls_back():
    """planeFullType 缺席 → plane 键不落：机读码源随换源退役，
    不回落 planeType（机读码读者零增量，回落即垃圾复辟）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight({"planeType": "73P"})]), "2026-10-05")
    assert "plane" not in rows[0], rows[0]


def test_qunar_pc_plane_transfer_row_same_source():
    """中转行同源换采（binfo1.planeFullType 首段机型，与既有
    plane 取数槽位一致）；二段信息不并（行级机型语义=首段执飞）。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([
        _pc_flight({"planeType": "73P", "planeFullType": "空客320(中)"},
                   b2={"depTime": "13:30", "arrTime": "17:20",
                       "date": "2026-10-05", "arrDate": "2026-10-05",
                       "shortCarrier": "CZ", "airCode": "6940",
                       "planeType": "738",
                       "planeFullType": "波音737(中)"},
                   transCity="西安")]),
        "2026-10-05")
    assert rows[0]["plane"] == "空客320(中)", rows[0]
    assert rows[0]["planeSize"] == "中型机", rows[0]


# ---- H5 兜底路径同族收口（r242 after 观测 r1 抓漏：meal/baggage/plane
# 三键 H5 行构造器仍恒落空串——中转行 48/48 平铺，r241 收口 8 键的
# H5 侧余量；与 PC 出口同轮对齐为「无值不落键」）----

def _h5_row(**kw):
    """H5 行最小载体（无 addon/无机型词面的中转行形态）。"""
    f = {"minPrice": 1288, "code": "CZ3544/CZ6940", "transCity": "武汉",
         "binfo1": {"depTime": "21:40", "arrTime": "00:50",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"},
         "binfo2": {"depTime": "11:30", "arrTime": "14:00",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"}}
    f.update(kw)
    return json.dumps({"data": {"flights": [f]}}, ensure_ascii=False)


def test_qunar_h5_plane_meal_baggage_no_value_no_key():
    """H5 无值不落键：无 addon 信息且 binfo.name 无机型词面的行
    （生产中转行 48/48 实录形态），plane/meal/baggage 三键整键缺席
    （旧形为空串落库——与 PC 出口 walrus 门同口径）。"""
    rows = QunarCrawler._parse_response_flights(_h5_row())
    f = rows[0]
    for k in ("plane", "meal", "baggage"):
        assert k not in f, (k, f)


def test_qunar_h5_plane_meal_baggage_values_kept():
    """有值照落：机型词面（binfo.name[1] fullmatch 命中形态）与餐食/
    托运 addon 词面三键正常在位，词面与旧形一致。"""
    rows = QunarCrawler._parse_response_flights(_h5_row(
        binfo1={"depTime": "08:00", "arrTime": "10:00",
                "depDate": "2026-10-05", "arrDate": "2026-10-05",
                "name": ["春秋", "波音737(中)"]},
        flightAddInfoIntegration={"flightAdditionInfos": [
            {"name": "有餐", "icon": "x"},
            {"name": "免费托运20KG", "icon": "y"}]}))
    f = rows[0]
    assert f["plane"] == "波音737(中)", f
    assert f["planeSize"] == "中型机", f
    assert f["meal"] == "有餐", f
    assert f["baggage"] == "免费托运20KG", f
