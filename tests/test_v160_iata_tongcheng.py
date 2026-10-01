# -*- coding: utf-8 -*-
"""回归：tongcheng 行级机场 IATA 码（depAirportCode/
arrAirportCode 第四源）+ 跨渠道 IATA 码对分歧哨兵 + aptc 覆盖率
比率观测 + cabin_text discount N折 形态守卫 + fliggy recheck 观测
转正源钉。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v160_iata_tongcheng.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from core.flightnorm import cabin_text  # noqa: E402


# ---- tongcheng 直飞行：fl[].dac/aac（第十二批调研 dump 95/95 恒在） ----

def _tc_direct(**kw):
    f = {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
         "atp": 1800, "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    f.update(kw)
    return TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [f]}}))


def test_tongcheng_direct_iata_codes():
    """fl[].dac/aac 与已采 dasn/aasn 同层读，iata3 守卫同 qunar/tuniu/
    ctrip 三源同律：合法落、脏值不落、缺键空串在键（与 qunar 落键
    形态一致——webui 白名单/propagate 消费空串=无值）。"""
    rows = _tc_direct(dasn="天山", aasn="虹桥", dac="URC", aac="SHA")
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "SHA"
    for bad in ("urc", "123", "URCC", "乌鲁木齐", None, ""):
        rows = _tc_direct(dac=bad, aac=bad)
        assert rows[0]["depAirportCode"] == "", bad
        assert rows[0]["arrAirportCode"] == "", bad
    rows = _tc_direct()
    assert rows[0]["depAirportCode"] == ""
    assert rows[0]["arrAirportCode"] == ""


def test_tongcheng_transfer_iata_segment_chain():
    """conn 块段链取 ss[0].dac（首段出发=整体出发）/ss[-1].aac（末段
    到达=整体到达）。陷阱键钉死：ss[0].aac=首段中转场码（YZY 形），
    误读会让 URC→SHA 航线挂出 URC→YZY——与 qunar
    binfo1.arrAirportId 同律防误读。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "aat": "T3", "dac": "URC", "aac": "YZY"},
                 {"fn": "MU5700", "dat": "T5", "dac": "YZY", "aac": "PVG"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "PVG"
    fp2 = dict(fp, ss=[{"fn": "CZ6981", "dac": "urc"},
                       {"fn": "MU5700", "aac": "URCC"}])
    rows2 = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp2]}}))
    assert rows2[0]["depAirportCode"] == ""
    assert rows2[0]["arrAirportCode"] == ""


# ---- 哨兵：跨渠道 IATA 码对分歧 + aptc 覆盖率比率观测 ----

def _sent(monkeypatch, tmp_path, prices):
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    class _I:
        def info(self, *a, **k):
            pass

    rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
    _m._field_sentinel(rows, _L())
    return seen, _I, _m


def _healthy(**kw):
    """带齐比率/白名单观测字段命中值的行（排除其他桶噪音，聚焦断言）。"""
    f = {"price": 1000, "code": "9C8846", "depTime": "08:00",
         "arrTime": "12:00", "transCity": "", "arrDate": "2026-10-06",
         "cabin": "经济舱", "meal": "有餐食", "prate": "96",
         "plane": "737", "planeSize": "中型机", "depAirport": "天山",
         "depAirportCode": "URC", "arrAirportCode": "SHA"}
    f.update(kw)
    return f


def test_sentinel_iata_pair_divergence_warns(monkeypatch, tmp_path):
    """同航班号同指纹两渠道码对集合不一致=分歧（DB 全库 293 组合级
    配对 d=0 纯净基线定证的零容忍告警面）；码对一致/单源不响。"""
    qn = [_healthy() for _ in range(12)]
    ct = [_healthy(depAirportCode="URC", arrAirportCode="PVG")
          for _ in range(12)]
    seen, _I, _m = _sent(monkeypatch, tmp_path,
                         [("qunar", qn), ("ctrip", ct)])
    assert any("IATA 码对分歧" in str(a) for a in seen), seen
    # 码对一致：不响
    seen2, _I, _m = _sent(monkeypatch, tmp_path,
                          [("qunar", qn), ("ctrip", [_healthy() for _ in range(12)])])
    assert not any("IATA 码对分歧" in str(a) for a in seen2), seen2
    # 单源（对方无码不参对）：不响
    seen3, _I, _m = _sent(monkeypatch, tmp_path,
                          [("qunar", qn),
                           ("ctrip", [_healthy(depAirportCode="",
                                               arrAirportCode="")
                                      for _ in range(12)])])
    assert not any("IATA 码对分歧" in str(a) for a in seen3), seen3


def test_sentinel_iata_aptc_coverage(monkeypatch, tmp_path):
    """aptc 入比率观测（union 口径同 apt）：四源渠道码全灭 <10% 即响
    （键死会退化成单源让分歧哨兵失明——第二道防线）；fliggy|aptc 入
    死键表（页面定证无源）不响。"""
    bare = [_healthy(depAirportCode="", arrAirportCode="") for _ in range(30)]
    seen, _I, _m = _sent(monkeypatch, tmp_path, [("qunar", bare)])
    assert any("aptc" in str(a) for a in seen), seen
    seen2, _I, _m = _sent(monkeypatch, tmp_path, [("fliggy", bare)])
    assert not any("aptc" in str(a) for a in seen2), seen2
    coded = [_healthy() for _ in range(30)]
    seen3, _I, _m = _sent(monkeypatch, tmp_path, [("qunar", coded)])
    assert not any("aptc" in str(a) for a in seen3), seen3


# ---- cabin_text：discount N折 形态守卫 ----

def test_cabin_text_discount_guard():
    """N折 形态保留；qunar PC 复活后 discount 槽位的舱位描述文本
    （「全价经济舱」等，全库 6235 处/523 行实证）不进舱位描述串
    （与 report._plan_sub 守卫同律，语义由舱名列承载）。"""
    assert cabin_text({"cabin": "经济舱", "discount": "5.6折",
                       "plane": "737"}) == "经济舱 · 5.6折 · 737"
    # 文本形态丢弃（含空白包裹），其余段不受影响
    assert cabin_text({"cabin": "T", "discount": "全价经济舱"}) == "T舱"
    assert cabin_text({"cabin": "经济舱", "discount": " 5.6折 "}) == \
        "经济舱 · 5.6折"
    assert cabin_text({"cabin": "经济舱", "discount": "明珠经济舱"}) == \
        "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "商务舱"}) == "经济舱"
    # 无 discount / 空 / 纯折扣数值缺「折」均不落
    assert cabin_text({"cabin": "经济舱"}) == "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": ""}) == "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "5.6"}) == "经济舱"
    # 小数折与整数折皆合法
    assert cabin_text({"discount": "4折", "cabin": "经济舱"}) == \
        "经济舱 · 4折"


# ---- fliggy recheck 观测转正（源钉：撤「N=1 先观测」备注） ----

def test_fliggy_recheck_observation_promoted():
    """转正源钉：修复生效后 DB 累计 11/11 全部 recheck、反例
    0——「N=1 先观测」备注撤除，转正结论在案；反例出现即回滚的语义
    保留。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(os.path.dirname(here),
                            "crawlers", "fliggy.py"), encoding="utf-8").read()
    assert "N=1 先观测" not in src
    assert "N=1 定证不足" not in src
    assert "观测转正" in src
