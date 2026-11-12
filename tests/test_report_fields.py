# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r248_fields.py
- tests/test_v15124_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import logging
import os
import sqlite3
import sys

from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r248_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t248")


def _fa(mins=0):
    """样本 fetched_at 动态基线（now-24h）：hours=48 相对窗吃硬编码
    时刻零余量——『2026-10-04 15:34:43』样本于 10-06 15:34 起滑出窗界
    （LESSONS 十八§1 时间敏感测试日历自爆判例）。24h 居窗中段，双侧
    余量恒 ≥1 天；同一用例内多样本只挪 mins 相对偏移，桶聚行为不变。"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=24, minutes=mins)).strftime(
        "%Y-%m-%d %H:%M:%S")


# ---------- D1: normalize 打 _dep_mismatch 标 ----------

def test_dep_mismatch_flag_in_normalize():
    from core.flightnorm import normalize
    # 渠道滚动：查询 10-05、行内真实起飞日期 10-06 → 打标
    g = normalize({"depDate": "2026-10-06", "arrDate": "2026-10-06",
                   "depTime": "08:00", "arrTime": "11:00"}, "2026-10-05")
    assert g.get("_dep_mismatch") is True
    # 正常行不打标
    g2 = normalize({"depDate": "2026-10-05", "arrDate": "2026-10-05",
                    "depTime": "08:00", "arrTime": "11:00"}, "2026-10-05")
    assert not g2.get("_dep_mismatch")
    # depDate 缺失不打标（无参照不判，守卫从宽）
    g3 = normalize({"depTime": "08:00", "arrTime": "11:00"}, "2026-10-05")
    assert not g3.get("_dep_mismatch")
    # 查询日期缺失不打标（webui 历史行 depart_date 可空）
    g4 = normalize({"depDate": "2026-10-06", "depTime": "08:00",
                    "arrTime": "11:00"}, "")
    assert not g4.get("_dep_mismatch")
    # 跨天中转行不误伤：depDate=查询日、到达次日
    g5 = normalize({"depDate": "2026-10-05", "arrDate": "2026-10-06",
                    "depTime": "23:30", "arrTime": "01:50",
                    "transCity": "西安"}, "2026-10-05")
    assert not g5.get("_dep_mismatch")
    # 幂等：重复 normalize 不翻转
    normalize(g, "2026-10-05")
    assert g.get("_dep_mismatch") is True


def test_dep_mismatch_flag_before_early_return():
    """缺起降时刻的早退分支同样打标（mismatch 判定无前置依赖）。"""
    from core.flightnorm import normalize
    g = normalize({"depDate": "2026-10-07", "price": 1200}, "2026-10-05")
    assert g.get("_dep_mismatch") is True


# ---------- D1: 曲线端消费过滤 ----------

def test_curve_ignores_dep_mismatch_elements(tmp_path):
    db = str(tmp_path / "t.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE flight_prices (platform TEXT, extra TEXT, "
        "fetched_at TEXT, from_city TEXT, to_city TEXT, depart_date TEXT, "
        "price REAL)")
    # 滚动行：10-05 查询、真实 10-06 航班——不给 10-05 曲线画点
    rolling = [{"price": 2470, "depDate": "2026-10-06",
                "arrDate": "2026-10-06",
                "depTime": "08:00", "arrTime": "11:00",
                "code": "MU8368", "name": "东航MU8368"}]
    real = [{"price": 1500, "depDate": "2026-10-05", "arrDate": "2026-10-05",
             "depTime": "09:00", "arrTime": "12:00",
             "code": "CZ6400", "name": "南航CZ6400"}]
    con.execute("INSERT INTO flight_prices VALUES "
                "('fliggy', ?, ?, 'URC', 'SHA', "
                "'2026-10-05', 2470)", (json.dumps(rolling), _fa()))
    con.execute("INSERT INTO flight_prices VALUES "
                "('qunar', ?, ?, 'URC', 'SHA', "
                "'2026-10-05', 1500)", (json.dumps(real), _fa(mins=10)))
    con.commit()
    con.close()
    from report import _rounds
    series = _rounds(db, "URC", "SHA", "2026-10-05", "02:00", hours=48)
    assert len(series) == 1
    _ts, d, t, _qd, _qt = series[0]
    assert d == 1500, "滚动元素不得进桶（曲线冻结在最后真实轮）"


# ---------- D1: 推送池消费过滤 ----------

def test_push_pool_ignores_dep_mismatch():
    from core.alerter import _flights_from_extra
    obj = [
        {"price": 2470, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "08:00", "arrTime": "11:00"},
        {"price": 1500, "depDate": "2026-10-05", "arrDate": "2026-10-05",
         "depTime": "09:00", "arrTime": "12:00"},
    ]
    flights = _flights_from_extra(obj, "2026-10-05", "qunar")
    assert len(flights) == 1
    assert flights[0]["price"] == 1500
    assert flights[0]["_platform"] == "qunar"


# ---------- D1: sweep 跳过过期日期查询（治本） ----------

def test_sweep_splits_expired_query_dates():
    import main
    queries = [("URC", "SHA", "2026-10-05"), ("URC", "SHA", "2026-10-06"),
               ("URC", "PEK", "2026-10-07")]
    live, expired = main._split_expired_queries(queries, "2026-10-06")
    assert live == [("URC", "SHA", "2026-10-06"), ("URC", "PEK", "2026-10-07")]
    assert expired == [("URC", "SHA", "2026-10-05")]
    # 全部未过期：expired 空
    live2, expired2 = main._split_expired_queries(queries, "2026-10-01")
    assert len(live2) == 3 and expired2 == []


# ---------- D1: 日报池消费过滤（第三消费点） ----------

def test_daily_pool_ignores_dep_mismatch(tmp_path):
    """_route_latest_flights（日报 KPI/明细表/查现价共用池）同样不得
    让滚动行入池：跳采上线前落库的滚动行年龄 ≤2.5h 时仍会被「每平台
    最新一份」选中，日报 09:00 档的过期日期小节仍会呈现别日航班
    （与推送 P0 同病，三端同一可信口径缺一不可）。"""
    db = str(tmp_path / "t.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, "
        "platform TEXT, extra TEXT, fetched_at TEXT, from_city TEXT, "
        "to_city TEXT, depart_date TEXT, price REAL)")
    # 滚动行（id 更大=更新，「每平台最新一份」先选中它）与真实行同平台
    # ——不过滤则日报池被滚动态顶替，真实行连候选都进不了
    rolling = [{"price": 2470, "depDate": "2026-10-06",
                "arrDate": "2026-10-06",
                "depTime": "08:00", "arrTime": "11:00",
                "code": "MU8368", "name": "东航MU8368"}]
    real = [{"price": 1500, "depDate": "2026-10-05", "arrDate": "2026-10-05",
             "depTime": "09:00", "arrTime": "12:00",
             "code": "CZ6400", "name": "南航CZ6400"}]
    con.execute("INSERT INTO flight_prices (platform, extra, fetched_at,"
                " from_city, to_city, depart_date, price) VALUES "
                "('fliggy', ?, '2026-10-05 23:50:00', 'URC', 'SHA', "
                "'2026-10-05', 1500)", (json.dumps(real),))
    con.execute("INSERT INTO flight_prices (platform, extra, fetched_at,"
                " from_city, to_city, depart_date, price) VALUES "
                "('fliggy', ?, '2026-10-06 00:30:00', 'URC', 'SHA', "
                "'2026-10-05', 2470)", (json.dumps(rolling),))
    con.commit()
    con.close()
    from report import _route_latest_flights
    import datetime as _dt
    import report as _report
    real_now = _dt.datetime

    class _FakeNow(real_now):
        @classmethod
        def now(cls):
            return real_now(2026, 10, 6, 0, 40, 0)

    # report.py 是「from datetime import datetime」类绑定：须补其
    # 命名空间，补 datetime 模块属性不生效
    import pytest
    mpatch = pytest.MonkeyPatch()
    mpatch.setattr(_report, "datetime", _FakeNow)
    try:
        out = _route_latest_flights(db, "URC", "SHA", "2026-10-05")
    finally:
        mpatch.undo()
    prices = [f["price"] for f in out]
    assert 2470 not in prices, "滚动行不得进日报池（第三消费点同口径）"
    assert 1500 in prices, "真实行不受误伤"


# ---------- D2: 渠道整轮零记录哨 ----------

def test_channel_zero_rounds_sentinel(monkeypatch):
    import main
    logs = []

    class _L:
        @staticmethod
        def warning(m, *a):
            logs.append(("W", m % a if a else m))

        @staticmethod
        def info(m, *a):
            logs.append(("I", m % a if a else m))

    monkeypatch.setattr(main, "_ZERO_STREAK", {})
    monkeypatch.setattr(main, "_SENT_LAST", {})
    monkeypatch.setattr(main, "_SENT_CNT", {})
    monkeypatch.setattr(main, "_sent_save", lambda: None)
    # 单轮零记录不报（瞬时风控常态，tuniu 179991 单轮自愈先例）
    main._channel_zero_sentinel({"tuniu": 0, "qunar": 45}, _L)
    assert not any("零记录" in m for _lv, m in logs)
    # 连续第 2 轮零记录 → WARNING
    main._channel_zero_sentinel({"tuniu": 0, "qunar": 45}, _L)
    assert any(lv == "W" and "零记录" in m and "tuniu" in m
               for lv, m in logs)
    # 同日去重：第 3 轮不再报（但 streak 继续）
    n_warn = sum(1 for lv, m in logs if lv == "W" and "零记录" in m)
    main._channel_zero_sentinel({"tuniu": 0}, _L)
    assert sum(1 for lv, m in logs if lv == "W" and "零记录" in m) == n_warn
    assert main._ZERO_STREAK.get("tuniu") == 3
    # 恢复出数 → streak 归零
    main._channel_zero_sentinel({"tuniu": 30}, _L)
    assert main._ZERO_STREAK.get("tuniu") == 0


# ---------- D3: 曲线桶行级幻影守卫 ----------

def test_curve_row_guard_drops_tainted_rows(tmp_path):
    """复刻观测分歧桶②机理：中转桶元素池仅 3 渠道（tuniu/fliggy 无中转
    明细），双渠道毒价互拖元素级锚漏判；行级池 5 渠道可判。行级守卫
    先行整行剔除后，毒价 1034 不上图、qunar 行内健康直飞元素 2589
    随行出局（与列表「整行剔除」同口径，图有列无消失）。"""
    db = str(tmp_path / "t.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE flight_prices (platform TEXT, extra TEXT, "
        "fetched_at TEXT, from_city TEXT, to_city TEXT, depart_date TEXT, "
        "price REAL)")

    def _row(plat, price, elements):
        con.execute(
            "INSERT INTO flight_prices VALUES (?, ?, ?,"
            " 'URC', 'SHA', '2026-10-06', ?)",
            (plat, json.dumps(elements), _fa(), price))

    # 双毒行（行级池可判幻影）+ 健康三行；qunar 行内带健康直飞元素
    _row("qunar", 1034, [
        {"price": 1034, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "08:00", "arrTime": "14:20", "transCity": "西安",
         "code": "MU6108/MU9192", "name": "东航MU6108/MU9192",
         "totalDuration": "6时20分", "layover": 170},
        {"price": 2589, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "07:30", "arrTime": "10:50",
         "code": "9C6496", "name": "春秋9C6496"},
    ])
    _row("ctrip", 1100, [
        {"price": 1100, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "09:00", "arrTime": "15:00", "transCity": "西安",
         "code": "CZ3301/ZH9876", "name": "南航CZ3301/深航ZH9876",
         "totalDuration": "6时0分", "layover": 150},
    ])
    _row("tongcheng", 2299, [
        {"price": 2299, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "10:00", "arrTime": "13:00",
         "code": "HO1252", "name": "吉祥HO1252"},
    ])
    _row("tuniu", 2350, [
        {"price": 2350, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "11:00", "arrTime": "14:00",
         "code": "MF2808", "name": "厦航MF2808"},
    ])
    _row("fliggy", 2400, [
        {"price": 2400, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "12:00", "arrTime": "15:10",
         "code": "CA8564", "name": "国航CA8564"},
    ])
    con.commit()
    con.close()
    from report import _rounds
    series = _rounds(db, "URC", "SHA", "2026-10-06", "02:00", hours=48)
    assert len(series) == 1
    _ts, d, t, qd, qt = series[0]
    assert d == 2299, "毒行整行出局后直飞最低=健康行"
    assert t is None, "毒价 1034/1100 不得成为曲线中转点"
    assert not qt and not qd, "毒价不得挂达标/破线旗标"


# ---------- C1: qunar listPopView → ticketRisk ----------

_LISTPOP = {"title": "温馨提示",
            "mainText": "1.航班临近起飞时间，购票前请先到值机柜台确认"
                        "出票后仍有时间值机再预订，（支付成功后5分钟内"
                        "告知出票结果）。2.若出票失败，订单自动取消并"
                        "全额退款。3.若已出票，退改损失需自行承担。",
            "confirmButton": "已确认有时间值机，去预订",
            "cancelButton": "值机柜台已关闭，暂不预订"}


def _qf(extra=None):
    f = {"code": "HU7518", "minPrice": 900,
         "binfo": {"depTime": "06:55", "arrTime": "10:10",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "binfo2": {}, "mixFlightName": "海航HU7518\n金鹿JD5218"}
    if extra:
        f.update(extra)
    return f


def test_qunar_listpopview_ticketrisk():
    from crawlers.qunar import QunarCrawler
    out = QunarCrawler._extract_flights_obj(
        [_qf({"listPopView": _LISTPOP})])
    assert len(out) == 1
    assert out[0].get("ticketRisk") == "临近起飞需确认值机"


def test_qunar_ticketrisk_guard_negative():
    from crawlers.qunar import QunarCrawler
    # title 不含「提示」（营销弹层形态）→ 不落
    m1 = dict(_LISTPOP, title="限时优惠")
    out1 = QunarCrawler._extract_flights_obj([_qf({"listPopView": m1})])
    assert not out1[0].get("ticketRisk")
    # mainText 不含「值机柜台」→ 不落
    m2 = dict(_LISTPOP, mainText="支付成功后5分钟内告知出票结果")
    out2 = QunarCrawler._extract_flights_obj([_qf({"listPopView": m2})])
    assert not out2[0].get("ticketRisk")
    # font 标签 strip：标签包裹下守卫仍命中且词面纯净
    m3 = dict(_LISTPOP,
              mainText="<font color='#ff6600'>航班临近起飞时间，购票前"
                       "请先到值机柜台确认</font>")
    out3 = QunarCrawler._extract_flights_obj([_qf({"listPopView": m3})])
    assert out3[0].get("ticketRisk") == "临近起飞需确认值机"
    # 无 listPopView 的行零影响
    out4 = QunarCrawler._extract_flights_obj([_qf()])
    assert "ticketRisk" not in out4[0]


# ---------- S-Q2: PC 复活轮 binfo.cabin 直飞行舱位码收编 ----------

def _pcrow(trans=False, binfo_extra=None, b1_extra=None):
    """PC wbdflightlist 行形态：直飞=binfo 满键+binfo1/binfo2 空；
    中转=binfo1/binfo2 两段。"""
    bi = {"depTime": "09:30", "arrTime": "14:10", "depDate": "2026-10-06",
          "arrDate": "2026-10-06", "flightTime": "4h40m"}
    bi.update(binfo_extra or {})
    if trans:
        b1 = dict(bi, arrTime="11:30", cabin="R1")
        b2 = dict(bi, depTime="13:00", cabin="Q")
        f = {"code": "GS6478/Y87510", "minPrice": 2270,
             "transCity": "兰州", "binfo1": b1, "binfo2": b2}
    else:
        f = {"code": "FM9220", "minPrice": 2214,
             "binfo": dict(bi, cabin="L"), "binfo1": {}, "binfo2": {}}
    if b1_extra:
        f.setdefault("binfo1", {}).update(b1_extra)
    return f


def test_qunar_pc_direct_cabin_code():
    from crawlers.qunar import QunarCrawler
    # 直飞行 binfo.cabin（单字符标准订座舱位）→ cabinCode
    out = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [_pcrow()]}}), "2026-10-06")
    assert len(out) == 1
    assert out[0].get("cabinCode") == "L"
    # 中转段级 binfo1.cabin 与 cabinDegree 全等=r222 撤伪案（段级折扣
    # 桶冒充行级舱位，'R1' 数字漂移在场）——不落，维持撤伪
    out2 = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [_pcrow(trans=True)]}}), "2026-10-06")
    assert len(out2) == 1
    assert "cabinCode" not in out2[0]
    # 直飞无舱位码不落键（无值不落）
    f3 = _pcrow()
    f3["binfo"].pop("cabin")
    out3 = QunarCrawler._parse_pc_flights(
        json.dumps({"data": {"flights": [f3]}}), "2026-10-06")
    assert len(out3) == 1
    assert "cabinCode" not in out3[0]


# ---------- D3 补口: 滚动行价不入行级锚池（Soldier P2-1） ----------

def test_curve_row_anchor_excludes_rolling_rows(tmp_path):
    """行级幻影锚池只收「价带内+非滚动」行（与告警链先滤滚动行再判锚
    同口径）：滚动行价（常为别日更低价）混入中位锚会把阈值从
    0.5×2400=1200 拉到 0.5×2200=1100，边界毒价 1150 逃过行级守卫，
    且元素池仅剩 1 渠道时二审不判→毒价上图。"""
    db = str(tmp_path / "t.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE flight_prices (platform TEXT, extra TEXT, "
        "fetched_at TEXT, from_city TEXT, to_city TEXT, depart_date TEXT, "
        "price REAL)")

    def _row(plat, price, elements):
        con.execute(
            "INSERT INTO flight_prices VALUES (?, ?, ?,"
            " 'URC', 'SHA', '2026-10-06', ?)",
            (plat, json.dumps(elements), _fa(), price))

    _tf_fail = {"depDate": "2026-10-06", "arrDate": "2026-10-06",
                "depTime": "10:00", "arrTime": "13:00",
                "transCity": "西安", "code": "HO1252",
                "name": "吉祥HO1252", "totalDuration": "6时0分",
                "layover": 60}
    _row("qunar", 1150, [
        {"price": 1150, "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "depTime": "08:00", "arrTime": "11:00",
         "code": "MU6108", "name": "东航MU6108"}])
    _row("tongcheng", 2000, [dict(_tf_fail, price=2000)])
    _row("ctrip", 2400, [dict(_tf_fail, price=2400)])
    _row("fliggy", 2500, [dict(_tf_fail, price=2500)])
    _row("tuniu", 500, [
        {"price": 500, "depDate": "2026-10-07", "arrDate": "2026-10-07",
         "depTime": "08:00", "arrTime": "11:00",
         "code": "MF2808", "name": "厦航MF2808"}])
    con.commit()
    con.close()
    from report import _rounds
    series = _rounds(db, "URC", "SHA", "2026-10-06", "02:00", hours=48,
                     layover_min=90)
    # 修复后：毒行被净锚整行剔除、中转行被衔接门滤空→桶 d/t 全空不落点
    # （旧行为：滚动行 500 混锚把阈拉到 1100 放过毒价 1150，且 ds 池单
    # 渠道二审不判→series=[(ts,1150,None,…)] 长 1）
    assert series == [], "毒价 1150 不得上图（滚动行价混锚放过边界毒价）"


# ---------- C2: ctrip「中转餐食」白名单补词 ----------

def test_ctrip_label_zhuanzhuan_meal():
    """aset tagcnt「中转餐食」（G_INCZZXX）→ labels；「中转餐饮」保留。"""
    from crawlers.ctrip import CtripCrawler
    ct = CtripCrawler({}, _LOG)

    def _mk(tagcnt):
        return {
            "mutilstn": [
                {"basinfo": {"flgno": "GJ8651"},
                 "dateinfo": {"ddate": "2026-10-05 08:30:00",
                              "adate": "2026-10-05 10:40:00"},
                 "craftinfo": {"cdisname": "空客320(中)"},
                 "dportinfo": {"aport": "URC", "bsname": "天山"},
                 "aportinfo": {"aport": "INC", "city": "银川",
                               "bsname": "河东"},
                 },
                {"basinfo": {"flgno": "MF8531"},
                 "dateinfo": {"ddate": "2026-10-05 13:10:00",
                              "adate": "2026-10-05 16:20:00"},
                 "craftinfo": {"cdisname": "波音737(中)"},
                 "dportinfo": {"aport": "INC", "bsname": "河东"},
                 "aportinfo": {"aport": "XMN", "bsname": "高崎"},
                 },
            ],
            "aset": [{"tagarea": [{"tcode": "G_INCZZXX",
                                   "tagcnt": tagcnt}]}],
            "policyinfo": [{"quantity": 1, "tprice": 1420.0, "drate": 5.0}],
        }

    out = ct._extract_ctrip_flights(json.dumps({"fltitem": [_mk("中转餐食")]}))
    assert out, "合成行必须真实可达（fixture 不可达=死码测试）"
    assert "中转餐食" in (out[0].get("labels") or "")
    # 既有词保留（并存异域产品，超集补词不替换）
    out2 = ct._extract_ctrip_flights(json.dumps({"fltitem": [_mk("中转餐饮")]}))
    assert "中转餐饮" in (out2[0].get("labels") or "")


# ---- merged from tests/test_v15124_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 最小 DOM 文本（行形态照 test_core_units._DOM_SAMPLE 状态机口径）：
# 一组中转行 + 一组经停行
_DOM_MINI = """23:00

虹桥T1

10h55m

转

西安

+1天

09:55

乌鲁木齐天山

春秋9C8945 新海航｜长安航空9H8329

1836

17:05

浦东T2

7时

停

+1天

00:05

乌鲁木齐天山

南航CZ6976 波音737(中)

2692
"""


def test_qunar_dom_via_never_leaves_parser():
    """_via 哨兵不得随行出解析器（fliggy 同律写入端根治）：经停语义
    函数尾部直落 stopover=True，中转语义已由状态机直落 transCity；
    normalize 读层 pop 保持双保险（幂等不翻转）。"""
    out = QunarCrawler._parse_dom_flights(_DOM_MINI, "2026-10-05")
    assert len(out) == 2, out
    st = next(f for f in out if f["code"] == "CZ6976")
    t = next(f for f in out if f["code"] == "9C8945/9H8329")
    for f in (st, t):
        assert "_via" not in f, f
    assert st["stopover"] is True, st          # 「停」直落
    assert t["transCity"] == "西安", t          # 「转」既有直落不受影响
    # normalize 幂等：写入端直落后同判不变（读层双保险不翻转语义）
    from core.flightnorm import normalize as _norm
    assert _norm(dict(st), "2026-10-05")["stopover"] is True


def test_qunar_pc_row_never_carries_stopairports():
    """PC 路 stopAirports 孤儿键退役（载荷卫生 tam 先例）：行不再携带；
    stopCitys 数组 join 出口保留（normalize 取首城落 stopCity 有消费）。"""
    pc = json.dumps({
        "ret": True, "data": {"flights": [
            {"code": "FM9223", "minPrice": "2889", "crossDayDesc": "+1天",
             "transCity": "", "transTime": "",
             "binfo": {"airCode": "FM9223", "shortName": "上航",
                       "name": "上海航空", "depTime": "19:55",
                       "arrTime": "01:25", "date": "2026-10-05",
                       "arrDate": "2026-10-06", "flightTime": "5h30m",
                       "stopCitys": ["宜昌"],
                       "stopAirports": ["宜昌三峡机场"]}},
        ]}}, ensure_ascii=False)
    rows = QunarCrawler._parse_pc_flights(pc, "2026-10-05")
    assert rows, "PC 样本应解析出行"
    assert rows[0]["stopCitys"] == "宜昌", rows[0]
    assert "stopAirports" not in rows[0], rows[0]


def test_qunar_h5_row_never_carries_stopairports():
    """H5 路 stopsAirPort 同律退役：info/binfo2 两级兜底提取链撤
    stopAirports 半边，stopsCitys 半边保留（真值「西安;库尔勒」形
    分号归一口径不受牵连）。"""
    h5 = json.dumps({"data": {"flights": [{
        "minPrice": 2692, "code": "CZ6976",
        "extparams": "{\"stopFlight\":true}",
        "binfo": {"depTime": "17:05", "arrTime": "00:05",
                  "depDate": "2026-10-05", "arrDate": "2026-10-06",
                  "stopsCitys": "宜昌", "stopsAirPort": "宜昌三峡机场"},
    }]}})
    rows = QunarCrawler._parse_response_flights(h5)
    assert rows, "H5 样本应解析出行"
    assert rows[0]["stopCitys"] == "宜昌", rows[0]
    assert "stopAirports" not in rows[0], rows[0]


# ---- WebUI 审计三案（r224）：源码钉层 ----

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui_src():
    return webui_full_src()


def test_webui_mtabsh_defined_in_541_760_band():
    """P1-1：541-760 带切换器吸顶（L1248 专属块）但 --mtabsh 只在 ≤540
    块定义——scroll-padding 消费裸 var 整条 calc 塌 0（声明 invalid 落
    auto），锚点落点被 header+吸顶条遮挡实测 102px。定义随消费带补齐：
    与 ≤540 同值 52px（宁多勿遮既定取舍；该带 montabs 无 height 声明，
    变量只喂 scroll-padding，零视觉副作用）。"""
    src = _webui_src()
    i_band = src.index("@media(min-width:541px) and (max-width:760px)")
    i_le540 = src.index("@media(max-width:540px)")
    i_def = src.index(":root{--mtabsh:52px}", i_band)
    assert i_band < i_def < i_le540, (i_band, i_def, i_le540)


def test_webui_mkact_preserves_template_tabindex():
    """P1-2：mkact 无条件 el.tabIndex=0 打穿 roving 初态——健康格/
    脉冲柱模板带 tabindex="0/-1"（每族首格 0 其余 -1 的 roving 纪律）
    且 role="button" 命中 mkactAll，改写发生在内联 onkeydown 早退之前
    →全族 400+ 格 Tab 逐格穿越回归。写法钉：模板已带 tabindex 属性者
    不改写，仅无属性元素补 0。"""
    src = _webui_src()
    assert "if(!el.hasAttribute('tabindex'))el.tabIndex=0;" in src
    assert "\n el.tabIndex=0;el.setAttribute('role','button');" not in src


def test_webui_rngchip_on_focus_ring_override_after():
    """P2-3：.rngchip.on 选中辉光与焦点环同特异性同属性（box-shadow），
    声明序靠后者胜（LESSONS 廿一§1）——环块在前被辉光盖掉，选中态
    chip 键盘聚焦零可见环。覆写块必须置尾（声明序在 .rngchip.on 之后）。"""
    src = _webui_src()
    i_on = src.index(".rngchip.on{")
    i_fix = src.index(".rngchip.on:focus-visible{")
    assert i_fix > i_on, (i_on, i_fix)


# ---- 推送审校 P0（r224）：总表次行极端超容兜底形态 ----

def _report_src():
    return open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()


def test_subline_overflow_fallback_keeps_core_group():
    """总表次行极端超容 plan=None 兜底形态（r224 推送审校 P0）：六档
    丢档链全败回退「全字段单行省略号」时可见头部恰是低优字段（机型·
    体量·廊桥），恒保组（准点/共享/余票/取消率）整段截丢。兜底串必须
    取末档丢弃域重建（_chain[-1]）——单行截断保住的可见头部即恒保组，
    决策字段不再随兜底路径蒸发。"""
    import re
    src = _report_src()
    assert re.search(r"for _drop, _ss in _chain:", src), "丢档链未变量化"
    m = re.search(r"if plan is None:\s*\n[^:]*?_rebuild\(\*_chain\[-1\]\)", src,
                  re.S)
    assert m, "plan=None 兜底串未取末档重建（恒保组被整截）"


def test_subline_overflow_extreme_row_renders(tmp_path):
    """极端超宽行端到端渲染不炸：plan=None 兜底分支只有极端样本走到，
    常规样本全链探不到（LESSONS 十九§14 空分支同族）。全字段超长值
    构造极端行，兜底路径真实执行且产物落盘。"""
    from report import render_flights_table
    f = {
        "platform": "qunar", "depDate": "2026-10-05", "price": 1264.0,
        "depTime": "07:10", "arrTime": "13:45", "airline": "海航",
        "flight_no": "HU7844", "cabin": "经济舱", "plane": "波音737(超长机型后缀词)",
        "planeSize": "大型机·宽体双通道远程旗舰机型", "bridgeRate": 88,
        "prate": 92, "meal": "正餐·点心·饮品三式服务包",
        "baggage": "免费托运23KG·手提7KG", "carryon": "手提行李额7KG",
        "labels": "经济舱售罄·含免费托运·老客专享·新客立减·会员日特惠·联程保障",
        "age": "限青年(16-23周岁)", "risk": "高风险政策",
        "share": "共享·南方航空CZ6993", "fewTicket": "票少",
        "cancelRate": 35, "lcc": True, "black": True,
        "discount": "4.9折超值折扣优惠", "transferBaggage": "recheck",
    }
    out = tmp_path / "t.png"
    rows = [("direct", [f], "✈️ 直飞最优 · 测试 10/05", {})]
    render_flights_table(rows, "极端超容行", str(out))
    assert out.exists() and out.stat().st_size > 1000


# ---- 推送审校 P1/P2（r224）：文案形态收口源码钉 ----

def _alerter_src():
    return open(os.path.join(_ROOT, "core", "alerter.py"),
                encoding="utf-8").read()


def test_kpi_pct_second_tier_dot_joined():
    """P1-2：KPI 行1 百分比尾注第二档间隔号连接——裸空格拼 pct 出
    「低￥50 3%」悬空百分数；「·」在确定安全字符集，与第一档全角
    括号态、第三档地板态成宽→窄降级链。r225 收单源 helper
    （_pct_fallback_forms，心跳两分支同源），内联档序表达式退役。"""
    src = _alerter_src()
    assert "forms = _pct_fallback_forms(base1, pct)" in src
    assert 'base1 + "·" + pct' not in src, "内联档序残留（须走 helper）"
    assert 'base1 + " " + pct' not in src, "旧裸空格档残留"


def test_daily_kpi_bold_tier_core_whole():
    """P1-3：日报 KPI 加粗范围=档位核整体（emoji+label+价），与主链路
    _kpi_block 同律一种实现（mini_kpi 单档粗为准）——旧「仅价粗」是
    同律两种实现，粗体分段语义漂移。"""
    src = _report_src()
    assert ('base = (f"**{core}**" if mark == TIER_EMOJI["qual"] + " "\n'
            '                    else core)') in src
    assert 'px = f"**{px}**" if mark == "🎯 "' not in src, "旧仅价粗残留"


def test_channel_market_lines_multiday_dated():
    """P1-4：图挂兜底「各渠道最低」行多日期带日期短标——sections 2+
    时两日期渠道价交错无主；单日期不带（常态不加状态标识律）。
    逐渠道前缀现居 _tops 收集元组（r289 P3-A 同价合并重构），机制
    断言随形态改写。"""
    src = _alerter_src()
    assert "_multi = len(sections) > 1" in src
    assert 'f"- {_dpre}{cn} 最低 "' in src
    assert 'f"- {_dpre}{cn} 最低 ￥{v:.0f}（全线价）"' in src
    assert 'f"- {_dpre}{_cnt_cn(len(_tops))}渠道 最低 "' in src


def test_skeleton_nb_keeps_word_boundary():
    """P2-5：去括号骨架档「（」换空格——双删把「→13:50（去哪儿）」
    剥成「13:50去哪儿」两词粘连；空格替换保词界净省 3 半角仍达标。"""
    src = _alerter_src()
    assert 'skeleton.replace("（", " ").replace("）", "")' in src
    assert 'skeleton.replace("（", "").replace("）", "")' not in src


def test_legacy_ops_split_second_segment_quoted():
    """P2-6：legacy「本轮无数据渠道」拆段后第二段补引用前缀——裸名单
    段与 ⚠️ 头视觉脱钩；names 经 _fit_line ≤40 半角=短块（钉钉引用块
    拆短块定律达标）。"""
    src = _alerter_src()
    assert 'heads + "\\n\\n> " + _fit_line(' in src
