# -*- coding: utf-8 -*-
"""数据层字段面：渠道报文新增语义载体与舱位伪语义出口收口。

ctrip riskPolicy 第二源：classinfor.classNoteList nt=3 词表含独立词
HighRisk（12/218 行两 dump 复现）——这些行 nt=104 报价载荷全部空转
（priceInfoList 零 HighRiskPolicy 条目），语义只此一载体。配对门与
nt=104 价门同构：旗标挂最低价政策才落（带旗政策==行最低价 12/12
dump 实证），词面复用「高风险政策」零新键。

ctrip labels「超级经济舱」：nt=3 PremiumEcoProduct 旗标（5/218 稀疏
两 dump 复现，S 舱 4.4/5.8 折座椅倾斜 100°）——cabin=经济舱+cabinCode=S
不透明，该档位语义无任何既有出口承载。随最低价政策配对（同上），
labels 通道零新键。

qunar PC cabin 撤伪：binfo1.cabin 与 H5 cabinDegree 跨源逐行全等
15/15（r222 已定谳 H5 侧为「段级折扣桶冒充行级舱位」撤伪），两字符
'R3' 漂移已在场——同一伪语义出口的 PC 半程缺角，同案不落。消费端
cabin_clean/cabin_class 对存量行照常守卫（DB 原值不动）。

cabin_clean 复合高档词：查纯域从精确等值扩为词族子串（「豪华公务舱」
等复合高档词须整体命中词族成员，等值匹配留缺口）；「超级经济舱」
等经济词族不含高档词子串不受影响。

cabin_text cabinName 分支接同一守卫：cabinName 是 cabin 的同语义
载体（当前零生产者，未来渠道直出高档词不得绕过价格硬证）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15123_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.flightnorm import cabin_clean, cabin_text  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("t15123")
_CT = CtripCrawler({}, _LOG)


def _ctrip_one(item):
    rows = CtripCrawler._extract_ctrip_flights(_CT, json.dumps([item]))
    assert rows
    return rows[0]


def _ctrip_seg(dd="2026-10-06 16:40:00", ad="2026-10-06 21:30:00",
               flgno="MU5633"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _policy(price=2410, qty=5, nt3=None):
    """政策 fixture：classinfor 单元素（直飞 1 段==1 元素，全元素
    扫描结构门成立），nt3=词表串（notecnt 原样，逗号形态同 dump）。"""
    ci = {"cgrd": 0}
    if nt3:
        ci["classNoteList"] = [{"notetype": 3, "notecnt": nt3}]
    return {"tprice": price, "quantity": qty, "drate": 5.2,
            "classinfor": [ci]}


# ---- ctrip riskPolicy 第二源：nt=3 HighRisk 旗标 ----

def test_ctrip_riskpolicy_nt3_flag_lands():
    """最低价政策带 nt=3 HighRisk 旗标且 nt=104 空转：riskPolicy=
    「高风险政策」——词面复用零新键，第二源补齐 nt=104 载体缺席行。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="HighRisk")]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_nt3_comma_form_lands():
    """逗号串形态（dump 实证「SplicingNfd,PremiumEcoProduct」同族
    载体）同落：split 归一后词表成员判定。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="SplicingNfd,HighRisk")]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_nt3_nonbest_policy_not_set():
    """旗标挂非最低价政策：不落——配对门唯一判据（最低价未必是
    高风险价，挂行级即误导，nt=104 价门同律）。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(price=2410),
                                   _policy(price=3600, nt3="HighRisk")]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_nt104_precedence_word_stable():
    """双源同价在场：词面恒「高风险政策」单值（riskPolicy 是字符串
    出口，双源同词面无重复拼接面）。"""
    import base64
    import zstandard
    payload = {"items": {"priceInfoList": json.dumps([
        {"aggSalePrice": 2410.0, "engineFareCode": "", "flags": ["PHISHING"],
         "grade": "Y", "limitTag": "HighRiskPolicy", "policyId": "p1",
         "price": 2410.0, "priceType": "normal"}])}}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="HighRisk")],
                    "notes": [{"notetype": 104,
                               "notecnt": base64.b64encode(blob).decode()}]})
    assert r.get("riskPolicy") == "高风险政策"


# ---- ctrip labels「超级经济舱」：nt=3 PremiumEcoProduct ----

def test_ctrip_premeco_label_lands():
    """最低价政策带 PremiumEcoProduct：labels 收「超级经济舱」——
    S 舱+座椅倾斜 100°+深折扣的档位语义，既有出口零承载。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(nt3="SplicingNfd,"
                                           "PremiumEcoProduct")]})
    assert "超级经济舱" in (r.get("labels") or "").split("·")


def test_ctrip_premeco_nonbest_policy_not_labeled():
    """旗标挂非最低价政策：不落——超级经济舱标签随最低价政策配对，
    行价不是超经产品价时挂行级即误导。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy(price=2410),
                                   _policy(price=3190,
                                           nt3="PremiumEcoProduct")]})
    assert "超级经济舱" not in (r.get("labels") or "").split("·")


# ---- qunar PC cabin 撤伪：binfo1.cabin 不落（H5 cabinDegree 同案） ----

def _pc_sample(binfo_extra=None, top=None):
    b1 = {"airCode": "FM9223", "shortName": "上航", "shortCarrier": "FM",
          "depTime": "19:55", "arrTime": "01:25",
          "date": "2026-10-04", "arrDate": "2026-10-05"}
    if binfo_extra:
        b1.update(binfo_extra)
    row = {"code": "FM9223", "minPrice": "2472", "transCity": "",
           "extparams": {}, "binfo": b1}
    row.update(top or {})
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [row]}})


def test_qunar_pc_cabin_not_landed():
    """PC binfo1.cabin（首段折扣桶/两字符漂移 'R3' 已在场）不落：
    与 H5 cabinDegree 撤伪同案——伪语义出口两侧同收。"""
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"cabin": "L"}), "2026-10-04")
    assert fl and "cabin" not in fl[0]


def test_qunar_pc_row_intact_after_cabin_removal():
    """撤伪不伤邻键：同舱位行的折扣词面照常落（信息由 discount
    承载，cabin 键冗余既判）。"""
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"cabin": "L"}, top={"discountStr": "9折"}),
        "2026-10-04")
    # 折扣词面有值照落（无值不落键缺席语义，r239 空串落键收口）
    assert fl and fl[0].get("discount") == "9折"


# ---- cabin_clean 复合高档词：查纯域词族子串化 ----

def test_cabin_clean_compound_high_word_guarded():
    """「豪华公务舱」含高档词族子串：价格硬证（price<bizPrice）成立
    即清污——等值匹配对复合高档词留缺口。"""
    assert cabin_clean({"cabin": "豪华公务舱", "price": 1000,
                        "bizPrice": 3000}) == ""


def test_cabin_clean_compound_high_word_kept_with_evidence():
    """price>=bizPrice（真高档选中）：复合词照常保留。"""
    assert cabin_clean({"cabin": "豪华公务舱", "price": 3000,
                        "bizPrice": 3000}) == "豪华公务舱"


def test_cabin_clean_super_economy_unaffected():
    """「超级经济舱」不含高档词子串：不受守卫影响（既有钉保持）。"""
    assert cabin_clean({"cabin": "超级经济舱", "price": 1000,
                        "bizPrice": 3000}) == "超级经济舱"


# ---- cabin_text cabinName 分支接守卫（上轮 P2-3） ----

def test_cabin_text_cabinname_high_word_guarded():
    """cabinName 高档词 × price<bizPrice：清污不进描述串——与 cabin
    分支同门，未来渠道直出高档 cabinName 不得绕过价格硬证。"""
    assert cabin_text({"cabinName": "头等舱", "price": 1000,
                       "bizPrice": 3000}) == ""


def test_cabin_text_cabinname_without_bizprice_kept():
    """无 bizPrice 不可内证：维持原值（与 cabin 分支口径一致）。"""
    assert cabin_text({"cabinName": "头等舱"}) == "头等舱"


def test_cabin_text_cabinname_economy_kept():
    """经济舱词面照常透传（既有钉保持）。"""
    assert cabin_text({"cabinName": "经济舱", "price": 1000,
                       "bizPrice": 3000}) == "经济舱"


# ---- fliggy._via 存储层脏键收口（r223 观测 P2-1，qunar._via 同族） ----

def test_fliggy_stopover_direct_lands_without_via():
    """经停语义直落 stopover，_via 内部哨兵不再入库——机型行「共享|
    经停|」形态（dump 实证）经 _parse_pc_text 后行内应有 stopover=True
    且无 _via 键（normalize 同判幂等：bool(stopover) 短路结果不变，
    DB raw schema 净化，qunar DOM 路径同族先例）。"""
    from crawlers.fliggy import FliggyCrawler
    rows = FliggyCrawler._parse_pc_text(
        "\n".join(["东航MU5137", "中型机 737 共享|经停|", "08:00", "11:30",
                   "虹桥国际机场T1", "浦东国际机场T2", "¥2320"]),
        "2026-10-05")
    assert rows and rows[0].get("stopover") is True
    assert "_via" not in rows[0]


# ---- qunar|cabin 哨兵退役（r223 观测 P2-2：键故意退场非站点改版） ----

def test_field_sentinel_qunar_cabin_retired_no_false_fire(monkeypatch, tmp_path):
    """qunar 60 行 cabin 全灭（撤伪后新轮常态）不告警：cabin 入结构性
    死键表（H5 cabinDegree 与 PC binfo1.cabin 两路撤伪定谳，跨源同一
    伪语义出口）——「站点改版键名失效」语义不再适用，观测即天天假火
    （表成员语义=skip，main._SENT_DEAD_KEYS 消费点）。share/few/term
    等白名单字段的伴生告警不在本钉范围，只钉 cabin 静默。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    # plane/discount 非死键、比率观测，带命中值防伴生假火干扰判读
    rows = [{"price": 1000, "cabin": "", "meal": "", "prate": "",
             "plane": "波音737", "discount": "4.5折"} for _ in range(60)]
    _m._field_sentinel(
        [_NS(platform="qunar", extra=json.dumps(rows))], _L())
    assert not any("cabin" in " ".join(map(str, a)) for a in seen), seen
