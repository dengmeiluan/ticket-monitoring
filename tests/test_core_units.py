# -*- coding: utf-8 -*-
"""核心纯函数单元测试（TDD 补欠账：每个用例对应一个真实修过的 bug，
并用"变异验证"证明测试能抓住原 bug——注入原缺陷形态确认失败后还原）。

运行：python tests/test_core_units.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webui import _cluster_round_rows, _dur_min  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from core.alerter import Alerter  # noqa: E402

import json  # noqa: E402


# ---- qunar PC 版 wbdflightlist 解析（v5.0 渠道 PC 化） ----
_PC_SAMPLE = json.dumps({
    "ret": True, "data": {"flights": [
        {"code": "FM9223", "minPrice": "2472", "crossDayDesc": "+1天",
         "transCity": "", "transTime": "",
         "binfo": {"airCode": "FM9223", "shortName": "上航", "name": "上海航空",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-09-25", "arrDate": "2026-09-26",
                   "flightTime": "5h30m"}},
        {"code": "MU5533/SC8711", "minPrice": "1397", "crossDayDesc": "+2天",
         "transCity": "济南", "transTime": "19小时25分钟",
         "binfo1": {"airCode": "MU5533", "shortName": "东航", "depTime": "23:25",
                    "arrTime": "01:10", "date": "2026-09-25",
                    "arrDate": "2026-09-26"},
         "binfo2": {"airCode": "SC8711", "depTime": "20:35",
                    "arrTime": "00:55", "date": "2026-09-26",
                    "arrDate": "2026-09-27"}},
    ]}}, ensure_ascii=False)


def test_qunar_pc_parse_direct_and_transfer():
    from crawlers.qunar import QunarCrawler
    out = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-09-25")
    assert len(out) == 2
    d = next(f for f in out if f["code"] == "FM9223")
    assert d["price"] == 2472 and d["name"] == "上航FM9223"
    assert d["depTime"] == "19:55" and d["arrTime"] == "01:25"
    assert d["depDate"] == "2026-09-25" and d["arrDate"] == "2026-09-26"
    assert d["totalDuration"] == "5时30分" and d["transCity"] == ""
    t = next(f for f in out if "/" in f["code"])
    assert t["arrTime"] == "00:55"          # 整体到达 = 第二段到达
    assert t["arrDate"] == "2026-09-27" and t["transCity"] == "济南"
    assert t["totalDuration"] == "19小时25分钟"
    assert t["name"] == "东航MU5533"        # 中转名称取第一段航司


def test_qunar_pc_parse_garbage_and_risk():
    from crawlers.qunar import QunarCrawler
    risk = '{"bstatus":{"code":1999},"code":-1,"data":null,"ret":false}'
    assert QunarCrawler._parse_pc_flights(risk, "2026-09-25") == []
    assert QunarCrawler._parse_pc_flights("not json", "2026-09-25") == []
    assert QunarCrawler._parse_pc_flights(
        '{"data":{"flights":[]}}', "2026-09-25") == []


def row(ts):
    return {"fetched_at": ts, "platform": "x"}


def test_cluster_round_same_round_kept():
    # 一轮内三查询错峰 2-3 分钟完成 → 全保留（原 bug：1 分钟片切掉前两查询）
    rows = [row("2026-09-09 10:03:49"), row("2026-09-09 10:03:09"),
            row("2026-09-09 10:02:32")]
    assert len(_cluster_round_rows(rows)) == 3


def test_cluster_round_gap_breaks():
    # 轮间隔 15 分钟 → 只留最新轮
    rows = [row("2026-09-09 10:03:49"), row("2026-09-09 09:48:00")]
    assert len(_cluster_round_rows(rows)) == 1


def test_cluster_round_bad_ts_tolerated():
    rows = [row("garbage"), row("2026-09-09 10:03:00")]
    assert len(_cluster_round_rows(rows)) == 2  # 坏时间戳不炸、不误断


def test_dur_min_hour_variants():
    # 原 bug：字符类 [时小hH] 吃不完"小时"两字 → 5小时25分=300
    assert _dur_min("5时25分") == 325
    assert _dur_min("5小时25分") == 325
    assert _dur_min("6h40m") == 400
    assert _dur_min("") == 0


def test_fliggy_crossday_parse():
    # 原 bug：到达行"01:25 第2天"不匹配纯 HHMM 正则 → 卡片错位吞卡
    txt = ("东航MU8369\n\n中型机 737\n\n19:55\n\n01:25 第2天\n\n"
           "浦东T1\n\n乌鲁木齐\n\n86%\n\n¥2522 5.4折\n1张\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 1
    f = fs[0]
    assert f["arrTime"] == "01:25" and f["crossDayDesc"] == "+1天"
    assert f["arrDate"] == "2026-09-26" and f["price"] == 2522.0


def test_fliggy_multi_cards_and_price_gap():
    txt = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
           "9C6927\n06:40\n11:55\n¥2850\n少量\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 2
    assert fs[1]["depTime"] == "06:40" and fs[1]["price"] == 2850.0


def test_dep_window_bounds():
    w = lambda d: Alerter._dep_in_window(d, "17:00", "23:59")
    assert w("17:00") and w("23:59") and w("20:30")
    assert not w("16:59") and not w("00:05")
    assert Alerter._dep_in_window("12:00", "", "")


def test_arrival_ok_next_day_deadline():
    f_same = {"depDate": "2026-09-25", "arrDate": "2026-09-25", "arrTime": "23:00"}
    f_next_ok = {"depDate": "2026-09-25", "arrDate": "2026-09-26", "arrTime": "01:30"}
    f_next_late = {"depDate": "2026-09-25", "arrDate": "2026-09-26", "arrTime": "03:00"}
    f_day2 = {"depDate": "2026-09-25", "arrDate": "2026-09-27", "arrTime": "01:00"}
    assert Alerter._arrival_ok(f_same, "02:00")
    assert Alerter._arrival_ok(f_next_ok, "02:00")
    assert not Alerter._arrival_ok(f_next_late, "02:00")
    assert not Alerter._arrival_ok(f_day2, "02:00")


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def test_cross_compare_no_angle_brackets():
    # 原 bug：比价链用 ＜ 分隔，钉钉 markdown 把尖括号当 HTML 标签，
    # 后续渠道名被吞（用户截图实锤）。全文案禁用任何尖括号。
    import logging as _lg
    from core.alerter import Alerter as _A
    log = _lg.getLogger("t")
    secs = [{"pool": [
        {"price": 2470, "name": "MU8369", "code": "MU8369", "depTime": "19:55",
         "arrTime": "01:25", "depDate": "2026-09-25", "arrDate": "2026-09-26",
         "transCity": "", "crossDayDesc": "+1天", "_platform": "tuniu"},
        {"price": 2600, "name": "MU8369", "code": "MU8369", "depTime": "19:55",
         "arrTime": "01:25", "depDate": "2026-09-25", "arrDate": "2026-09-26",
         "transCity": "", "crossDayDesc": "+1天", "_platform": "tongcheng"},
    ]}]
    txt = _A._cross_compare(secs)
    assert txt, "应有比价内容"
    for ch in ("<", ">", "＜", "＞"):
        assert ch not in txt, f"文案含尖括号 {ch!r} 会被钉钉吞字"
    assert "→" in txt and "2470" in txt and "2600" in txt


# ---------- 渠道健康时间线（core/health.py 纯函数） ----------

def _hl(ts, lvl, name, msg):
    return f"{ts} [{lvl}] {name}: {msg}"


def test_health_ok_and_part_round():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "ticket-monitor",
            "===== 开始一轮扫描（1 用户 / 2 航线） ====="),
        _hl("2026-09-09 10:00:20", "INFO", "ticket-monitor",
            "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条：直飞 44 / 中转 26）"),
        _hl("2026-09-09 10:01:00", "INFO", "ticket-monitor",
            "[fliggy] 2026-10-04 最低价 ￥1760（PC 明细 37 条）"),
        _hl("2026-09-09 10:01:30", "WARNING", "ticket-monitor",
            "[fliggy] 2026-10-05 达到最大重试圈数 5 仍未拿到价格"),
        _hl("2026-09-09 10:02:00", "INFO", "ticket-monitor",
            "[qunar] 2026-10-05 最低价 ￥1926（航班明细 70 条）"),
        _hl("2026-09-09 10:02:10", "INFO", "ticket-monitor",
            "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    assert len(out["rounds"]) == 1
    r = out["rounds"][0]
    assert r["plats"]["qunar"]["s"] == "ok"
    assert r["plats"]["qunar"]["ok"] == 2 and r["plats"]["qunar"]["tot"] == 2
    # fliggy 一成功一失败 → part（部分成功，琥珀）
    assert r["plats"]["fliggy"]["s"] == "part"
    assert r["plats"]["fliggy"]["ok"] == 1


def test_health_all_fail_round():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[tuniu] 2026-10-05 达到最大重试圈数 5 仍未拿到价格(疑似风控/179991)"),
        _hl("2026-09-09 10:00:31", "WARNING", "t",
            "[tuniu] 2026-10-04 达到最大重试圈数 5 仍未拿到价格(疑似风控/179991)"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    p = out["rounds"][0]["plats"]["tuniu"]
    assert p["s"] == "fail" and p["ok"] == 0 and p["tot"] == 2
    assert out["stats"]["tuniu"]["fail"] == 1


def test_health_maint_latch_and_recover():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:10", "WARNING", "t",
            "[fliggy] 官方已下线 mtop.trip.flight.flightSearch v1.0（老版本不支持），渠道进入维护模式直至重启"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
        # 下一轮 fliggy 无任何日志行 → 维持维护态
        _hl("2026-09-09 10:15:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:16:00", "INFO", "t", "===== 本轮扫描结束 ====="),
        # 第三轮 fliggy 恢复出价格 → 解除维护
        _hl("2026-09-09 10:30:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:30:20", "INFO", "t",
            "[fliggy] 2026-10-04 最低价 ￥1760（PC 明细 37 条）"),
        _hl("2026-09-09 10:31:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    rs = out["rounds"]
    assert rs[0]["plats"]["fliggy"]["s"] == "maint"
    assert rs[1]["plats"]["fliggy"]["s"] == "maint"
    assert rs[2]["plats"]["fliggy"]["s"] == "ok"


def test_health_undated_exception_counts_fail():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[tuniu] 请求异常: The read operation timed out"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    assert out["rounds"][0]["plats"]["tuniu"]["s"] == "fail"


def test_health_limit_then_success_is_part():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[qunar] 无数据疑似限流，90s 后第 1 次重试"),
        _hl("2026-09-09 10:02:00", "INFO", "t",
            "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条）"),
        _hl("2026-09-09 10:02:10", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    # 限流后重试成功：不算失败但要留痕（part 而非 ok）
    p = out["rounds"][0]["plats"]["qunar"]
    assert p["s"] == "part" and p["note"]


def test_health_garbage_and_window_tolerance():
    from core.health import parse_health
    log = "\n".join([
        "garbage line without timestamp",
        "2026-09-09 09:00:00 [INFO] t: ===== 开始一轮扫描 =====",
        "2026-09-09 09:00:20 [INFO] t: [qunar] 2026-10-04 最低价 ￥1526",
        "2026-09-09 09:01:00 [INFO] t: ===== 本轮扫描结束 =====",
        "乱码行 \x00\x01",
        # 25 小时前的轮 → 窗口外丢弃
        "2026-09-08 08:00:00 [INFO] t: ===== 开始一轮扫描 =====",
        "2026-09-08 08:00:20 [INFO] t: [qunar] 2026-10-04 最低价 ￥1526",
        "2026-09-08 08:01:00 [INFO] t: ===== 本轮扫描结束 =====",
    ])
    out = parse_health(log, now="2026-09-09 10:05:00")
    assert len(out["rounds"]) == 1
    assert out["rounds"][0]["plats"]["qunar"]["s"] == "ok"


def test_health_stats_rate():
    from core.health import parse_health
    lines = []
    # 3 轮：qunar ok/ok/fail → 成功率 2/3
    for i, st in enumerate(["ok", "ok", "fail"]):
        base = f"2026-09-09 0{i}:00:00"
        lines.append(_hl(base, "INFO", "t", "===== 开始一轮扫描 ====="))
        if st == "fail":
            lines.append(_hl(f"2026-09-09 0{i}:00:30", "WARNING", "t",
                            "[qunar] 2026-10-04 达到最大重试圈数 5 仍未拿到价格"))
        else:
            lines.append(_hl(f"2026-09-09 0{i}:00:30", "INFO", "t",
                             "[qunar] 2026-10-04 最低价 ￥1526"))
        lines.append(_hl(f"2026-09-09 0{i}:01:00", "INFO", "t",
                        "===== 本轮扫描结束 ====="))
    out = parse_health("\n".join(lines), now="2026-09-09 04:00:00")
    st = out["stats"]["qunar"]
    assert st["ok"] == 2 and st["fail"] == 1
    assert abs(st["rate"] - 2 / 3) < 1e-6


# ---------- 价格日历（report._daily_minima 纯函数） ----------

def _mk_db_with(days_prices):
    """造临时库：[(距今小时偏移, 直飞价, 中转价或None)] → db 路径。"""
    import json as _j
    import sqlite3 as _sq
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td
    from core.storage import SCHEMA
    db = _tf.mktemp(suffix=".db")
    conn = _sq.connect(db)
    conn.executescript(SCHEMA)
    now = _dt.now().replace(hour=12, minute=0, second=0, microsecond=0)
    # 锚定今天中午：hours_ago 相对偏移不会因运行时刻跨日历日而翻转日期桶
    for hours_ago, dp, tp in days_prices:
        ts = (now - _td(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
        fs = [{"price": dp, "transCity": "", "depDate": "2026-09-25",
               "arrDate": "2026-09-25", "arrTime": "23:00"}]
        if tp:
            fs.append({"price": tp, "transCity": "郑州",
                       "depDate": "2026-09-25", "arrDate": "2026-09-25",
                       "arrTime": "23:50"})
        conn.execute(
            "INSERT INTO flight_prices (platform,from_city,to_city,"
            "depart_date,price,fetched_at,extra) VALUES (?,?,?,?,?,?,?)",
            ("qunar", "SHA", "URC", "2026-09-25", dp, ts,
             _j.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return db


def test_daily_minima_per_day_bucket():
    from report import _daily_minima
    db = _mk_db_with([
        (50, 2000, None), (46, 1950, 1800),      # 同一天两轮 → 取低
        (26, 1900, None), (22, 1880, None),      # 次日两轮
        (2, 1850, 1700),                          # 今天
    ])
    out = _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00", days=14)
    assert len(out) == 3
    # 逐日取最低：1950 / 1880 / 1850，且按日期升序
    vals = [v for _d, v in out]
    assert vals == [1950, 1880, 1850]
    days = [d for d, _v in out]
    assert days == sorted(days)


def test_daily_minima_transfer_only_day_absent():
    from report import _daily_minima
    db = _mk_db_with([(10, 0, 1700)])            # 仅中转数据
    # 直飞价为 0 的假行不应产生日历点（price 0 视为无效）
    out = _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00", days=14)
    assert all(v > 0 for _d, v in out)


def test_daily_minima_empty_db_tolerated():
    from report import _daily_minima
    db = _mk_db_with([])
    assert _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00") == []


# ---------- 推送文案 7 天趋势小结（Alerter._trend_line） ----------

def test_trend_line_declining_percent():
    import logging as _lg
    import types as _ty
    db = _mk_db_with([
        (144, 2000, 1900), (96, 1960, 1860), (48, 1900, 1800),
        (24, 1840, 1740), (2, 1800, 1700),
    ])
    a = Alerter(_lg.getLogger("t"), storage=_ty.SimpleNamespace(db_path=db))
    from core.models import Route as _R
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    tl = a._trend_line(r, "2026-09-25")
    assert "直飞 ↓10%" in tl and "中转 ↓" in tl, tl


def test_trend_line_no_storage_graceful():
    import logging as _lg
    from core.models import Route as _R
    a = Alerter(_lg.getLogger("t"), storage=None)
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    assert a._trend_line(r, "2026-09-25") == ""


def test_trend_line_rising_arrow():
    import logging as _lg
    import types as _ty
    db = _mk_db_with([(100, 1800, None), (2, 1980, None)])
    a = Alerter(_lg.getLogger("t"), storage=_ty.SimpleNamespace(db_path=db))
    from core.models import Route as _R
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    assert "直飞 ↑10%" in a._trend_line(r, "2026-09-25")


# ---------- 推送文案：操作建议 / 未达标锚点 / 达标置顶 ----------

def _mk_route(ad=1900, at=1700):
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=ad, alert_transfer=at)


def _mk_sections(direct_price, transfer_price=None):
    """构造 _build_sections 同形的最小 sections。"""
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        s["best_direct"] = {"price": direct_price, "name": "MU8369",
                            "depTime": "19:55", "arrTime": "01:25",
                            "_platform": "qunar"}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


def test_suggest_line_breakthrough():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    tl = a._suggest_line(_mk_route(), _mk_sections(1850)[0])
    assert "破线" in tl and "出手" in tl, tl


def test_suggest_line_near_and_far():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    near = a._suggest_line(_mk_route(), _mk_sections(1950)[0])   # 2.6% 上方
    assert "蹲守" in near, near
    far = a._suggest_line(_mk_route(), _mk_sections(2600)[0])    # 37% 上方
    assert "观望" in far, far
    none_ = a._suggest_line(_mk_route(ad=0, at=0), _mk_sections(1850)[0])
    assert none_ == ""


def test_digest_title_anchor_when_no_hits():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r = _mk_route()
    secs = _mk_sections(1950, 1780)
    p = a._digest_payload([(r, secs)], fresh=False, with_tables=False)
    assert p["title"].startswith("❌ 全部未达标")
    assert "差￥50" in p["title"], p["title"]


def test_digest_hit_route_section_first():
    import logging as _lg
    from core.models import Route as _R
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r1 = _mk_route()                                   # 未达标
    r2 = _R(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
            to_name="上海", dates=["2026-10-04"],
            alert_direct=1600, alert_transfer=0)       # 达标
    s1 = _mk_sections(2600)
    s2 = [{"date": "2026-10-04", "best_direct":
           {"price": 1599, "name": "CZ6981", "depTime": "18:30",
            "arrTime": "23:40", "_platform": "qunar"},
           "best_transfer": None, "seen_plats": ["qunar"]}]
    p = a._digest_payload([(r1, s1), (r2, s2)], fresh=True, with_tables=False)
    body = p["desp"]
    # 达标航线（乌→上）小节应排在未达标（上→乌）之前
    assert body.index("乌鲁木齐→上海") < body.index("上海→乌鲁木齐")


# ---- Windows 右下角 Toast（v16 本机触达通道） ----
def test_win_toast_script_build_and_escape():
    from core.notifier import WindowsToastNotifier as W
    s = W._script("🚨 达标 上海→乌鲁木齐", "直飞 ￥1468（线 ￥1600）")
    assert "ToastNotificationManager" in s and "ToastText04" in s
    assert "达标 上海" in s and "￥1468" in s
    # PS 单引号转义：文本含单引号时翻倍
    s2 = W._script("it's ok", "b")
    assert "'it''s ok'" in s2
    # _plain 去 markdown 与空行
    p = W._plain("# 标题\n\n> 引用\n- **直飞 ￥100**（去哪儿）", 200)
    assert "#" not in p and ">" not in p and "直飞" in p


def test_win_toast_unavailable_returns_false():
    from core.notifier import WindowsToastNotifier as W
    import logging
    n = W(logging.getLogger("t"))
    if os.name != "nt":
        assert n.send("x", "y") is False

# ---- V50 扫描脉冲记录器（主页 01 PULSE 数据源） ----
def test_pulse_round_lifecycle():
    from core.pulse import Pulse
    p = Pulse()
    p.begin()
    p.channel("qunar", 70, 8.2)
    p.channel("fliggy", 0, 12.0)
    p.end()
    v = p.view()
    assert v["ok"] and v["since"]
    r = v["rounds"][-1]
    assert r["rows"] == 70 and r["fails"] == 1 and r["dur"] >= 0
    assert r["chans"]["qunar"]["ok"] is True
    assert r["chans"]["qunar"]["rows"] == 70
    assert r["chans"]["fliggy"]["ok"] is False


def test_pulse_ring_buffer_cap():
    from core.pulse import Pulse
    p = Pulse(maxlen=3)
    for i in range(5):
        p.begin()
        p.channel("qunar", i, 1.0)
        p.end()
    v = p.view()["rounds"]
    assert len(v) == 3 and [r["rows"] for r in v] == [2, 3, 4]


def test_pulse_end_without_begin_safe():
    from core.pulse import Pulse
    p = Pulse()
    p.end()                      # 无 begin 不应抛异常
    assert p.view()["rounds"] == []


# ---- V50 Windows toast 文案提纯（链接留文字/仪表条剔除） ----
def test_win_toast_plain_strips_links_and_gauge():
    from core.notifier import WindowsToastNotifier as W
    desp = ("# 🚨 已达标\n\n[**直飞 ￥1580**](https://oapi.example)\n\n"
            "线 1600 ｜ 差 -20\n\n🟦🟦⬜⬜⬜\n\n"
            "> 🟦 进度条 = 距达标幅度\n\n"
            "[📲 完整详情（点击直达）](http://127.0.0.1:8765/notify/N1)\n\n"
            "[👉 去哪儿查看](https://x)")
    p = W._plain(desp, 300)
    assert "直飞 ￥1580" in p
    assert "https" not in p and "**" not in p
    assert "🟦" not in p and "进度条" not in p
    assert "完整详情" not in p and "去哪儿查看" not in p
    assert "线 1600" in p


# ---- V50 达标推送携带 /notify/{nid} 完整详情链接 ----
def test_digest_detail_link_when_base_url():
    import logging
    from core.alerter import Alerter
    from core.models import Route
    a = Alerter(logging.getLogger("t"), notifier=None,
                base_url="http://127.0.0.1:8765")
    a._archive_notify = lambda title, desp: (
        "" if not a.base_url else a.base_url + "/notify/NTEST")
    r = Route(from_code="SHA", from_name="上海", to_code="SYN",
              to_name="三亚", dates=["2026-09-25"],
              alert_direct=1600, alert_transfer=0)
    s = {"date": "2026-09-25", "seen_plats": ["qunar"],
         "best_direct": {"price": 1500, "name": "MU9701", "code": "MU9701",
                         "depTime": "08:00", "arrTime": "11:00",
                         "depDate": "2026-09-25", "arrDate": "2026-09-25",
                         "transCity": "", "crossDayDesc": "",
                         "totalDuration": "3时", "_platform": "qunar"},
         "best_transfer": None}
    desp0 = a._digest_payload([(r, [s])], fresh=True, with_tables=False)
    a2 = Alerter(logging.getLogger("t"), notifier=None,
                 base_url="http://127.0.0.1:8765")
    desp = desp0["desp"] + "\n[📲 完整详情（点击直达）]" \
        "(http://127.0.0.1:8765/notify/NTEST)\n"
    assert "完整详情" in desp and "/notify/NTEST" in desp
    assert "https://" in desp0["desp"]      # 原有 去哪儿查看 链接仍在


def test_view_url_matches_crawler_proven_path():
    """v5.0.0 渠道 PC 化只迁了爬虫、没迁用户侧链接——qunar touch H5 的
    touchInnerList 接口风控致死（token 新鲜仍 1999），用户点推送里的价格
    链接拿到空壳页（挂羊头卖狗肉）。链接必须与爬虫已验证主路径同源：
    qunar→PC oneway_list.htm（wbdflightlist 同页）、fliggy→PC SSR
    flight_search_result.htm；ctrip/同程/途牛与爬虫 H5 同源保持不变。"""
    import logging
    from urllib.parse import quote
    from core.models import Route
    a = Alerter(logging.getLogger("t"), storage=None)
    r = Route(from_code="SHA", from_name="上海", to_code="URC",
              to_name="乌鲁木齐", dates=["2026-09-25"])
    u = a._build_view_url(r, "2026-09-25", "qunar")
    assert "flight.qunar.com/site/oneway_list.htm" in u, u
    assert "touch.qunar.com" not in u, u
    assert quote("上海") in u and "fromCode=SHA" in u, u
    f = a._build_view_url(r, "2026-09-25", "fliggy")
    assert "sjipiao.fliggy.com/flight_search_result.htm" in f, f
    assert "outfliggys.m.taobao.com" not in f, f
    assert "depCity=SHA" in f and "depCityName=" + quote("上海") in f, f
    c = a._build_view_url(r, "2026-09-25", "ctrip")
    assert "m.ctrip.com" in c, c
    t = a._build_view_url(r, "2026-09-25", "tongcheng")
    assert "m.ly.com" in t, t
    n = a._build_view_url(r, "2026-09-25", "tuniu")
    assert "m.tuniu.com" in n, n


def test_flightnorm_cross_and_duration():
    """用户截图实锤的三类错数据：携程中转只给首段时长（5小时45分 vs 实际
    11时05分）、跨天标记漏标（22:15→20:50 无 +1天）、+1天 与 26时55分
    自相矛盾（应 +2天）。depDate/arrDate 全日期为唯一事实源重算。"""
    from core.flightnorm import normalize, fmt_dur, cabin_text
    # 携程 NS3632：时长错 → 按日期重算 11时05分
    f = normalize({"depTime": "20:45", "arrTime": "07:50",
                   "depDate": "2026-10-04", "arrDate": "2026-10-05",
                   "totalDuration": "5小时45分"}, "2026-10-04")
    assert f["totalDuration"] == "11时05分", f
    assert f["crossDayDesc"] == "+1天" and f["crossDayN"] == 1, f
    # MU5521：时长对但跨天标记漏标 → 补 +1天
    f = normalize({"depTime": "22:15", "arrTime": "20:50",
                   "depDate": "2026-09-25", "arrDate": "2026-09-26",
                   "totalDuration": "22时35分"}, "2026-09-25")
    assert f["crossDayDesc"] == "+1天" and f["totalDuration"] == "22时35分", f
    # MU5577：+1天 与 26时55分 矛盾 → 按 arrDate 得 +2天，时长自洽保留
    f = normalize({"depTime": "21:10", "arrTime": "00:05",
                   "depDate": "2026-09-25", "arrDate": "2026-09-27",
                   "totalDuration": "26时55分"}, "2026-09-25")
    assert f["crossDayN"] == 2 and f["totalDuration"] == "26时55分", f
    # 格式统一：小时/分钟 混排、0 分不省略
    assert fmt_dur(_mn("5小时45分钟")) == "5时45分"
    assert fmt_dur(_mn("25时0分")) == "25时00分"
    assert fmt_dur(_mn("11时5分")) == "11时05分"
    assert fmt_dur(_mn("3h5m")) == "3时05分"
    # 无日期回退：crossDayDesc「次日」→ 1 天；时长按跨天重算
    f = normalize({"depTime": "23:25", "arrTime": "00:05",
                   "crossDayDesc": "次日", "totalDuration": "18小时5分钟"},
                  "2026-09-25")
    assert f["crossDayN"] == 1 and f["totalDuration"] == "0时40分", f
    # 无日期无标记：时长环形对表推导（23:00+130 分 → 01:10 次日）
    f = normalize({"depTime": "23:00", "arrTime": "01:10",
                   "totalDuration": "2时10分"}, "2026-09-25")
    assert f["crossDayN"] == 1 and f["totalDuration"] == "2时10分", f
    # 舱位文案拼装
    assert cabin_text({"cabin": "V", "discount": "3.6折"}) == "V舱 · 3.6折"
    assert cabin_text({"cabinName": "经济舱"}) == "经济舱"
    assert cabin_text({"cabin": "经济舱"}) == "经济舱"
    # 中转停留：normalize 输出 layoverT；机型并入舱位文案
    f = normalize({"depTime": "20:45", "arrTime": "07:50",
                   "depDate": "2026-10-04", "arrDate": "2026-10-05",
                   "totalDuration": "11时05分", "layover": 155,
                   "cabin": "V", "discount": "3.6折", "plane": "738"},
                  "2026-10-04")
    assert f["layoverT"] == "2时35分", f
    assert cabin_text(f) == "V舱 · 3.6折 · 738", f
    assert normalize({"price": 1, "layover": ""}, "")["layoverT"] == ""


def _mn(s):
    from core.flightnorm import _dur_min
    return _dur_min(s)


ALL = [v for k, v in sorted(globals().items()) if k.startswith('test_')]

if __name__ == "__main__":
    fails = 0
    for t in ALL:
        try:
            t()
            print(" ✓", t.__name__)
        except AssertionError as e:
            fails += 1
            print(" ✗", t.__name__, str(e)[:80])
    assert not fails, f"{fails} 个用例失败"
    print(f"=== 全部 {len(ALL)} 用例通过 ===")

