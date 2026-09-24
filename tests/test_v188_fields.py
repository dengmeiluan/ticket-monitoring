# -*- coding: utf-8 -*-
"""渠道字段第十六批回归：ctrip 高档舱最低参考价 bizPrice / fliggy
discount「全价」形态放行 / 折扣词面守卫单源收编 / alerter bizPrice
bool 硬化。

- ctrip bizPrice（调研 F1 转正）：policyinfo 内 classinfor 首元素
  cgrd∈{1,2}（0=经济 1=公务 2=头等，dump 实证）政策取最低 tprice，
  多档取 min（协议=「高档舱最低参考价」，qunar businessClassMinPrice
  /tuniu 高档舱政策/fliggy 双价行高档词同键同语义）。首元素语义与
  best_ci 同律——dump 实证 121+160 政策 first-hi==any-hi 全等，混合
  形态 0 例，宁缺勿错不认后位元素。
- fliggy「全价」：SSR span.discount 词域（10-06 17/31=55%）无折扣
  可售形态，qunar/tuniu/tongcheng 同域已在产；两守卫放行后四渠道
  同词面。双价行首行折扣词描述被撤高价时撤键（与 cabin 撤键同律）。
- 折扣词面单源：flightnorm.discount_txt（「N.N折」|「全价」两形态），
  cabin_text 与 report 总表次行同源消费。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v188_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t188")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip：高档舱最低参考价 bizPrice ----

def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _one(policies):
    dd, ad = "2026-10-06 16:40:00", "2026-10-06 21:30:00"
    item = _ctrip_item([_ctrip_seg(dd, ad)], policies)
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_biz_price_high_cabin_min():
    """多档高档舱政策取最低 tprice（min 而非 max——取 max 会成
    「公务￥头等价」舱名数值双误）；主价取经济舱政策。"""
    r = _one([_ctrip_policy(price=560, ci={"cgrd": 0}),
              _ctrip_policy(price=9900, ci={"cgrd": 2}),
              _ctrip_policy(price=2730, ci={"cgrd": 2})])
    assert r["price"] == 560
    assert r["bizPrice"] == 2730
    assert isinstance(r["bizPrice"], int)


def test_ctrip_biz_price_absent_when_all_economy():
    """全经济舱政策：无高档舱参考价，不落键。"""
    r = _one([_ctrip_policy(price=560, ci={"cgrd": 0}),
              _ctrip_policy(price=610, ci={"cgrd": 0})])
    assert "bizPrice" not in r


def test_ctrip_biz_price_zero_qty_policy_ignored():
    """高档舱政策 quantity=0=不可购：同主价过滤律，不落。"""
    r = _one([_ctrip_policy(price=560, ci={"cgrd": 0}),
              _ctrip_policy(price=2730, ci={"cgrd": 2}, qty=0)])
    assert "bizPrice" not in r


def test_ctrip_biz_price_first_element_semantics():
    """classinfor 首元素语义（与 best_ci 舱位提取同律）：首元素
    经济、后位高档的混合形态不认（dump 实证 0 例，宁缺勿错）。"""
    p = _ctrip_policy(price=400)
    p["classinfor"] = [{"cgrd": 0}, {"cgrd": 2}]
    r = _one([p])
    assert "bizPrice" not in r


def test_ctrip_biz_price_int_protocol():
    """tprice 浮点透传会让 alerter isinstance(int) 门静默缺席
    （qunar 同坑先例）：落键恒 int。"""
    r = _one([_ctrip_policy(price=560, ci={"cgrd": 0}),
              _ctrip_policy(price=2730.0, ci={"cgrd": 2})])
    assert r["bizPrice"] == 2730
    assert isinstance(r["bizPrice"], int)


def test_ctrip_biz_price_only_high_left_equals_price():
    """仅剩高档舱政策：主价即高档舱价，bizPrice 与 price 同值照落
    （qunar 有源即落同律；渲染端「公务￥N」语义仍真）。"""
    r = _one([_ctrip_policy(price=9900, ci={"cgrd": 2})])
    assert r["price"] == 9900
    assert r["bizPrice"] == 9900
    assert r["cabin"] == "头等舱"


# ---- fliggy：discount「全价」形态 ----

def _row(txt):
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert rows, txt
    return rows[0]


_HEAD = "国航CA8564\n中型机 320\n15:15\n21:30\n乌鲁木齐天山国际机场\n虹桥国际机场T2\n"


def test_fliggy_full_price_discount_captured():
    """单报价行「¥560 全价」：全价=无折扣可售，落 discount（此前
    整体丢弃）。"""
    r = _row(_HEAD + "¥560 全价\n订票")
    assert r["price"] == 560.0
    assert r["discount"] == "全价"


def test_fliggy_nzhe_discount_unchanged():
    """「N.N折」既有捕获不回退。"""
    r = _row(_HEAD + "¥3960 4.5折\n订票")
    assert r["discount"] == "4.5折"


def test_fliggy_dual_first_high_discount_dropped():
    """首价格行折扣词描述被撤高价：合并后撤键宁缺勿错（词不随行，
    与 cabin 撤键同律；既有 N折 错归属同口关闭）。"""
    r = _row(_HEAD + "¥9900 9.9折\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert "discount" not in r


def test_fliggy_dual_first_high_full_price_dropped():
    """「全价」高价在前同律：撤高价后 discount 不驻留。"""
    r = _row(_HEAD + "¥9900 全价\n¥3960 4.5折\n订票")
    assert r["price"] == 3960.0
    assert "discount" not in r
    assert "bizPrice" not in r   # 无词高价宁缺勿错（既有协议不回退）


def test_fliggy_dual_first_low_keeps_discount():
    """低价在前：「全价」描述保留价，照常保留；高价带词照落
    bizPrice。"""
    r = _row(_HEAD + "¥3960 全价\n¥9900 商务舱\n订票")
    assert r["price"] == 3960.0
    assert r["discount"] == "全价"
    assert r["bizPrice"] == 9900


# ---- 折扣词面守卫单源（flightnorm.discount_txt） ----

def test_discount_txt_two_forms_only():
    """「N.N折」/「全价」两形态放行；「全价经济舱」类舱位描述假
    折扣词面（历史坑）与空值照弃。"""
    from core.flightnorm import discount_txt
    assert discount_txt("5.6折") == "5.6折"
    assert discount_txt(" 4.5折 ") == "4.5折"
    assert discount_txt("全价") == "全价"
    assert discount_txt("全价经济舱") == ""
    assert discount_txt("6.70折") == "6.70折"
    assert discount_txt("") == ""
    assert discount_txt(None) == ""


def test_cabin_text_consumes_full_price():
    """cabin_text 放行「全价」进舱位描述串（单源 discount_txt）。"""
    from core.flightnorm import cabin_text
    assert cabin_text({"cabinName": "经济舱", "discount": "全价"}) \
        == "经济舱 · 全价"
    assert cabin_text({"cabinName": "经济舱", "discount": "全价经济舱"}) \
        == "经济舱"


def test_report_discount_gate_single_source():
    """report 总表次行折扣段与 cabin_text 同源 discount_txt
    （两处 inline fullmatch 收编单源）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert 'discount_txt(f.get("discount"))' in src, \
        "report 折扣段未收编 discount_txt 单源"


# ---- alerter：bizPrice bool 硬化 ----

def test_compare_rows_biz_bool_rejected():
    """isinstance(x, int) 门对 bool True 为真（bool 是 int 子类）：
    True>0 恒真，「公务￥True」词条假数据——bool 显式排除。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="qunar", bizPrice=True)],
              "2026-10-06")]
    assert Alerter._compare_rows(cands)[0]["biz"] == ""
