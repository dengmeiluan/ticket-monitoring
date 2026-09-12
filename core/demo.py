# -*- coding: utf-8 -*-
"""演示模式数据（`python webui.py --demo`）：零配置体验控制台全部可视化。

build_demo_db(path)：真实 flight_prices schema 的合成库——
  48h 走势历史（每 30min 一轮 × 3 航线）+ 富细节当轮明细（5 渠道）。
  前端/预览/走势全部走与真机同一条渲染链路，零特判。
demo_health()：与 core.health.parse_health 同形的合成健康时间线。
"""
import json
import random
import sqlite3
from datetime import datetime, timedelta

from core.storage import SCHEMA

_PLATS = ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"]


def _d(days):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def demo_routes():
    """演示航线定义（dict，webui 侧再转 Route 对象）。"""
    return [
        {"from": "SHA", "from_name": "上海", "to": "URC", "to_name": "乌鲁木齐",
         "dates": [_d(16)], "alert_direct": 1900, "alert_transfer": 1700,
         "transfer_arrival_max": "02:00", "dep_time_min": "", "dep_time_max": ""},
        {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA", "to_name": "上海",
         "dates": [_d(25)], "alert_direct": 1600, "alert_transfer": 1500,
         "transfer_arrival_max": "02:00", "dep_time_min": "17:00",
         "dep_time_max": ""},
        {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA", "to_name": "上海",
         "dates": [_d(26)], "alert_direct": 1600, "alert_transfer": 1500,
         "transfer_arrival_max": "02:00", "dep_time_min": "", "dep_time_max": ""},
    ]


def demo_cfg(db_path, port=8765):
    return {"output": {"db_path": db_path, "log_path": "logs/monitor.log"},
            "web": {"port": port}}


def _flight(price, name, code, dpt, art, dep_date, days=0, trans="",
            cross="", dur="", cabin="", layover="", plane="", discount=""):
    d0 = datetime.strptime(dep_date, "%Y-%m-%d").date()
    return {"price": price, "name": name, "code": code, "depTime": dpt,
            "arrTime": art, "depDate": dep_date,
            "arrDate": (d0 + timedelta(days=days)).strftime("%Y-%m-%d"),
            "transCity": trans, "crossDayDesc": cross,
            "totalDuration": dur or "5时25分",
            "cabin": cabin, "layover": layover, "plane": plane,
            "discount": discount}


def _mk_detail(rng, plat, dep_date, base, dep_min_only=False):
    """某渠道某航线的一批明细（直飞为主 + 少量中转）。"""
    airlines = [("南航CZ6976", "CZ6976"), ("东航MU8369", "MU8369"),
                ("春秋9C8866", "9C8866"), ("上航FM9220", "FM9220"),
                ("国航CA1295", "CA1295"), ("海航HU7815", "HU7815"),
                ("天津GS7728", "GS7728"), ("山航SC4664", "SC4664")]
    slots = [("06:40", "11:55", 0), ("08:20", "13:40", 0),
             ("12:05", "17:30", 0), ("15:20", "20:45", 0),
             ("17:05", "22:30", 0), ("19:55", "01:25", 1),
             ("21:10", "02:35", 1)]
    fs = []
    for i, (nm, code) in enumerate(airlines):
        dpt, art, plus = slots[(i + hash(plat) % 3) % len(slots)]
        if dep_min_only and dpt < "17:00":
            continue
        price = base + rng.randint(-120, 160)
        cross = "+1天" if plus else ""
        fs.append(_flight(price, nm, code, dpt, art, dep_date,
                          days=plus, cross=cross,
                          dur="5时%d分" % rng.randint(5, 55),
                          cabin="经济舱", plane="738"))
    # 两条中转（一条达标约束内、一条超时）
    fs.append(_flight(base - 160, "南航CZ6976转", "CZ6976", "12:05", "23:50",
                      dep_date, days=0, trans="郑州", dur="11时45分",
                      cabin="经济舱", layover=175, plane="320",
                      discount="4.2折"))
    fs.append(_flight(base - 200, "山航SC4664转", "SC4664", "15:20", "05:40",
                      dep_date, days=1, trans="青岛", cross="+1天",
                      dur="14时20分", cabin="经济舱", layover=310,
                      plane="738", discount="3.8折"))
    return fs


def build_demo_db(path, seed=20260909):
    """生成演示库：48h 历史 + 当轮明细（确定性种子，截图可复现）。"""
    rng = random.Random(seed)
    routes = demo_routes()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM flight_prices")
    now = datetime.now().replace(second=0, microsecond=0)
    # ---- 14 天历史：每 30min 一轮（长坡缓降，末段刺破阈值；
    #      供 48h 走势图 / 7d 范围 / 14 天价格日历三个视图共用） ----
    curves = {
        0: dict(d0=2680, d1=1850, t0=2150, t1=1660),   # 上→乌 直飞破线 1900
        1: dict(d0=2200, d1=1580, t0=1880, t1=1520),   # 乌→上 10/04 直飞破线
        2: dict(d0=2900, d1=2440, t0=2300, t1=1930),   # 乌→上 10/05 未达标
    }
    n = 14 * 48
    for i in range(n):
        ts = now - timedelta(minutes=30 * (n - 1 - i))
        ts_s = ts.strftime("%Y-%m-%d %H:%M:%S")
        for ri, r in enumerate(routes):
            c = curves[ri]
            k = i / (n - 1)
            dp = round(c["d0"] + (c["d1"] - c["d0"]) * k + rng.uniform(-35, 35))
            tp = round(c["t0"] + (c["t1"] - c["t0"]) * k + rng.uniform(-30, 30))
            dep_min_only = bool(r["dep_time_min"])
            extra = [
                _flight(dp, "东航MU8369", "MU8369",
                        "19:55" if not dep_min_only else "18:40",
                        "01:25" if not dep_min_only else "23:30",
                        r["dates"][0], days=0 if not dep_min_only else 0,
                        cross="" if not dep_min_only else ""),
                _flight(tp, "南航CZ6976转", "CZ6976", "12:05", "23:50",
                        r["dates"][0], trans="郑州", dur="11时45分"),
            ]
            conn.execute(
                "INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, airline, flight_no, fetched_at, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (_PLATS[(i + ri) % len(_PLATS)], r["from"], r["to"],
                 r["dates"][0], min(dp, tp), "东航", "MU8369", ts_s,
                 json.dumps(extra, ensure_ascii=False)))
    # ---- 当轮富明细：近 30 分钟内，5 渠道 × 3 航线 ----
    for pi, plat in enumerate(_PLATS):
        ts_s = (now - timedelta(minutes=4 + pi * 3)).strftime(
            "%Y-%m-%d %H:%M:%S")
        for ri, r in enumerate(routes):
            c = curves[ri]
            base = {"qunar": 0, "ctrip": -30, "fliggy": 60,
                    "tongcheng": 90, "tuniu": 120}[plat]
            fs = _mk_detail(rng, plat, r["dates"][0], c["d1"] + base,
                            dep_min_only=bool(r["dep_time_min"]))
            conn.execute(
                "INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, airline, flight_no, fetched_at, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (plat, r["from"], r["to"], r["dates"][0],
                 min(f["price"] for f in fs), "", "", ts_s,
                 json.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return path


def demo_health(hours=24, seed=7):
    """合成健康时间线（与 parse_health 输出同形）。"""
    rng = random.Random(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    rounds = []
    n = hours * 4                       # 15min 一轮
    for i in range(n):
        ts = now - timedelta(minutes=15 * (n - 1 - i))
        plats = {}
        for plat in _PLATS:
            roll = rng.random()
            if plat == "fliggy" and i < n - 14:
                plats[plat] = {"s": "maint", "ok": 0, "tot": 0,
                               "note": "渠道维护模式"}
            elif plat == "tongcheng" or roll < 0.90:
                plats[plat] = {"s": "ok", "ok": 3, "tot": 3, "note": ""}
            elif roll < 0.96:
                plats[plat] = {"s": "part", "ok": 2, "tot": 3,
                               "note": "部分日期查询失败（2/3 成功）"}
            else:
                plats[plat] = {"s": "fail", "ok": 0, "tot": 3,
                               "note": "达到最大重试圈数仍未拿到价格"}
        rounds.append({"ts": ts.strftime("%Y-%m-%d %H:%M"), "plats": plats})
    stats = {}
    for r in rounds:
        for plat, p in r["plats"].items():
            st = stats.setdefault(
                plat, {"ok": 0, "part": 0, "fail": 0, "maint": 0,
                       "rate": 0.0})
            st[p["s"]] += 1
    for plat, st in stats.items():
        att = st["ok"] + st["part"] + st["fail"]
        st["rate"] = (st["ok"] / att) if att else 0.0
    return {"rounds": rounds, "stats": stats}


def demo_pulse(seed=11):
    """合成扫描脉冲（与 core.pulse.Pulse.view 同形）：最近 40 轮
    每轮各渠道行数/耗时，供主页概览条与脉冲柱演示。"""
    rng = random.Random(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    chans = {"qunar": (70, 16), "fliggy": (24, 9),
             "tongcheng": (30, 12), "tuniu": (12, 7)}
    rounds = []
    for i in range(40):
        ts = now - timedelta(minutes=15 * (39 - i))
        cs = {}
        for plat, (base, spread) in chans.items():
            roll = rng.random()
            if roll < 0.94:
                rows = base + rng.randint(-spread // 2, spread)
            elif roll < 0.985:
                rows = max(1, base // 4)
            else:
                rows = 0
            cs[plat] = {"ok": rows > 0, "rows": rows,
                        "lat": round(6 + rng.random() * 14, 1)}
        rounds.append({"ts": ts.strftime("%Y-%m-%d %H:%M"),
                       "dur": round(sum(c["lat"] for c in cs.values()) / 3, 1),
                       "rows": sum(c["rows"] for c in cs.values()),
                       "fails": sum(1 for c in cs.values() if not c["ok"]),
                       "chans": cs})
    return {"ok": True, "rounds": rounds,
            "since": (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M")}
