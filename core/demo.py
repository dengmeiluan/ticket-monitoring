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
         "transfer_arrival_max": "02:00", "transfer_layover_min": 90,
         "transfer_baggage": "direct", "dep_time_min": "", "dep_time_max": ""},
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
            cross="", dur="", cabin="", layover="", plane="", discount="",
            svc=""):
    d0 = datetime.strptime(dep_date, "%Y-%m-%d").date()
    return {"price": price, "name": name, "code": code, "depTime": dpt,
            "arrTime": art, "depDate": dep_date,
            "arrDate": (d0 + timedelta(days=days)).strftime("%Y-%m-%d"),
            "transCity": trans, "crossDayDesc": cross,
            "totalDuration": dur or "5时25分",
            "cabin": cabin, "layover": layover, "plane": plane,
            "discount": discount, "transitServiceLabel": svc}


def _mk_detail(rng, plat, dep_date, base, dep_min_only=False, route=None):
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
        # 桶位偏移用枚举序号而非 hash(plat)：Python 字符串 hash 每进程
        # 随机化（无 PYTHONHASHSEED），docstring「确定性种子，截图可
        # 复现」曾不成立——同一份演示数据每次进程时段分布不同
        dpt, art, plus = slots[(i + _PLATS.index(plat) % 3) % len(slots)]
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
                      svc="本服务包含中转行李免提、中转休息区、免费行李寄存等服务",
                      discount="4.2折"))
    fs.append(_flight(base - 200, "山航SC4664转", "SC4664", "15:20", "05:40",
                      dep_date, days=1, trans="青岛", cross="+1天",
                      dur="14时20分", cabin="经济舱", layover=310,
                      plane="738", discount="3.8折"))
    # 新决策字段演示（渠道字段四批）：fliggy 余票紧张、ctrip
    # 最低价政策余票数、到达航站楼、中转航站楼——UI 次行段/CSV 可视
    if plat == "fliggy" and len(fs) > 1:
        fs[1]["fewTicket"] = "少量"
        fs[1]["arrTerminal"] = "T2"
    if plat == "ctrip" and fs:
        fs[0]["leftTickets"] = 3
        fs[0]["arrTerminal"] = "T1"
        # 渠道字段七批演示：廊桥率/取消率/公务舱价/舱位码（挂
        # fs[0] 首行演示 hover 与 CSV 新列；bizPrice 行价+840 呈升舱差
        # 主口径）。词面挂载点：取消率并准点段、廊桥/机龄并机型段——
        # 载体字段 prate/planeSize/planeAge 必须同时在，否则词面无挂载
        # 点整段消失（首轮截图目检实锤）。lcc 不合成——normalize 由
        # 航司池「春秋9C」行派生出镜
        fs[0]["bridgeRate"] = 92
        fs[0]["cancelRate"] = 3
        fs[0]["bizPrice"] = base + 840
        # 舱别词面随源演示（bizCabin 头等形态；其余渠道缺省回退
        # 「公务」同存量行）
        fs[0]["bizCabin"] = "头等"
        fs[0]["cabinCode"] = "Y"
        fs[0]["labels"] = "机上Wi-Fi"
        # 渠道字段演示：年龄限制专享价（最低价政策 nt=20）——
        # 价格格 ⚠限青年价 徽标目检
        fs[0]["agePolicy"] = "限青年"
        # 退改费结构化双键演示（qunar 真采同协议）：首行双 0=「免费
        # 退改」徽标、fs[1] 有值=「退￥N·改￥0」形态，价格格徽标+
        # CSV「退改」列两处目检点
        fs[0]["returnFee"] = 0
        fs[0]["changeFee"] = 0
        if len(fs) > 1:
            fs[1]["returnFee"] = 366
            fs[1]["changeFee"] = 0
    # 渠道字段十一批演示：机场 IATA 码（H1 三源真采，demo 按
    # 航线方向统一挂中文名+码，供 webui 白名单透传/渲染门目检）
    if route:
        dep_nm, dep_cd = (("乌鲁木齐天山", "URC") if route["from"] == "URC"
                          else ("上海虹桥", "SHA"))
        arr_nm, arr_cd = (("上海虹桥", "SHA") if route["from"] == "URC"
                          else ("乌鲁木齐天山", "URC"))
        for f in fs:
            f["depAirport"], f["depAirportCode"] = dep_nm, dep_cd
            f["arrAirport"], f["arrAirportCode"] = arr_nm, arr_cd
        fs[0]["prate"] = "87"
        fs[0]["planeSize"] = "中型机"
        fs[0]["planeAge"] = "6.3"
    if plat == "qunar" and fs:
        fs[0]["arrTerminal"] = "T2"
        # 渠道字段九批演示：labelNote 标签适用条件随 labels
        # 配对（生产端唯一源=qunar PC priceLabel[].note；渲染=labels
        # title「｜」拼接通道，CSV「标签说明」列 32 列）
        fs[0]["labels"] = "机上Wi-Fi"
        fs[0]["labelNote"] = "享受退改保护，如不可抗力可免费办理另一程改签或退票"
    if plat == "tongcheng" and fs:
        # 九批演示：leftTickets 余票紧张（与 ctrip 同键同位，
        # 次行「余N张」红字语境；1-9 值域守卫与爬虫一致）
        fs[0]["leftTickets"] = 2
        # 同程/途牛 bizPrice 接入（三渠道同键同协议，
        # 「公务￥N」通道现成零前端改动）
        fs[0]["bizPrice"] = base + 840
    if plat == "tuniu" and fs:
        fs[0]["bizPrice"] = base + 840
    if plat == "fliggy" and fs:
        # 渠道字段八批演示：中转行机建燃油（「+机建燃油￥240」
        # 词面，载体=中转行 transTerminal 段同行渲染）+ meal 双态
        # 标签（meal 段载体，与爬虫「出现即真」口径一致，has-food-
        # label 正负两态都有生产实发，演示面双态对齐）
        for f in fs:
            if f.get("transCity"):
                f["transferTax"] = 240
                # 调研 R4 演示：中转说明图例 → transferBaggage=
                # 'recheck'（明细「需转运」stoptag 渲染门，ctrip 同键
                # 同语义位五渠道协议补全）
                f["transferBaggage"] = "recheck"
        if fs[0].get("transCity"):
            fs[1]["meal"] = "无餐食"
            fs[0]["meal"] = "有餐食"
        else:
            fs[0]["meal"] = "无餐食"
            if len(fs) > 1:
                fs[1]["meal"] = "有餐食"
    if plat == "tuniu" and fs:
        fs[0]["cabinCode"] = "D"   # tuniu 生产端已产舱位码，演示同形
    for f in fs:
        if f.get("transCity"):
            f["transTerminal"] = ("新郑T2" if f["transCity"] == "郑州"
                                  else "胶东T1")
            # 九批演示：中转服务权益（qunar PC transitServiceLabel
            # 文本本体与 tongcheng stss 同键 transferService；渲染=中转
            # tag title 既有位，直挂键——svc= 的 transitServiceLabel 只
            # 喂 normalize transferBaggage 推断不产本键。半角冒号与
            # 爬虫 f"{Name}:{Label}" 协议同形）
            if plat in ("qunar", "tongcheng"):
                # 串尾分隔与爬虫 svc_txt="/".join(...) 同形（半角斜杠）
                f["transferService"] = (
                    "中转优享:本服务包含免二次安检、免费餐食、免费行李寄存服务"
                    + ("/航班延误取消，免费退改" if plat == "tongcheng"
                       else ""))
                # 调研 R3 演示：doc.book1「延误取消免费退改」页
                # 面级图例并入串尾（白名单词面与爬虫产出同形）
                # 十三批演示：行级直挂证据（stss ServiceType=
                # LUGGAGE「行李直达」白名单词与 transferBaggage='direct'
                # 配对，词随串同形入串；qunar 行级无此证据不合成）
                if plat == "tongcheng":
                    f["transferService"] += "/行李直达"
                    f["transferBaggage"] = "direct"
    return fs


def _trend_go(dep_date, price):
    """qunar H5 改期窗口合成（与爬虫 _parse_trend_go 同构）：出发日期
    ±7 天 15 点 [[MM-DD,int],…]，中心=行 depDate；最低点放 +2 天、
    较行价低 ~15%，抛物线过渡无 rng——uitest 胶囊断言可复现。"""
    d0 = datetime.strptime(dep_date, "%Y-%m-%d").date()
    lo = max(100, round(price * 0.85))
    return [[(d0 + timedelta(days=off)).strftime("%m-%d"),
             lo if off == 2 else
             int(lo + (price * 1.06 - lo) * ((off - 2) / 9.0) ** 2)]
            for off in range(-7, 8)]


def build_demo_db(path, seed=20260909):
    """生成演示库：48h 历史 + 当轮明细（确定性种子，截图可复现）。"""
    rng = random.Random(seed)
    routes = demo_routes()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM flight_prices")
    now = datetime.now().replace(second=0, microsecond=0)
    # ---- 14 天历史：每 30min 一轮（长坡缓降，末段刺破阈值；
    # 供 48h 走势图 / 7d 范围 / 14 天价格日历三个视图共用） ----
    curves = {
        0: dict(d0=2680, d1=1850, t0=2150, t1=1660),   # 直飞长坡刺破 1900 线
        1: dict(d0=2200, d1=1580, t0=1880, t1=1520),   # 直飞+中转双双破线
        2: dict(d0=2900, d1=2440, t0=2300, t1=1930),   # 全程未达标（超线档演示）
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
                        r["dates"][0], days=0, cross=""),
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
                            dep_min_only=bool(r["dep_time_min"]), route=r)
            if plat == "qunar":
                # 改期窗口挂当轮最低价行（与 qunar 爬虫同律，一行代表全轮）；
                # dep_min_only 航线按时段过滤后只剩晚段直飞——挂到被滤掉的
                # 行上等于白挂，故先按同谓词取可见集
                vis = [f for f in fs if not
                       (r["dep_time_min"] and f["depTime"] < r["dep_time_min"])]
                lo_f = min(vis, key=lambda f: f["price"])
                lo_f["trendGo"] = _trend_go(r["dates"][0], lo_f["price"])
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
