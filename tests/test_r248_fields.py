# -*- coding: utf-8 -*-
"""r248 数据层五案（TDD 先行，测试全部先红后绿）：

D1 过期日期滚动标注——监控日期过期后渠道把过期查询滚动为其他日期航班
照常返回，按请求日期落桶即把别的日期的价挂进过期桶（曲线画活点、
推送日期错位，10-06 实证 21 轮+推送「10/05 直飞差￥570」实为 10-06
航班）。三层防线：normalize 打 _dep_mismatch 标（三端解析共用单源）+
曲线/推送/列表三端消费过滤 + sweep 跳过过期日期查询（治本）。
误杀面预演（_scratch/r248_d1_mismatch.txt）：全库 68.9 万元素仅在
滚动期组合命中（10-05 行×10-06/10-07 元素），正常期零错位。

D2 渠道整轮零记录哨——tuniu 风控断供 11.5h+（ok=false rows=0）对
noDet/塌方/绝对下限三哨全盲：无记录→行历史不入池→重启后永不入池。
零记录形态与「有记录 0 行明细」不同，须在 sweep 渠道行数聚合层观测。

D3 曲线端幻影守卫对齐行级口径——列表/告警链=行级守卫（行价 vs 其他
渠道行价中位），曲线=元素级守卫（桶内元素池锚）。双渠道同轮污染时
元素级池锚被拖歪（观测桶②：中转桶仅 3 渠道有元素，锚中位 1699 vs
行级池 5 渠道中位 2324），毒价 1034 逃过 0.5× 上图并挂「行情破线」
旗标；健康元素随毒行「图有列无」（观测桶①）。修法：曲线桶构建先按
行级守卫整行剔除（与列表/告警同一可信口径），元素级守卫保留作第二层。

C1 qunar listPopView 弹层 → ticketRisk 新键（调研 chA：渠道本代际
新部署的行级购买风险警示，载体行 fewTicket/labels/refundChange 全空，
行级唯一风险出口）。双词面守卫（title 含「提示」且 mainText 含
「值机柜台」）+ font 标签 strip，防弹层被复用为营销位。

C2 ctrip aset 词面「中转餐食」白名单补词（调研 chA：逐字配对证伪
r247「已采✓」记录——实采的是「中转餐饮」，两词面并存异域产品；
银川中转 GJ8651/MF8531 行唯一餐食域词面，不收则永久缺失）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r248_fields.py
"""
import json
import logging
import os
import sqlite3
import sys

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
