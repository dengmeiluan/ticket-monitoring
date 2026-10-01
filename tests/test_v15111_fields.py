# -*- coding: utf-8 -*-
"""本轮数据层源码钉（渠道调研立案 A-2 §2.1）：

同程中转行 bizPrice（高档舱参考价）：connection 报文 lps[] 政策
pts[].td 带「公务舱/商务舱/头等舱」词 + atp 有票价 → 落 bizPrice。
复用 book1 直飞同款三守卫（has_ticket 循环门 + 价带 + 舱位词独立
判定），取最低高档有票价——中转行 0/873 缺键补齐（直飞 1207/1887
与 ctrip 中转 1262/1973 均已落同键，「中转也坐公务要多少钱」跨渠道
键完整性缺口）。白名单/渲染端（webui/report/alerter）bizPrice 全
现成零改动。

ctrip riskPolicy（高风险政策透明标记）：notes nt=104 notecnt（裸
base64+zstd，与 pid 的 __Zstd__| 前缀门不同形）→ items.priceInfoList
（双层 JSON 字符串二次解析）[].limitTag=="HighRiskPolicy"，与落库
最低价同价（价门精确到分；同价条目 limitTag 零分歧 215/215 实证，
pid 舱位门在此不适用——limitTag 行 cabin_code 100% 缺失且 grade
全 Y 无区分度）即落，直飞/中转同行（nt=104 是行级报价载荷非 pid
段级分算形态，价门配对即真值；dump 两轮 13/13 命中全为中转行）。
limitTag 值域 {"",LimitedAgePolicy,HighRiskPolicy}：LimitedAgePolicy
已由 nt=20 文案源消费（同族同现），nt=104 只出口 HighRiskPolicy 新
语义；行级兜底「本班存在」不采——最低价未必是高风险价，挂行级即
误导。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15111_fields.py -q
"""
import base64
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import PRICE_MAX
from crawlers.ctrip import CtripCrawler
from crawlers.tongcheng import TongchengCrawler

_LOG = logging.getLogger("t15111")
_CT = CtripCrawler({}, _LOG)


def _rows(fps, doc=None):
    obj = {"data": {"fps": fps,
                    "doc": doc if doc is not None else {
                        "luggageSelf": "行李自助直挂",
                        "luggageAgain": "重新托运行李"}}}
    return TongchengCrawler._extract_transfer_flights(
        json.dumps(obj, ensure_ascii=False))


def _fp(lps):
    return {
        "dt": "2026-10-06 15:15", "at": "2026-10-07 07:55",
        "td": "16h40m", "sd": "11h0m", "sc": "武汉",
        "dat": "", "aat": "T2",
        "ss": [{"fn": "MU2601", "dt": "2026-10-06 15:15",
                "at": "2026-10-06 17:05", "asn": "东方",
                "amn": "空客A320"},
               {"fn": "MU2477", "dt": "2026-10-07 06:05",
                "at": "2026-10-07 07:55", "asn": "东方",
                "amn": "空客A320"}],
        "lps": lps,
    }


def test_transfer_bizprice_top_cabin_ticketed():
    """带票高档舱政策落 bizPrice：公务舱 atp 3956 → 行键在。"""
    rows = _rows([_fp([{"atp": 3956, "brs": [{"al": 5}],
                        "pts": [{"td": "公务舱"}]}])])
    assert rows and rows[0].get("bizPrice") == 3956


def test_transfer_bizprice_min_among_topcabins():
    """多高档政策取最低（商务 5230 / 公务 3956 → 3956）；
    经济舱有票政策（2320）不参与高档取值也不干扰。"""
    rows = _rows([_fp([
        {"atp": 5230, "brs": [{"al": 2}], "pts": [{"td": "商务舱"}]},
        {"atp": 2320, "brs": [{"al": 5}], "pts": [{"td": "5.6折经济舱"}]},
        {"atp": 3956, "brs": [{"al": 3}], "pts": [{"td": "公务舱"}]},
    ])])
    assert rows and rows[0].get("bizPrice") == 3956
    assert rows[0]["price"] == 2320   # 主价仍是经济舱最低价
    assert rows[0]["cabin"] == "经济舱"   # 舱位随最低价政策（既有律）


def test_transfer_bizprice_absent_when_economy_only():
    """只有经济舱有票政策：不落 bizPrice（宁缺勿错）。"""
    rows = _rows([_fp([{"atp": 2320, "brs": [{"al": 5}],
                        "pts": [{"td": "5.6折经济舱"}]}])])
    assert rows and "bizPrice" not in rows[0]


def test_transfer_bizprice_absent_when_top_unticketed():
    """高档舱政策无票（brs al=0）：幻影参考不落（_has_ticket 同守卫），
    经济舱有票行照常产出。"""
    rows = _rows([_fp([
        {"atp": 5230, "brs": [{"al": 0}], "pts": [{"td": "公务舱"}]},
        {"atp": 2320, "brs": [{"al": 5}], "pts": [{"td": "经济舱"}]},
    ])])
    assert rows and "bizPrice" not in rows[0]


def test_transfer_bizprice_absent_out_of_price_band():
    """高档舱价越价带（>PRICE_MAX）：不落（atp 价带守卫同 book1）。"""
    rows = _rows([_fp([
        {"atp": PRICE_MAX + 1, "brs": [{"al": 5}], "pts": [{"td": "头等舱"}]},
        {"atp": 2320, "brs": [{"al": 5}], "pts": [{"td": "经济舱"}]},
    ])])
    assert rows and "bizPrice" not in rows[0]


# ---- ctrip：nt=104 limitTag=HighRiskPolicy → riskPolicy「高风险政策」 ----

def _risk_note(entries):
    """构造 nt=104 notecnt（裸 base64+zstd；items.priceInfoList 是
    双层 JSON 字符串——与生产 dump 解码形态逐层同构）。"""
    import zstandard
    payload = {"items": {"priceInfoList": json.dumps([
        {"aggSalePrice": p, "engineFareCode": "", "flags": ["PHISHING"],
         "grade": g, "limitTag": t, "policyId": "4547559444",
         "price": p, "priceType": "normal"} for p, g, t in entries])}}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return {"notetype": 104, "notecnt": base64.b64encode(blob).decode()}


def _ctrip_seg(dd="2026-10-06 16:40:00", ad="2026-10-06 21:30:00",
               flgno="MU5633"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, qty=5):
    return {"tprice": price, "quantity": qty, "drate": 5.2}


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_riskpolicy_paired_lowest():
    """最低价与 HighRiskPolicy 条目同价：riskPolicy=「高风险政策」——
    「你看到的最低价是渠道高风险政策价」强信号（agePolicy 同语义位），
    价门=价格精确到分。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2410.0, "Y", "HighRiskPolicy"),
                                          (2600.0, "Y", "")])]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_unpaired_not_set():
    """HighRiskPolicy 在场但无同价条目：不落——配对不中宁缺勿错
    （行级兜底「本班存在」不采：最低价未必是高风险价，挂行级即误导）。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2999.0, "Y", "HighRiskPolicy")])]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_limited_age_not_set():
    """limitTag=LimitedAgePolicy 不落：nt=20 文案源已消费同族语义
    （agePolicy 出口在案），nt=104 只出口 HighRiskPolicy 新语义。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2410.0, "Y",
                                           "LimitedAgePolicy")])]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_transfer_paired():
    """中转行同价配对同样落：nt=104 是行级报价载荷（priceInfoList 与
    policyinfo 同源），价门精确配对即真值——非 pid 段级分算形态，
    「仅直飞」先例不适用（dump 两轮 13/13 命中全为中转行、直飞样本 0，
    维持中转门=永久零出勤死代码）。"""
    r = _ctrip_one({"pid": "",
                    "mutilstn": [_ctrip_seg("2026-10-06 16:40:00",
                                            "2026-10-06 19:30:00"),
                                 _ctrip_seg("2026-10-06 21:00:00",
                                            "2026-10-07 01:30:00",
                                            flgno="MU5700")],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2410.0, "Y",
                                           "HighRiskPolicy")])]})
    assert r.get("riskPolicy") == "高风险政策"


def test_ctrip_riskpolicy_transfer_unpaired_not_set():
    """中转行 HighRiskPolicy 在场但无同价条目：同样不落（价门唯一
    判据，与行级聚合价差 miss 宁缺勿错同律）。"""
    r = _ctrip_one({"pid": "",
                    "mutilstn": [_ctrip_seg("2026-10-06 16:40:00",
                                            "2026-10-06 19:30:00"),
                                 _ctrip_seg("2026-10-06 21:00:00",
                                            "2026-10-07 01:30:00",
                                            flgno="MU5700")],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2999.0, "Y",
                                           "HighRiskPolicy")])]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_bad_payload_silent():
    """坏 base64 静默跳过该 note 不炸整行（解码失败返回空表同
    _pid_free_kgs 四门律）。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [{"notetype": 104, "notecnt": "!!!not-b64!!!"}]})
    assert "riskPolicy" not in r


def test_ctrip_riskpolicy_zstd_dependency_missing_silent(monkeypatch):
    """zstandard 依赖缺失（ZstdDecompressor=None 哨兵）：nt=104
    整体跳过不炸整行——依赖 import try/except 收口为 None 的既有
    哨兵律，缺失时采集器整体跳过该字段而非炸渠道。"""
    import crawlers.ctrip as _m
    monkeypatch.setattr(_m, "ZstdDecompressor", None)
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_ctrip_policy(price=2410)],
                    "notes": [_risk_note([(2410.0, "Y",
                                           "HighRiskPolicy")])]})
    assert "riskPolicy" not in r
