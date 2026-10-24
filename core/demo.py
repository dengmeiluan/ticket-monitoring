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

from core.storage import SCHEMA, PriceStorage

_PLATS = ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"]


def _d(days):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def demo_routes():
    """演示航线定义（dict，webui 侧再转 Route 对象）。国内 3 + 国际 3
    （R49：东行/西行/远途西行三种时区形态，达标四档全档齐活——
    国际开关键零需要，intl 判定全由 core.intl 大陆码集单源派生）。"""
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
        {"from": "SHA", "from_name": "上海", "to": "NRT", "to_name": "东京成田",
         "dates": [_d(18)], "alert_direct": 1999, "alert_transfer": 1899,
         "transfer_arrival_max": "02:00", "dep_time_min": "", "dep_time_max": ""},
        {"from": "SHA", "from_name": "上海", "to": "BKK", "to_name": "曼谷",
         "dates": [_d(21)], "alert_direct": 1450, "alert_transfer": 1350,
         "transfer_arrival_max": "02:00", "dep_time_min": "", "dep_time_max": ""},
        {"from": "SHA", "from_name": "上海", "to": "LHR", "to_name": "伦敦希思罗",
         "dates": [_d(24)], "alert_direct": 6800, "alert_transfer": 6400,
         "transfer_arrival_max": "14:00", "dep_time_min": "", "dep_time_max": ""},
    ]


# ---- R49 国际演示样例（_scratch/intl/r49_promo.md 规格，可直接抄）----
# 每行都过两道既有守卫：flightnorm 时区校正（声明时长 vs 计算差
# ≤15 分不被覆写）+ alerter 补位自洽（dep+时长+Δtz≡arr 环形 ≤10 分）。
# crossDayDesc 一律空串——arrDate 由 normalize 推导，手填防打架。
_INTL_PLAN = {
    "NRT": dict(
        tz=(480, 540), tax=415,
        air=(("上海浦东", "T1", "PVG"), ("东京成田", "T1", "NRT")),
        hero=("东航", "MU523"),
        rows=[
            ("东航MU523", "MU523", "09:05", "13:15", 0, "3时10分", "", 0, ""),
            ("东航MU271", "MU271", "12:40", "16:45", 0, "3时05分", "", 0, ""),
            ("吉祥HO1355", "HO1355", "16:20", "20:25", 0, "3时05分", "", 0,
             "789"),
            ("春秋9C8515", "9C8515", "19:30", "23:55", 0, "3时25分", "", 0, ""),
            ("国泰CX363转", "CX363/CX509", "08:20", "19:10", 0, "9时50分",
             "香港", 145, ""),
        ]),
    "BKK": dict(
        tz=(480, 420), tax=265,
        air=(("上海浦东", "T2", "PVG"), ("曼谷素万那普", "T1", "BKK")),
        hero=("东航", "MU541"),
        rows=[
            ("东航MU541", "MU541", "09:55", "13:40", 0, "4时45分", "", 0, ""),
            ("春秋9C8577", "9C8577", "13:15", "17:00", 0, "4时45分", "", 0, ""),
            ("东航MU543", "MU543", "17:30", "21:15", 0, "4时45分", "", 0, ""),
            ("吉祥HO1357", "HO1357", "21:10", "01:35", 1, "5时25分", "", 0, ""),
            ("南航CZ3524转", "CZ3524/CZ3081", "07:55", "18:20", 0, "11时25分",
             "广州", 180, ""),
        ]),
    "LHR": dict(
        tz=(480, 0), tax=836,
        air=(("上海浦东", "T2", "PVG"), ("伦敦希思罗", "T3", "LHR")),
        hero=("东航", "MU551"),
        rows=[
            ("东航MU551", "MU551", "11:20", "16:40", 0, "13时20分", "", 0,
             "359"),
            ("东航MU553", "MU553", "13:45", "19:35", 0, "13时50分", "", 0, ""),
            ("英航BA168", "BA168", "23:50", "05:55", 1, "14时05分", "", 0, ""),
            ("阿联酋EK304转", "EK304/EK1", "23:00", "13:30", 1, "22时30分",
             "迪拜", 280, ""),
        ]),
}


def _stamp_intl_demo(fs, to_code):
    """国际演示行统一戳（镜像 crawlers/base._stamp_intl + tax/机场对
    附着）：webui「含税￥N」小字、时区校正时长真值、机场对三键、
    国际 23KG 托运口径单源。"""
    plan = _INTL_PLAN[to_code]
    dep_nm, dep_tm, dep_cd = plan["air"][0]
    arr_nm, arr_tm, arr_cd = plan["air"][1]
    for f in fs:
        f["intl"] = 1
        f["tax"] = plan["tax"]
        f["tz_dep"], f["tz_arr"] = plan["tz"]
        f["depAirport"], f["depTerminal"], f["depAirportCode"] = \
            dep_nm, dep_tm, dep_cd
        f["arrAirport"], f["arrTerminal"], f["arrAirportCode"] = \
            arr_nm, arr_tm, arr_cd
        f["cabin"] = "经济舱"
        f["meal"] = "有餐食"
        f["baggage"] = ("无免费托运" if f["code"].startswith("9C")
                        else "免费托运23KG")
    return fs


def _mk_intl_detail(rng, plat, dep_date, base_d, base_t, to_code):
    """国际航线一批明细（R49 专用池，不共用国内 airlines/slots）。"""
    plan = _INTL_PLAN[to_code]
    fs = []
    for (nm, code, dpt, art, plus, dur, trans, layover, plane) in plan["rows"]:
        if trans:
            price = base_t + rng.randint(-80, 120)
        else:
            price = base_d + rng.randint(-120, 160)
        fs.append(_flight(price, nm, code, dpt, art, dep_date,
                          days=plus, dur=dur, cabin="经济舱",
                          layover=layover, plane=plane, trans=trans))
    _stamp_intl_demo(fs, to_code)
    if plat in ("ctrip", "fliggy", "tongcheng"):
        # 日历薄行形态（r51 走查：demo 此前五渠道全富行，薄行在
        # --demo 全链零覆盖；生产日历兜底链同形——无航班号无时刻）
        thin = _flight(max(900, base_d - 60), "日历最低价", "", "", "",
                       dep_date)
        _stamp_intl_demo([thin], to_code)
        for k in ("cabin", "meal", "baggage", "totalDuration"):
            thin.pop(k, None)
        fs.append(thin)
    if plat == "qunar" and fs:
        # qunar 国际行真键：裸价/含税双口径（R40 census tax 拆分）
        fs[0]["nakedPrice"] = fs[0]["price"] - plan["tax"]
        fs[0]["prate"] = "87"
        fs[0]["planeSize"] = "中型机"
    return fs


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
    # 两条中转（一条达标约束内、一条超时）。code 恒「/」链形（与
    # 生产 qunar 中转行同形态：裸段码会撞跨源时刻仲裁的「无 / 直飞」
    # 代理门，被同码直飞整行改写起降——演示语料不养生产不可达形态）
    fs.append(_flight(base - 160, "南航CZ6976转", "CZ6976/ZH9876", "12:05", "23:50",
                      dep_date, days=0, trans="郑州", dur="11时45分",
                      cabin="经济舱", layover=175, plane="320",
                      svc="本服务包含中转行李免提、中转休息区、免费行李寄存等服务",
                      discount="4.2折"))
    fs.append(_flight(base - 200, "山航SC4664转", "SC4664/MU2201", "15:20", "05:40",
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
        # 舱别词面随源演示（bizCabin=公务：r256 cgrd 勘误后渠道词面
        # 值域单值「公务」，其余渠道缺省回退同词）——不可达形态不进
        # 演示面（旧「头等」演示值随勘误退役）
        fs[0]["bizCabin"] = "公务"
        fs[0]["cabinCode"] = "Y"
        fs[0]["labels"] = "机上Wi-Fi"
        # 渠道字段演示：年龄限制专享价（最低价政策 nt=20）——
        # 价格格 ⚠限青年价 徽标目检
        fs[0]["agePolicy"] = "限青年"
        # 渠道字段演示：高风险政策透明标记（ctrip nt=104 与最低价
        # 同价条目）——价格格 ⚠高风险政策 徽标目检
        fs[0]["riskPolicy"] = "高风险政策"
        # 退改费结构化双键演示（qunar 真采同协议）：首行双 0=「免费
        # 退改」徽标、fs[1] 有值=「退￥N·改￥0」形态，价格格徽标+
        # CSV「退改」列两处目检点
        fs[0]["returnFee"] = 0
        fs[0]["changeFee"] = 0
        if len(fs) > 1:
            fs[1]["returnFee"] = 366
            fs[1]["changeFee"] = 0
        # pid 数字托运额词面演示（ctrip 真采同协议，qunar/tongcheng
        # 同键 baggage）：正额=「免费托运20KG」、0=「无免费托运」双态，
        # title 悬停 + CSV「托运额」列目检点
        fs[0]["baggage"] = "免费托运20KG"
        if len(fs) > 1:
            fs[1]["baggage"] = "无免费托运"
        # pid 数字手提额词面演示（ctrip 孪生家族同门）：春秋型「无托运
        # 但有手提」在 fs[1] 成对目检
        fs[0]["carryon"] = "手提8KG·2件"
        if len(fs) > 1:
            fs[1]["carryon"] = "手提7KG·1件"
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
        # ieso 售罄词演示：真实形态挂非最低价的公务舱幸存行
        # （经济舱域售罄、公务有票参考价），labels 既有渲染通道
        if len(fs) > 1 and not fs[1].get("transCity"):
            fs[1]["cabin"] = "公务舱"
            fs[1]["labels"] = "经济舱售罄"
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
    # 演示库是临时文件、会被复用；快照不清会让每次启动叠加同刻重复行，
    # 走势的“较上次”被同刻副本覆盖成 0。
    conn.execute("DELETE FROM radar_snapshots")
    now = datetime.now().replace(second=0, microsecond=0)
    # ---- 14 天历史：每 30min 一轮（长坡缓降，末段刺破阈值；
    # 供 48h 走势图 / 7d 范围 / 14 天价格日历三个视图共用） ----
    curves = {
        0: dict(d0=2680, d1=1850, t0=2150, t1=1660),   # 直飞长坡刺破 1900 线
        1: dict(d0=2200, d1=1580, t0=1880, t1=1520),   # 直飞+中转双双破线
        2: dict(d0=2900, d1=2440, t0=2300, t1=1930),   # 全程未达标（超线档演示）
        # R49 国际三线：东京直飞长坡刺破 1999（🎯真达标·含税）/
        # 曼谷直飞终点距线 4.8%（🟨擦边档）/ 伦敦直飞超线+中转破线
        3: dict(d0=2680, d1=1850, t0=2420, t1=1830),
        4: dict(d0=2280, d1=1520, t0=2050, t1=1690),
        5: dict(d0=9200, d1=7650, t0=8300, t1=6150),
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
            if r["to"] in _INTL_PLAN:
                # R49 国际历史行：hero 直飞+中转同戳（走势点点击进明细
                # 与曲线最低行对得上；airline/flight_no 列同步 hero）
                plan = _INTL_PLAN[r["to"]]
                hd, htrans = plan["rows"][0], plan["rows"][-1]
                extra = [
                    _flight(dp, hd[0], hd[1], hd[2], hd[3], r["dates"][0],
                            days=hd[4], dur=hd[5]),
                    _flight(tp, htrans[0], htrans[1], htrans[2], htrans[3],
                            r["dates"][0], days=htrans[4], dur=htrans[5],
                            trans=htrans[6]),
                ]
                _stamp_intl_demo(extra, r["to"])
                conn.execute(
                    "INSERT INTO flight_prices (platform, from_city, to_city, "
                    "depart_date, price, airline, flight_no, fetched_at, "
                    "extra) VALUES (?,?,?,?,?,?,?,?,?)",
                    (_PLATS[(i + ri) % len(_PLATS)], r["from"], r["to"],
                     r["dates"][0], min(dp, tp), plan["hero"][0],
                     plan["hero"][1], ts_s,
                     json.dumps(extra, ensure_ascii=False)))
                continue
            extra = [
                _flight(dp, "东航MU8369", "MU8369",
                        "19:55" if not dep_min_only else "18:40",
                        "01:25" if not dep_min_only else "23:30",
                        r["dates"][0], days=0, cross=""),
                _flight(tp, "南航CZ6976转", "CZ6976/ZH9876", "12:05", "23:50",
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
            if r["to"] in _INTL_PLAN:
                # R49 国际专用池（不共用国内 airlines/slots——行头
                # 机场对错挂国内虹桥/天山即在此规避）
                fs = _mk_intl_detail(rng, plat, r["dates"][0],
                                     c["d1"] + base, c["t1"] + base,
                                     r["to"])
            else:
                fs = _mk_detail(rng, plat, r["dates"][0], c["d1"] + base,
                                dep_min_only=bool(r["dep_time_min"]),
                                route=r)
            if plat == "qunar":
                # 改期窗口挂当轮最低价行（与 qunar 爬虫同律，一行代表全轮）；
                # dep_min_only 航线按时段过滤后只剩晚段直飞——挂到被滤掉的
                # 行上等于白挂，故先按同谓词取可见集
                vis = [f for f in fs if not
                       (r["dep_time_min"] and f["depTime"] < r["dep_time_min"])]
                lo_f = min(vis, key=lambda f: f["price"])
                lo_f["trendGo"] = _trend_go(r["dates"][0], lo_f["price"])
                # 改期日历节假日标注合成（tongcheng trendHoliday 消费端
                # 目检样本：与 trendGo 同日期轴抽两点带词面）
                _tg_pts = lo_f["trendGo"]
                lo_f["trendHoliday"] = [
                    [_tg_pts[2][0], "会员日"],
                    [_tg_pts[9][0], "中秋节·休"],
                ]
                # 高档舱同点注合成（tongcheng trendBiz 目检样本：同轴
                # 抽两点 2~3 倍价带，柱 title「公务￥X」渲染可视）
                lo_f["trendBiz"] = [
                    [_tg_pts[2][0], round(_tg_pts[2][1] * 2.6)],
                    [_tg_pts[5][0], round(_tg_pts[5][1] * 2.1)],
                ]
            conn.execute(
                "INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, airline, flight_no, fetched_at, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (plat, r["from"], r["to"], r["dates"][0],
                 min(f["price"] for f in fs), "", "", ts_s,
                 json.dumps(fs, ensure_ascii=False)))
    # ---- 特价监控：3 次合成快照（公开演示明确标 DEMO，非真实报价） ----
    # 低价日落在 SHA→URC 首个演示日期，点开可读到上面当轮明细；
    # 逐日最低渠道轮换，覆盖三个官方日历来源。
    _r0 = routes[0]
    _rdays = [now.date() + timedelta(days=15 + i) for i in range(7)]
    _runs = [
        (now - timedelta(hours=4), [1860, 1720, 1790, 1750, 1830, 2010, 2160]),
        (now - timedelta(hours=2), [1830, 1680, 1750, 1710, 1790, 1980, 2130]),
        (now, [1800, 1640, 1710, 1670, 1750, 1950, 2100]),
    ]
    _rrows = []
    for _at, _prices in _runs:
        _atx = _at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        for _di, _day in enumerate(_rdays):
            _extra = (0, 35, 70) if _di % 3 == 0 else (
                (35, 0, 70) if _di % 3 == 1 else (70, 35, 0))
            for _ci, _ch in enumerate(("ctrip", "fliggy", "tongcheng")):
                _rrows.append((
                    "演示用户", _r0["from"], _r0["to"], 0,
                    _day.strftime("%Y-%m-%d"), _ch,
                    _prices[_di] + _extra[_ci], 0, "bare", "calendar", "",
                    _rdays[0].strftime("%Y-%m-%d"),
                    _rdays[-1].strftime("%Y-%m-%d"), _atx))
    conn.executemany(
        "INSERT INTO radar_snapshots (user,from_city,to_city,nationwide,"
        "depart_date,channel,price,tax_included,basis,kind,link,"
        "query_start,query_end,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", _rrows)
    conn.commit()
    conn.close()
    # ---- 半年走势日桶：派生自同一套明细（PriceStorage.refresh_daily
    # 与生产同函数同口径；demo 行直中混装形态按元素自动归桶），
    # 否则 /api/trend 长窗三档全空态（r323 P1-1） ----
    _dst = PriceStorage(path)
    for r in routes:
        # 15 天：明细跨度 13d23h30m 触达 14 个自然日（今天往前第 14 天
        # 有最老数小时的行），range(14) 只刷到 13 天前——最旧日行在
        # 桶不在，长窗首桶与「数据自 X 起」注同错一天
        for i in range(15):
            _dst.refresh_daily(r["from"], r["to"], r["dates"][0],
                               (now - timedelta(days=i)).strftime("%Y-%m-%d"))
    return path


def demo_health(hours=24, seed=7):
    """合成健康时间线（与 parse_health 输出同形）。"""
    rng = random.Random(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    rounds = []
    n = hours * 4                       # 15min 一轮
    # Ctrip 已接 PC 国际航班列表（v1.5.280）：演示健康也必须是航班级，
    # 否则公共演示仍宣称“携程日历价 3（无航班明细）”，与 README/
    # Release 的 174 行真实航班直接矛盾。
    cal_only = {"fliggy", "tongcheng"}

    def _cell(s, ok, tot, note="", cal=0, detail=0, auth=False):
        return {"s": s, "ok": ok, "tot": tot, "note": note,
                "cal": cal, "detail": detail, "need_login": auth}

    for i in range(n):
        ts = now - timedelta(minutes=15 * (n - 1 - i))
        plats = {}
        for plat in _PLATS:
            roll = rng.random()
            if plat == "fliggy" and i < n - 14:
                plats[plat] = _cell("maint", 0, 0, "渠道维护模式")
            elif plat == "tongcheng" or roll < 0.90:
                if plat in cal_only:
                    plats[plat] = _cell("ok", 3, 3,
                                        "日历价 3（无航班明细）", cal=3)
                else:
                    plats[plat] = _cell("ok", 3, 3, "", detail=3)
            elif roll < 0.96:
                if plat in cal_only:
                    plats[plat] = _cell("part", 2, 3,
                                        "部分日期查询失败（2/3 成功）",
                                        cal=2)
                else:
                    plats[plat] = _cell("part", 2, 3,
                                        "部分日期查询失败（2/3 成功）",
                                        detail=2)
            else:
                plats[plat] = _cell(
                    "fail", 0, 3, "需登录 · 会话失效" if plat == "qunar"
                    else "达到最大重试圈数仍未拿到价格",
                    auth=(plat == "qunar"))
        rounds.append({"ts": ts.strftime("%Y-%m-%d %H:%M"), "plats": plats})
    stats = {}
    for r in rounds:
        for plat, p in r["plats"].items():
            st = stats.setdefault(
                plat, {"ok": 0, "part": 0, "fail": 0, "maint": 0,
                       "rate": 0.0, "cal": 0, "detail": 0, "auth": 0})
            st[p["s"]] += 1
            st["cal"] += p.get("cal", 0)
            st["detail"] += p.get("detail", 0)
            st["auth"] += 1 if p.get("need_login") else 0
    for plat, st in stats.items():
        att = st["ok"] + st["part"] + st["fail"]
        st["rate"] = (st["ok"] / att) if att else 0.0
    # 合成推送通道（与 _push_channel_state 输出同形）：钉钉 -1 幽灵期
    # 连败 + 邮件全绿——健康页推送通道区的演示形态
    push = {"window_hours": hours, "channels": {
        "dingtalk": {"ok": 6, "fail": 12, "fail_streak": 4,
                     "last": (now - timedelta(minutes=22)).strftime(
                         "%m-%d %H:%M"),
                     "last_ok": (now - timedelta(hours=5)).strftime(
                         "%m-%d %H:%M")},
        "email": {"ok": 18, "fail": 0, "fail_streak": 0,
                  "last": (now - timedelta(minutes=22)).strftime(
                      "%m-%d %H:%M"),
                  "last_ok": (now - timedelta(minutes=22)).strftime(
                      "%m-%d %H:%M")}}}
    return {"rounds": rounds, "stats": stats, "push": push}


def demo_pulse(seed=11):
    """合成扫描脉冲（与 core.pulse.Pulse.view 同形）：最近 40 轮
    每轮各渠道行数/耗时，供主页概览条与脉冲柱演示。"""
    rng = random.Random(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    chans = {"qunar": (70, 16), "ctrip": (18, 8), "fliggy": (24, 9),
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
                       "dur": round(sum(c["lat"] for c in cs.values())
                                    / len(cs), 1),
                       "rows": sum(c["rows"] for c in cs.values()),
                       "fails": sum(1 for c in cs.values() if not c["ok"]),
                       "chans": cs})
    return {"ok": True, "rounds": rounds,
            "since": (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M")}
