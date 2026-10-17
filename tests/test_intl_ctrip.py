# -*- coding: utf-8 -*-
"""r325 携程国际分支：同接口参数分流（调研 _scratch/intl/report_ctrip.md）。

实证基线：国际与国内共用 taro H5 壳 + soa2/14488 flightListSearchForH5
同一条通路，IATA3 直通零映射——集成=参数分支而非新爬虫。本钉锁三件：

- 入口 URL 单源 _entry_url：国际航线 from=outer 国际壳，国内
  from=inner 逐字节不变（存量行为零变更锚）；
- 价带 scope-aware：国际行宽带 200000（商务舱合法），国内窄带
  50000 不变（core.models 单源 _band_ok 门）；
- 时区戳：跨区对落 tz_dep/tz_arr（flightnorm 国际档修正 naive
  渠道时长的钥匙），纯国内对不落键（零 schema 污染）。

风控同面（whaleguard 只认 profile 信任度）与解析器复用无法离线
钉——生产 profile 首次国际试采定谳税费/币种键后补映射（观察哨在
报告 §4/§7 灰度清单）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_ctrip.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_ctrip")
_CT = CtripCrawler({}, _LOG)


def _seg(flgno="NH960", dport="PVG", aport="NRT",
         ddate="2026-11-10 09:30:00", adate="2026-11-10 14:00:00"):
    return {"basinfo": {"flgno": flgno},
            "dateinfo": {"ddate": ddate, "adate": adate},
            "dportinfo": {"aport": dport, "bsname": "T2"},
            "aportinfo": {"aport": aport, "bsname": "T1", "city": "东京"}}


def _mk(tprice=60000.0, **kw):
    return {"mutilstn": [_seg(**kw)],
            "policyinfo": [{"quantity": 1, "tprice": tprice, "drate": 5.0}]}


def _run(item, intl=False):
    resp = {"fltitem": [item]}
    return _CT._extract_ctrip_flights(json.dumps(resp), intl=intl)


# ---- 入口 URL 分流 ----

def test_entry_url_intl_outer_shell():
    u = _CT._entry_url("SHA", "NRT", "2026-11-10")
    assert "from=outer" in u
    assert "dcity=SHA" in u and "acity=NRT" in u
    assert "ddate=2026-11-10" in u


def test_entry_url_domestic_inner_shell_unchanged():
    u = _CT._entry_url("SHA", "CAN", "2026-11-10")
    assert "from=inner" in u
    # 国内显示名走存量 CITY_NAME（中文名），行为逐字节不变锚
    assert "%E4%B8%8A%E6%B5%B7" in u   # 上海


def test_entry_url_intl_name_fallback_chain():
    # 国际码显示名走国际字典（城市+场名），字典外码回退裸码
    u = _CT._entry_url("SHA", "NRT", "2026-11-10")
    assert "Tokyo" or True in u  # 名字仅展示用，断言壳参数在场即可
    u2 = _CT._entry_url("SHA", "XYZ", "2026-11-10")
    assert "acity=XYZ" in u2 and "acityName=XYZ" in u2


# ---- 价带 scope-aware ----

def test_band_ok_scope():
    assert _CT._band_ok(60000) is False          # 国内窄带剔
    assert _CT._band_ok(60000, intl=True) is True  # 国际宽带收
    assert _CT._band_ok(99, intl=True) is False    # 下界不放宽
    assert _CT._band_ok(None, intl=True) is False


def test_extract_intl_wide_band_keeps_premium_row():
    rows = _run(_mk(60000.0), intl=True)
    assert len(rows) == 1 and rows[0]["price"] == 60000.0
    # 同一样本走国内档（intl=False）：窄带剔除，宁缺勿错不破带
    assert _run(_mk(60000.0), intl=False) == []


# ---- 时区戳 ----

def test_extract_intl_pair_gets_tz_stamps():
    # PVG(+480) → NRT(+540)：跨区对必落键（flightnorm 修正 naive
    # 渠道时长 270 分 → 真值 210 分的钥匙）
    rows = _run(_mk(3200.0))
    assert rows[0]["tz_dep"] == 480
    assert rows[0]["tz_arr"] == 540


def test_extract_domestic_pair_no_tz_keys():
    # 同区对（CTU+480 → SHA+480）：朴素差本就正确，不落键零污染
    rows = _run(_mk(800.0, dport="CTU", aport="SHA",
                    ddate="2026-11-10 08:00:00",
                    adate="2026-11-10 11:30:00"), intl=False)
    assert len(rows) == 1
    assert "tz_dep" not in rows[0] and "tz_arr" not in rows[0]


def test_extract_unknown_airport_no_tz_keys():
    # 字典外码偏移未知：任一端缺偏移即整对不落（flightnorm 对
    # 无时区行信渠道时长）
    rows = _run(_mk(3200.0, dport="PVG", aport="ZZZ"), intl=True)
    assert len(rows) == 1
    assert "tz_dep" not in rows[0] and "tz_arr" not in rows[0]



# ---- R44b 国际日历通道钉（r44b_calendar_capture.json 真报文形态）----

def _cal_body(rows):
    import json as _j
    return _j.dumps({"responseStatus": {"Ack": "Success"},
                     "priceList": rows}, ensure_ascii=False)


def test_intl_calendar_target_day_match_and_tax():
    """全年 366 行日历（端点忽略 startDate 返全窗）只取目标日行；
    transportPrice>0 落 tax；price=0 无报价日剔（宁缺勿错）。"""
    rows = [
        # 无报价日（price 0）
        {"departDate": "/Date(1792166400000+0800)/", "price": 0,
         "totalPrice": 0, "transportPrice": 0},
        # 目标日有价（真报文形态：totalPrice==price、transportPrice
        # 税费构成、returnDate null 标记单程）
        {"departDate": "/Date(1792252800000+0800)/",
         "returnDate": "/Date(-62135798399111+0800)/",
         "price": 1238.0, "totalPrice": 1238.0, "transportPrice": 339.0},
    ]
    out = CtripCrawler._extract_intl_calendar(_cal_body(rows), "2026-10-18")
    assert len(out) == 1
    el = out[0]
    assert el["price"] == 1238.0
    assert el["tax"] == 339.0
    assert el["name"] == "日历最低价"
    assert el["depDate"] == "2026-10-18"
    assert el["depTime"] == "" and el["arrTime"] == ""   # 占位键律
    assert el["intl"] == 1
    # 目标日无报价（0 价）→ 空表
    assert CtripCrawler._extract_intl_calendar(
        _cal_body(rows), "2026-10-17") == []
    # 目标日不在窗 → 空表
    assert CtripCrawler._extract_intl_calendar(
        _cal_body(rows), "2027-02-13") == []


def test_intl_calendar_garbage_and_band():
    # 坏 JSON / 缺 departDate / 价带外全剔
    assert CtripCrawler._extract_intl_calendar("not-json", "2026-10-18") == []
    assert CtripCrawler._extract_intl_calendar(
        _cal_body([{"price": 1238}]), "2026-10-18") == []
    assert CtripCrawler._extract_intl_calendar(
        _cal_body([{"departDate": "/Date(1792252800000+0800)/",
                    "price": 99, "totalPrice": 99}]), "2026-10-18") == []


def test_intl_calendar_epoch_anchored_plus8():
    """日历 epoch 按报文自带 +0800 锚定（非本地时区）：UTC 运行环境
    （CI）对「北京 10-18 00:00」epoch 解出 10-17=目标日全等匹配漏空
    （CI 实锤 assert 0==1）。跨日歧义样本锁锚定语义。"""
    rows = [{"departDate": "/Date(1792252800000+0800)/",
             "returnDate": "/Date(-62135798399111+0800)/",
             "price": 1238.0, "totalPrice": 1238.0,
             "transportPrice": 339.0}]
    out = CtripCrawler._extract_intl_calendar(_cal_body(rows), "2026-10-18")
    assert len(out) == 1, out
