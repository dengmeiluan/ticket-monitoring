# -*- coding: utf-8 -*-
"""r336 T1/T2：qunar intl allFilters 字典面 → 行级 join。

T1 中转城市「需过境签」：allFilters[filterId=transCitys] 的
detailItems[].labels 白名单词。join 键双通道（r336 波3 P3 收口）：
①码域主通道——detailItemId 即城市码（TPE/LON 实证），链推导转点的
airport_city_code 归一码直查（「台北桃园」=city_name_of('TPE') 产出，
与剥括号归一名「台北」词面域失配曾 7 行零贴签——push 审校 P3）；
②词面兜底通道——title 剥国别括号归一城市名，行级渠道真值 transCity
（无段链可推码）全等查。
T2 航司「廉价航空」：allFilters[filterId=carriers] 同管道，行
binfo.name[] 任一命中即落 lcc=True（normalize `if not f.get("lcc")` 门
天然让位，零新键）——国际廉航 24 行净增量为现行 AIRLINE_LCC 静态表
（12 个国内二字码）不覆盖面。

结构实证（r336_m_fra_frozen.txt 冻结件）：allFilters[].filterId →
details[].detailItems[].title（detailItemTitle 为另一代形态，双态并读）
+ labels 数组 + detailItemId 城市码。
"""
import json
import os

import pytest

from crawlers.qunar import QunarCrawler as _QN


def _filter(det_id, triples):
    """构造单个 filter 块（title+labels+detailItemId 三元组列表）。"""
    return {"filterId": det_id, "filterTitle": "x",
            "details": [{"detailItems": [
                {"title": t, "labels": l, "detailItemId": i}
                for t, l, i in triples]}]}


def _flight(trans_city=None, names=None, reduce=None, code="MU583"):
    """构造最小 intl 行（走通 _extract_intl_flights 时刻链所需键）。

    code 传列表=段链形态（FNO|FROM-TO|DATE），链推导分支产出
    transCity 展示名并保留码域供签证表直查。"""
    info = {"depTime": "08:00", "depDate": "2026-11-16",
            "arrTime": "14:00", "arrDate": "2026-11-16",
            "name": names or ["东方航空"]}
    if trans_city:
        info["transCity"] = trans_city
    f = {"binfo": info, "minPrice": "1000", "code": code}
    if reduce:
        f["reducePriceDesc"] = reduce
    return f


def _tags():
    return _QN._intl_filter_tags({"allFilters": [
        _filter("transCitys", [
            ("不限", None, "default_fcity"),
            ("香港(中国)", [], "HKG"),
            ("台北(中国)", ["需过境签"], "TPE"),
            ("伦敦(英国)", ["需过境签"], "LON"),
            ("曼谷(泰国)", [], "BKK"),
            ("东京(日本)", ["需落地签"], "TYO"),   # 白名单外词不采
        ]),
        _filter("carriers", [
            ("国泰航空", [], "CX"),
            ("马来峇迪航空", ["廉价航空"], "OD"),
            ("春秋航空", ["廉价航空"], "9C"),
        ]),
    ]})


def test_intl_filter_tags_collect():
    visa_code, visa_city, lcc = _tags()
    # 码域主通道：detailItemId 直收（UI 项 default_fcity 非 3 字母码不入）
    assert visa_code == {"TPE": "需过境签", "LON": "需过境签"}
    # 词面兜底通道：剥国别括号归一
    assert visa_city == {"台北": "需过境签", "伦敦": "需过境签"}
    assert lcc == {"马来峇迪航空", "春秋航空"}


def test_trans_visa_by_city_face():
    """渠道真值 transCity（无段链可推码）走词面兜底通道。"""
    tags = _tags()
    rows = _QN._extract_intl_flights(
        [_flight(trans_city="台北")], filter_tags=tags)
    assert rows[0].get("labels") == "需过境签"
    # 多转点任一命中即落（join 语义=行程含该中转地）
    rows2 = _QN._extract_intl_flights(
        [_flight(trans_city="郑州/台北")], filter_tags=tags)
    assert rows2[0].get("labels") == "需过境签"
    # 非过境签中转不落
    rows3 = _QN._extract_intl_flights(
        [_flight(trans_city="郑州")], filter_tags=tags)
    assert "labels" not in rows3[0]


def test_trans_visa_by_seg_code():
    """码域主通道（push 审校 P3 收口）：段链推导行 transCity 展示名
    「台北桃园」与 filter 归一名「台北」词面域失配——链推导转点码
    airport_city_code 归一后直查签证表，全量贴签（7 行零贴签根治）。"""
    rows = _QN._extract_intl_flights(
        [_flight(code=["BR711|PVG-TPE|2026-11-16",
                       "BR87|TPE-CDG|2026-11-16"])], filter_tags=_tags())
    assert rows[0].get("transCity") == "中国台北"   # R55b 一切以携程为准：TPE 官方名中国台北
    assert rows[0].get("labels") == "需过境签"


def test_visa_merges_with_reduce_desc():
    """labels 多值「·」联接（H5 _h5_labels_of 同形态）：降价词在前
    与既有 intl 出口序一致，过境签随后。"""
    rows = _QN._extract_intl_flights(
        [_flight(trans_city="台北", reduce="已减¥100")],
        filter_tags=_tags())
    assert rows[0].get("labels") == "已减¥100·需过境签"


def test_lcc_joins_by_airline_name():
    tags = _tags()
    rows = _QN._extract_intl_flights(
        [_flight(names=["马来峇迪航空"])], filter_tags=tags)
    assert rows[0].get("lcc") is True
    # 全服务航司不落
    rows2 = _QN._extract_intl_flights(
        [_flight(names=["国泰航空"])], filter_tags=tags)
    assert "lcc" not in rows2[0]


def test_no_tags_zero_change():
    """filter_tags 缺省（None/空表）= 既有行为逐字节不变（类名直调
    形态兼容——判例三§12 直调面零破坏）。"""
    for ft in (None, ({}, {}, set())):
        rows = _QN._extract_intl_flights(
            [_flight(trans_city="台北", names=["马来峇迪航空"])],
            filter_tags=ft)
        assert "labels" not in rows[0]
        assert "lcc" not in rows[0]


def test_parse_intl_response_wires_tags():
    """端到端：_parse_intl_response 解出 data 后自动收集双表并接线。"""
    data = {
        "allFilters": [
            _filter("transCitys", [("台北(中国)", ["需过境签"], "TPE")]),
            _filter("carriers", [("马来峇迪航空", ["廉价航空"], "OD")]),
        ],
        "flights": [_flight(trans_city="台北", names=["马来峇迪航空"])],
    }
    flights, risk = _QN._parse_intl_response(
        json.dumps({"bstatus": {"code": 0}, "code": 0,
                    "data": data}, ensure_ascii=False))
    assert risk == ""
    assert flights[0].get("labels") == "需过境签"
    assert flights[0].get("lcc") is True


# ---- 冻结 dump 回放（skipif：debug/ 语料不入库，本地强化 CI 稳定；
# 活文件律——锁结构关系不锚瞬时计数，判例十八§24）----

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_intl_freeze_replay_filter_tags():
    """冻结 FRA dump 过真实解析器入口：贴签行 ⊆ 中转行（join 语义）、
    labels 词域封闭（降价词 ∪ 过境签词）、贴签词=白名单单值；行数只
    设地板不设锚（渠道窗滚动后 transCitys 城市集可变化）。码域主通道
    实效由「贴签行存在且经真实端到端解析」整体背书（r336 波3 P3）。"""
    p = os.path.join(_ROOT, "debug",
                     "qunar_raw_intl_SHA_FRA_2026_11_16.txt")
    if not os.path.exists(p):
        pytest.skip("冻结 dump 缺席（debug/ 不入库）")
    raw = open(p, encoding="utf-8").read()
    if len(raw) < 1000:
        pytest.skip("断供壳语料（硬拒 103B 态）")
    flights, risk = _QN._parse_intl_response(raw)
    assert risk == ""
    assert flights, "登录态满供航线零行（解析链断?）"
    visa = [f for f in flights if "需过境签" in (f.get("labels") or "")]
    for f in visa:
        assert f.get("transCity"), f"贴签行缺中转列：{f.get('code')}"
        for seg in (f.get("labels") or "").split("·"):
            assert seg == "需过境签" or seg.startswith("已减¥"), \
                f"labels 词域越界：{seg!r}"
    assert not [f for f in flights
                if f.get("lcc") and not f.get("name")]
