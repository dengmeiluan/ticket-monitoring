# -*- coding: utf-8 -*-
"""回归：qunar PC binfo2 经停两键回退（b1 优先 b2 兜底）+
qunar PC binfo.transNotice「华夏联程」并入 labels（H5 同源同律）+
qunar H5 stopCitys 前导「;」伪影清洗 + tongcheng 行级直挂证据
（stss ServiceType=LUGGAGE 双门 → transferBaggage='direct'）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v162_fields.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402


# ---- qunar PC：binfo2 经停两键回退（挂起④阈值 ≥3/144 触发，
# 调研样本 GS7511/HO1108 二段停陇南；binfo2.stopTime 键级不存在，
# 挂起三元组缩两键——stopTime 维持 binfo 层现状） ----

def _pc_flight(**kw):
    f = {"code": "GS7511/HO1108", "minPrice": "2472", "transCity": "兰州",
         "binfo1": {"airCode": "HO1108", "shortName": "吉祥",
                    "depTime": "08:00", "arrTime": "10:30",
                    "date": "2026-10-06", "arrDate": "2026-10-06",
                    "stopCitys": [], "stopAirports": []},
         "binfo2": {"depTime": "12:30", "arrTime": "14:40",
                    "arrDate": "2026-10-06",
                    "stopCitys": [], "stopAirports": []}}
    f.update(kw)
    return f


def _pc_text(*flights):
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": list(flights)}})


def test_qunar_pc_stopcitys_binfo2_fallback():
    """b1 空数组时回退 binfo2（中转二段经停真值位，13:20/13:21 dump
    3/144：GS7511/HO1108 二段停陇南）；b1 有值优先不回退；直飞行
    （无 binfo2）行为零变化；join 后剥前导/尾部分隔符伪影（H5
    「,庆阳」同型卫生）。"""
    f = _pc_flight()
    f["binfo2"]["stopCitys"] = ["陇南"]
    f["binfo2"]["stopAirports"] = ["陇南成县机场"]
    fl = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl[0]["stopCitys"] == "陇南"
    assert fl[0]["stopAirports"] == "陇南成县机场"
    # b1 有值优先
    f2 = _pc_flight()
    f2["binfo1"]["stopCitys"] = ["张掖"]
    fl2 = QunarCrawler._parse_pc_flights(_pc_text(f2), "2026-10-06")
    assert fl2[0]["stopCitys"] == "张掖"
    # 直飞行（binfo 形态、无 binfo2）b1 值照采、空数组落空串
    direct = {"code": "FM9223", "minPrice": "2472", "transCity": "",
              "binfo": {"airCode": "FM9223", "shortName": "上航",
                        "depTime": "19:55", "arrTime": "01:25",
                        "date": "2026-10-06", "arrDate": "2026-10-07",
                        "stopCitys": ["银川"], "stopAirports": []}}
    fl3 = QunarCrawler._parse_pc_flights(_pc_text(direct), "2026-10-06")
    assert fl3[0]["stopCitys"] == "银川"
    # 数组含空串元素（渠道「,庆阳」变体）：join 出「;庆阳」剥成「庆阳」
    f4 = _pc_flight()
    f4["binfo2"]["stopCitys"] = ["", "庆阳"]
    fl4 = QunarCrawler._parse_pc_flights(_pc_text(f4), "2026-10-06")
    assert fl4[0]["stopCitys"] == "庆阳"
    # b1 全空元素不阻断回退（：join 真值判「;」曾吃掉 b2 真值）
    f5 = _pc_flight()
    f5["binfo1"]["stopCitys"] = [""]
    f5["binfo2"]["stopCitys"] = ["陇南"]
    fl5 = QunarCrawler._parse_pc_flights(_pc_text(f5), "2026-10-06")
    assert fl5[0]["stopCitys"] == "陇南"


# ---- qunar PC：binfo.transNotice 并入 labels（H5 层级修复
# 同款信号，PC _labels_of 只读 priceLabel 漏读，4/144 且 3/4 行
# priceLabel 为空=背书整行丢失） ----

def test_qunar_pc_labels_transnotice_merged():
    """「华夏联程」航司自营联程背书：b1 层（binfo/binfo1）主源、顶层
    兜底，「转/停」占位排除——与 H5 _h5_labels_of 同律；去重；
    _LABEL_MAX=3 容量不足时不挤掉 priceLabel 现有名。"""
    f = _pc_flight()
    f["binfo1"]["transNotice"] = "华夏联程"
    fl = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl[0]["labels"] == "华夏联程"
    # 与 priceLabel 共存：去重联接
    f["priceLabel"] = [{"name": "联程航班服务"}]
    fl2 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl2[0]["labels"] == "联程航班服务·华夏联程"
    # 占位排除：顶层「转」不采（PC 顶层若下发占位形态）
    f["binfo1"]["transNotice"] = ""
    f["transNotice"] = "转"
    fl3 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl3[0]["labels"] == "联程航班服务"
    # 容量 3 满时不挤掉既有名（priceLabel 全决策词优先）
    f["transNotice"] = "华夏联程"
    f["priceLabel"] = [
        {"name": "取消延误免费改"}, {"name": "宠物友好"}, {"name": "免费上网"}]
    fl4 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl4[0]["labels"] == "取消延误免费改·宠物友好·免费上网"


# ---- qunar H5：stopCitys 前导「;」伪影（渠道「,庆阳」经 
# 逗号归一成「;庆阳」，strip(";") 判空放行了前导分隔符，DB 99 行） ----

def _h5_row(**extra):
    f = {"minPrice": 1200, "code": "HO1068/CZ6798",
         "mixFlightName": "吉祥HO1068", "transCity": "庆阳",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f.update(extra)
    return f


def test_qunar_h5_stopcitys_leading_separator():
    """「,庆阳」→ 归一「;庆阳」→ 剥前导分隔符「庆阳」；尾分隔符同律；
    纯分隔符「,」维持空串（口径不回退）；多城真值不受影响。"""
    cases = ((",庆阳", "庆阳"), ("庆阳,", "庆阳"),
             ("西安,库尔勒", "西安;库尔勒"), (",", ""))
    for raw, want in cases:
        f = _h5_row(binfo={"depTime": "16:40", "arrTime": "21:30",
                           "depDate": "2026-10-06", "arrDate": "2026-10-06",
                           "stopsCitys": raw, "stopsAirPort": raw})
        rows = QunarCrawler._extract_flights_obj([f])
        assert rows[0]["stopCitys"] == want, raw
        assert rows[0]["stopAirports"] == want, raw


# ---- tongcheng：行级直挂证据（stss ServiceType=LUGGAGE 双门 →
# transferBaggage='direct'；现版页面级 doc 图例五词恒全并存，
# direct_only 恒 False → 全库 direct=0 真实信息损失，DB 44 行/日） ----

def _tc_transfer_fp(stss=None, doc=None):
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "GS7511", "aat": "T3"},
                 {"fn": "HO1108", "dat": "T5"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    if stss is not None:
        fp["stss"] = stss
    _doc = {"luggageSelf": 1, "luggageAgain": 1}  # 两日 dump 恒全并存形态
    if doc:
        _doc.update(doc)
    return json.dumps({"data": {"fps": [fp], "doc": _doc}})


def _tc_bag(text):
    rows = TongchengCrawler._extract_transfer_flights(text)
    return rows[0]["transferBaggage"]


def test_tongcheng_transfer_baggage_row_evidence():
    """行级双门：ServiceType=='LUGGAGE' 且 ServiceName 白名单（行李
    直达/免提取托运行李）才置 direct；LUGGAGE_DEPOSIT（免费行李寄存）
    与缺 ServiceType 不混入（宁缺勿错）。"""
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}])) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "免提取托运行李"}])) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE_DEPOSIT",
         "ServiceName": "免费行李寄存"}])) == ""
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceName": "行李直达"}])) == ""
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "TRANSFER_HOTEL", "ServiceName": "免费住宿"}])) == ""


def test_tongcheng_transfer_baggage_lcc_guard():
    """任段廉航不落（flightnorm「春秋大概率不直挂」同律）：9C 段+
    行级证据不置 direct；全干线照置。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "9C7372", "aat": "T3"},
                 {"fn": "HO1068", "dat": "T5"}],
          "stss": [{"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    text = json.dumps({"data": {"fps": [fp],
                                "doc": {"luggageSelf": 1,
                                        "luggageAgain": 1}}})
    assert _tc_bag(text) == ""


def test_tongcheng_transfer_baggage_legacy_legend_path():
    """图例唯一含 luggageSelf（无 luggageAgain）→ direct（    既有路径零回退）；图例全并存+行级证据 → direct（行级证据救回）。"""
    assert _tc_bag(_tc_transfer_fp(
        doc={"luggageSelf": 1, "luggageAgain": 0})) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}],
        doc={"luggageSelf": 1, "luggageAgain": 1})) == "direct"
    # 图例全并存+无行级证据维持空（三态「空=未知」语义不破）
    assert _tc_bag(_tc_transfer_fp()) == ""
