# -*- coding: utf-8 -*-
"""渠道字段第十七批回归：ctrip 老客专享资格标签 / bizCabin 高档舱
舱别词面随源（纯头等政策班不再误标「公务」）/ tongcheng connection
fwbqs 第二段服务承诺 / 解析哨兵 discount 入列。

- ctrip 老客专享：aset.tagarea tcode=G_LoginMobileDiscount tagcnt 纯词
  无价格不随价 churn——「会员价/资格价」诉求在本报文唯一稳定落点，
  labels 白名单加一词零新键。
- bizCabin：bizPrice 取 cgrd∈{1,2} 政策最低 tprice，胜出政策的舱别
  （1=公务 2=头等）随键落 bizCabin；渲染端词面随源，缺省回退「公务」
  （存量行协议兼容）。三端同轮：alerter 比价组携 bizCab、report 链尾
  词条、webui 白名单+CSV+title。
- tongcheng fwbqs：connection 政策级服务标签（非空 2/74，真值唯一
  「第2程：免费上网」=中转第二段机上 WiFi，与 sts tt=3 白名单同族）；
  随最低价政策配对、白名单精确匹配、有值才落 labels（零新键）。
- 哨兵 discount 入列：五渠道现役恒有源（无折扣可售亦落「全价」
  词面），出勤高且稳——<10% 断链即键死信号，比率观测同 cabin/meal。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1589_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t189")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip：老客专享资格标签 ----

def _ctrip_item(segs, policies, aset=None):
    item = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        item["aset"] = aset
    return item


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


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_login_discount_label():
    """tcode=G_LoginMobileDiscount tagcnt「老客专享」：资格价标记入
    labels（该行价格非全民价——登录/老客才可买的决策信息）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})],
        aset=[{"tagarea": [{"tcode": "G_LoginMobileDiscount",
                            "tagcnt": "老客专享"}]}])
    assert "老客专享" in _ctrip_one(item)["labels"].split("·")


def test_ctrip_login_discount_absent_untouched():
    """无 aset 行照常产出（labels 其余词不回退）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})])
    assert "老客专享" not in _ctrip_one(item)["labels"]


# ---- ctrip：bizCabin 舱别词面随源 ----

def test_ctrip_biz_cabin_first_class_word():
    """胜出（最低 tprice）政策 cgrd=2=头等：bizCabin=「头等」——
    纯头等政策班渲染词面不再误标「公务」。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0}),
         _ctrip_policy(price=9900, ci={"cgrd": 2}),
         _ctrip_policy(price=2730, ci={"cgrd": 2})]))
    assert r["bizPrice"] == 2730
    assert r["bizCabin"] == "头等"


def test_ctrip_biz_cabin_business_word():
    """cgrd=1=公务：bizCabin=「公务」。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0}),
         _ctrip_policy(price=2730, ci={"cgrd": 1})]))
    assert r["bizCabin"] == "公务"


def test_ctrip_biz_cabin_absent_without_biz_price():
    """无高档舱政策：bizPrice/bizCabin 双双不落。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=560, ci={"cgrd": 0})]))
    assert "bizPrice" not in r
    assert "bizCabin" not in r


def test_compare_rows_biz_cabin_carried():
    """比价组携 bizCab（与 biz 同一行取源——同律防跨行错配）。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="ctrip", bizPrice=2730,
                         bizCabin="头等")], "2026-10-06")]
    row = Alerter._compare_rows(cands)[0]
    assert row["biz"] == 2730
    assert row["bizCab"] == "头等"


def test_compare_rows_biz_cabin_legacy_empty():
    """存量行无 bizCabin：bizCab 空串（渲染端回退「公务」）。"""
    from core.alerter import Alerter
    base = {"name": "春秋9C8846", "code": "9C8846", "depTime": "16:40",
            "arrTime": "21:30", "transCity": "", "crossDayDesc": "",
            "price": 2200}
    cands = [(140, [dict(base, _platform="qunar", bizPrice=7870)],
              "2026-10-06")]
    assert Alerter._compare_rows(cands)[0]["bizCab"] == ""


def test_report_biz_word_follows_source():
    """report 链尾词条词面随 bizCab 单源（缺省回退「公务」）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert "line.get('bizCab')" in src, "report 链尾词条未随 bizCab 源"


def test_webui_biz_cabin_three_ends():
    """webui 三端同轮：API 白名单透传 + CSV/title 词面随源 + CSV
    列头如实（高档舱）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "webui.py"), encoding="utf-8").read()
    assert '"bizCabin": f.get("bizCabin")' in src, "API 白名单缺 bizCabin"
    assert "f.bizCabin||'公务'" in src, "CSV 词面未随源"
    assert "he(f.bizCabin||'公务')" in src, "title 词面未随源"
    assert "'机建燃油','高档舱','退改'" in src, "CSV 列头未如实"


# ---- tongcheng：connection fwbqs 第二段服务承诺 ----

def _tc_row(lps=None, doc=None):
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "MU5700", "aat": "T2"},
                 {"fn": "MU2301", "dat": "T3"}],
          "lps": lps or [{"atp": 1800, "brs": [{"al": 3}]}]}
    text = json.dumps({"data": {"fps": [fp], "doc": doc or {}}})
    rows = TongchengCrawler._extract_transfer_flights(text)
    assert rows
    return rows[0]


def test_tongcheng_fwbqs_second_leg_wifi():
    """最低价政策带 fwbqs 真值「第2程：免费上网」：落 labels（中转
    第二段机上 WiFi 服务承诺，sts tt=3 同族）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "第2程：免费上网"}]}])
    assert r["labels"] == "第2程：免费上网"


def test_tongcheng_fwbqs_unknown_td_dropped():
    """白名单外词面整段不并（宁缺勿错——渠道改文案即静默不采）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}],
                      "fwbqs": [{"tt": 3, "td": "神秘权益"}]}])
    assert "labels" not in r


def test_tongcheng_fwbqs_absent_no_labels():
    """fwbqs 缺席/空：不落 labels 键（零新键，行形态不漂移）。"""
    assert "labels" not in _tc_row()
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}], "fwbqs": []}])
    assert "labels" not in r


def test_tongcheng_fwbqs_pairs_with_min_price_policy():
    """多政策时随最低价政策配对（同 cabin/$tcTip 同律防政策错配）。"""
    r = _tc_row(lps=[{"atp": 1800, "brs": [{"al": 3}]},
                     {"atp": 2600, "brs": [{"al": 2}],
                      "fwbqs": [{"tt": 3, "td": "第2程：免费上网"}]}])
    assert "labels" not in r   # fwbqs 挂在非最低价政策上，不采


# ---- 解析哨兵：discount 入列 ----

def _sent_rows(discount):
    return [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
             "prate": "", "plane": "波音737(中)", "discount": discount,
             "shareCarrier": "MU5700" if i % 3 == 0 else "",
             "fewTicket": "仅剩5张" if i % 5 == 0 else "",
             "arrTerminal": "T2", "depAirport": "乌鲁木齐天山",
             "planeSize": "中型机", "depAirportCode": "URC",
             "arrAirportCode": "SHA"} for i in range(30)]


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

        def info(self, *a, **k):
            pass

    rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
    _m._field_sentinel(rows, _L())
    return seen


def test_sentinel_discount_attended_healthy(monkeypatch, tmp_path):
    """五渠道现役恒有源（「N.N折」/「全价」两形态）：出勤高且稳，
    健康轮零告警（入列不假火）。"""
    seen = _sent(monkeypatch, tmp_path,
                 [("qunar", _sent_rows("4.5折"))])
    assert seen == [], seen


def test_sentinel_discount_death_alarms(monkeypatch, tmp_path):
    """discount 整字段断链（命中率 <10%）：比率观测告警——词面代行
    断供（「全价」形态丢失）静默死亡从此有观测。"""
    seen = _sent(monkeypatch, tmp_path, [("qunar", _sent_rows(""))])
    assert len(seen) == 1 and "discount" in str(seen[0]), seen
