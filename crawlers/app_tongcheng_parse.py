# -*- coding: utf-8 -*-
"""同程 App 纯解析：结果页 WebView 文本 / 原生表单 / 日历。

同程 App 的「机票查询」落 `WebViewActivity`；CLI uiautomator 因页面持续动画
会报 `could not get idle state`，但 uiautomator2 的 dump 能拿到完整文本
（2026-11-02 真机 SHA→PEK 7 行，含 MU5185 ¥373/¥336）。本模块只做纯函数，
输入是 u2 的 hierarchy XML。
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
FLIGHT_RE = re.compile(r"([A-Z0-9]{2}\d{3,4})(?![0-9])")
PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)")
MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月$")


def _root(xml: str):
    if not xml or "<hierarchy" not in xml:
        return None
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def nodes(xml: str):
    root = _root(xml)
    if root is None:
        return []
    out = []
    for n in root.iter("node"):
        t = (n.get("text") or n.get("content-desc") or "").strip()
        b = n.get("bounds") or ""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if not t or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        out.append({"text": t, "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return out


def _usable_airport(t: str) -> bool:
    """机场/航站楼文案：排除图标私用区、价格、时刻、服务说明。"""
    if not t or any(0xE000 <= ord(ch) <= 0xF8FF for ch in t):
        return False
    if PRICE_RE.search(t) or TIME_RE.match(t) or len(t) > 10:
        return False
    return bool(re.search(r"T\d", t)) or bool(
        re.fullmatch(r"[一-鿿]{2,6}", t))


def parse_form(xml: str):
    """原生表单的 (出发, 到达, 日期文案)；不是表单返回 None。"""
    ns = nodes(xml)
    if not any(n["text"] == "机票查询" for n in ns):
        return None
    # 城市位在表单 y=418（往返档）/466（单程档），左右两列；排除档位 tab。
    cities = [n for n in ns
              if 380 <= n["cy"] <= 520 and n["text"]
              and not re.search(r"\d", n["text"])
              and n["text"] not in ("国内", "国际", "往返", "多程")]
    dep = arr = ""
    if cities:
        left = [n for n in cities if n["cx"] < 450]
        right = [n for n in cities if n["cx"] >= 450]
        if left:
            dep = min(left, key=lambda n: abs(n["cy"] - 466))["text"]
        if right:
            arr = min(right, key=lambda n: abs(n["cy"] - 466))["text"]
    date = ""
    for n in ns:
        if n["cy"] < 700 and re.search(r"\d+月\d+日", n["text"]):
            date = re.split(r"[\n ]+", n["text"])[0]
            break
    if not (dep or arr or date):
        return None
    return {"dep": dep, "arr": arr, "date": date}


def is_form(xml: str) -> bool:
    return parse_form(xml) is not None


def is_calendar(xml: str) -> bool:
    """国内日历有「仅看直飞」开关；国际日历没有，但有「价格走势」。"""
    s = xml or ""
    return "价格日历" in s and ("仅看直飞" in s or "价格走势" in s)


def is_result(xml: str) -> bool:
    return bool(parse_result_rows(xml))


def is_login_wall(xml: str) -> bool:
    s = xml or ""
    return any(k in s for k in ("手机号一键登录", "微信登录", "其他登录方式",
                                "请输入手机号", "获取验证码"))


def parse_calendar_days(xml: str, year: int, month: int, today=None):
    """目标月份的逐日价 {day: price}；今天/明天/后天按 today 映射。

    日历一次渲染 2–3 个月，**必须**按 `YYYY年M月` 标题带切分：旧实现
    忽略 year/month、把整页同号日格混进一个 dict，12 月会覆盖 11 月
    （2026-11-02 实测两月输出完全相同）。
    """
    from datetime import timedelta
    ns = nodes(xml)
    heads = []
    for n in ns:
        m = MONTH_RE.match(n["text"])
        if m:
            heads.append((int(m.group(1)), int(m.group(2)), n["cy"]))
    heads.sort(key=lambda x: x[2])
    band = None
    for i, (y, mo, cy) in enumerate(heads):
        if (y, mo) == (year, month):
            hi = heads[i + 1][2] if i + 1 < len(heads) else 10 ** 9
            band = (cy, hi)
            break
    if band is None:
        return {}
    labels = {}
    if today is not None:
        for i, word in enumerate(("今天", "明天", "后天")):
            d = today + timedelta(days=i)
            if (d.year, d.month) == (year, month):
                labels[word] = d.day
    out = {}
    for n in ns:
        if not (band[0] < n["cy"] < band[1]):
            continue
        t = n["text"]
        m = PRICE_RE.search(t)
        if not m:
            continue
        day = next((v for k, v in labels.items() if t.startswith(k)), None)
        if day is None:
            parts = [p.strip() for p in re.split(r"[\n ]+", t) if p.strip()]
            nums = [int(p) for p in parts if p.isdigit()]
            if nums and 1 <= nums[0] <= 31:
                day = nums[0]
        if day:
            out[day] = float(m.group(1))
    return out


def parse_round_trip_form(xml: str):
    """往返表单的 (出发, 到达, 去程日期, 返程日期)；不是表单返回 None。

    与 `parse_form` 分开：往返档的城市行在 y=418（单程在 466），且有两个
    日期位；空返程位文案是「返程日期」而不是日期。
    """
    ns = nodes(xml)
    if not any(n["text"] == "机票查询" for n in ns):
        return None
    cities = [n for n in ns
              if 380 <= n["cy"] <= 520 and n["text"]
              and not re.search(r"\d", n["text"])
              and n["text"] not in ("国内", "国际", "往返", "多程")]
    dep = arr = ""
    left = [n for n in cities if n["cx"] < 450]
    right = [n for n in cities if n["cx"] >= 450]
    if left:
        dep = min(left, key=lambda n: abs(n["cy"] - 440))["text"]
    if right:
        arr = min(right, key=lambda n: abs(n["cy"] - 440))["text"]
    dep_date = ret_date = ""
    for n in ns:
        if n["cy"] >= 1000 or "月" not in n["text"]:
            continue
        m = re.search(r"(\d+月\d+日)", n["text"])
        if not m:
            continue
        if n["cx"] < 450 and not dep_date:
            dep_date = m.group(1)
        elif n["cx"] >= 450 and not ret_date:
            ret_date = m.group(1)
    if not (dep or arr or dep_date):
        return None
    return {"dep": dep, "arr": arr, "dep_date": dep_date,
            "ret_date": ret_date, "round_trip": bool(dep_date and ret_date)}


def is_round_trip_form(xml: str) -> bool:
    f = parse_round_trip_form(xml)
    return bool(f and f.get("round_trip"))


def _rt_date_badge(ns, split, left):
    """结果页顶部选中的 `11-16 周一` 徽标 → (月, 日)。"""
    for n in ns:
        if not (260 <= n["cy"] <= 320):
            continue
        m = re.match(r"^(\d{1,2})-(\d{1,2})\s*周[一二三四五六日]$",
                     n["text"])
        if not m:
            continue
        if left and n["cx"] < split:
            return m.group(1), m.group(2)
        if not left and n["cx"] >= split:
            return m.group(1), m.group(2)
    return "", ""


def _rt_split_flight(text: str):
    """`春秋航空9C85152时55分` → (9C8515, 春秋航空, 2时55分)。

    页面把时长直接粘在航班号后面，正则从中间起匹配会切出
    `C85152` 这类假航班号（实测）；按「尾部以时开头就把航号末位
    数字让给时长」切分：GK0363时→GK036+3时、MM8762时30分→MM876+2时30分。
    """
    m = re.match(r"^([一-鿿]*?)\s*([A-Z0-9]{2})(\d{3,4})(.*)$", text)
    if not m:
        return "", "", ""
    airline, prefix, digits, tail = m.groups()
    if len(digits) == 4 and not re.match(r"^\d+时", tail) \
            and tail.startswith("时"):
        digits, tail = digits[:3], digits[3:] + tail
    dm = re.match(r"^(\d+时(?:\d+分)?)", tail)
    return prefix + digits, airline.strip(), (dm.group(1) if dm else "")


def _rt_flight_line(ns, cy_lo, cy_hi, x_lo, x_hi, dur_ns):
    """航班行：航班号/航司/时长；时长可能在同行第二个节点。"""
    best = None
    for n in ns:
        if not (cy_lo <= n["cy"] <= cy_hi and x_lo <= n["x1"] <= x_hi):
            continue
        if not FLIGHT_RE.search(n["text"]):
            continue
        if best is None or n["cy"] < best[0]:
            best = (n["cy"], n)
    if best is None:
        return "", "", ""
    _, n = best
    flight_no, airline, dur = _rt_split_flight(n["text"])
    if not dur:
        near = [x for x in dur_ns if abs(x["cy"] - n["cy"]) <= 12]
        if near:
            dur = near[0]["text"].strip()
    return flight_no, airline, dur


def parse_round_trip(xml: str):
    """同程 App 往返结果页 → 去程行 + 返程加价 + 已选组合总价。

    页面是两栏并排：左栏去程行给「含税总价」（与该栏当前选中的返程
    组合后的**往返总价**），右栏返程行只给相对已选去程的 `+¥N` 加价；
    底部「已选 X 出发 Y · ¥Z」才是整单总价。不把 `+¥N` 当票价。
    """
    ns = nodes(xml)
    s = xml or ""
    if "含税总价" not in s or "已选" not in s:
        return None
    dep_hdr = [n for n in ns if n["text"] == "去程"
               and n["cy"] < 260 and n["x1"] < 450]
    ret_hdr = [n for n in ns if n["text"] == "返程"
               and n["cy"] < 260 and n["x1"] > 450]
    if not dep_hdr or not ret_hdr:
        return None
    split = (max(n["x2"] for n in dep_hdr)
             + min(n["x1"] for n in ret_hdr)) // 2
    route = ""
    for n in ns:
        if "⇌" in n["text"] or "⇄" in n["text"]:
            route = n["text"]
            break
    dep_m, dep_d = _rt_date_badge(ns, split, left=True)
    ret_m, ret_d = _rt_date_badge(ns, split, left=False)
    dur_ns = [n for n in ns if re.fullmatch(r"\d+时(?:\d+分)?",
                                            n["text"])]
    note = next((n["text"] for n in ns if "往返价格已降" in n["text"]), "")

    outbounds = []
    for dep in ns:
        if not (TIME_RE.match(dep["text"]) and dep["cy"] > 360
                and dep["x2"] - dep["x1"] >= 80
                and dep["x2"] < split - 400):
            continue
        arrs = [n for n in ns if TIME_RE.match(n["text"])
                and abs(n["cy"] - dep["cy"]) <= 8
                and split - 500 < n["x1"] and n["x2"] < split - 250]
        if not arrs:
            continue
        arr = min(arrs, key=lambda n: n["x1"])
        near = [n for n in ns if dep["cy"] + 10 <= n["cy"] <= dep["cy"] + 55
                and _usable_airport(n["text"])]
        dep_air = min((n for n in near if n["x2"] < 160),
                      key=lambda n: n["cx"], default={"text": ""})["text"]
        arr_air = min((n for n in near if 160 <= n["x1"] < 340),
                      key=lambda n: n["cx"], default={"text": ""})["text"]
        prices = [n for n in ns if "¥" in n["text"]
                  and abs(n["cy"] - dep["cy"]) <= 8
                  and 430 <= n["x1"] and n["x2"] < split]
        if not prices:
            continue
        pm = PRICE_RE.search(prices[0]["text"])
        if not pm:
            continue
        price = float(pm.group(1))
        arr_day = next((n["text"] for n in ns
                        if re.fullmatch(r"\d+月\d+日", n["text"])
                        and dep["cy"] - 35 <= n["cy"] <= dep["cy"] - 10
                        and 160 <= n["x1"] < 340), "")
        flight_no, airline, dur = _rt_flight_line(
            ns, dep["cy"] + 45, dep["cy"] + 120, 0, split, dur_ns)
        if not flight_no:
            continue
        seats = next((n["text"] for n in ns
                      if re.fullmatch(r"余\s*\d+\s*张|余票少", n["text"])
                      and abs(n["cy"] - dep["cy"]) <= 30), "")
        outbounds.append({
            "flight_no": flight_no, "airline": airline,
            "dep_time": dep["text"], "arr_time": arr["text"],
            "arr_date": arr_day, "dep_airport": dep_air,
            "arr_airport": arr_air, "duration": dur,
            "price": price, "seats": seats})
    if not outbounds:
        return None

    returns = []
    seen_ret = set()
    for dep in ns:
        if not (TIME_RE.match(dep["text"]) and dep["cy"] > 360
                and dep["x2"] - dep["x1"] >= 80
                and dep["x1"] >= split + 10 and dep["x2"] <= split + 130):
            continue
        arrs = [n for n in ns if TIME_RE.match(n["text"])
                and abs(n["cy"] - dep["cy"]) <= 8 and n["x1"] >= split + 190]
        if not arrs:
            continue
        arr = max(arrs, key=lambda n: n["x1"])
        near = [n for n in ns if dep["cy"] + 10 <= n["cy"] <= dep["cy"] + 55
                and _usable_airport(n["text"])]
        dep_air = min((n for n in near if n["x1"] >= split + 10
                       and n["x2"] <= split + 140),
                      key=lambda n: n["cx"], default={"text": ""})["text"]
        arr_air = max((n for n in near if n["x1"] >= split + 180),
                      key=lambda n: n["cx"], default={"text": ""})["text"]
        sur = next((n for n in ns if n["text"].startswith("+")
                    and "¥" in n["text"]
                    and dep["cy"] + 45 <= n["cy"] <= dep["cy"] + 110
                    and n["x1"] >= split + 150), None)
        if sur is None:
            continue
        sm = re.search(r"(\d+(?:\.\d+)?)", sur["text"])
        if not sm:
            continue
        flight_no, airline, dur = _rt_flight_line(
            ns, dep["cy"] + 45, dep["cy"] + 120, split + 10, 10 ** 9,
            dur_ns)
        if not flight_no:
            continue
        returns.append({
            "flight_no": flight_no, "airline": airline,
            "dep_time": dep["text"], "arr_time": arr["text"],
            "dep_airport": dep_air, "arr_airport": arr_air,
            "duration": dur, "surcharge": float(sm.group(1))})
    # 同一行在 WebView 里会出现两份（主行 + 紧凑行），按航班号+时刻去重。
    uniq = {}
    for r in returns:
        uniq.setdefault((r["flight_no"], r["dep_time"], r["arr_time"]), r)
    returns = list(uniq.values())

    # 页脚措辞两种：`已选 21:10 出发 春秋航空` / `已选 02:20- 06:20 捷星航空`
    # （有时间区间时不写「出发」）；两种都要认。
    sel = next((n for n in ns if n["text"].startswith("已选")
                and n["cy"] > 1200), None)
    total = None
    if sel is not None:
        for n in ns:
            if not (n["text"].startswith("¥")
                    and abs(n["cy"] - sel["cy"]) <= 25
                    and n["x1"] > 400
                    and n["y1"] >= sel["y1"] - 2):
                continue
            tm = PRICE_RE.search(n["text"])
            if tm:
                total = float(tm.group(1))
                break
    if total is None:
        return None
    selected = next((r for r in returns if r["surcharge"] == 0), None)
    dep_name = arr_name = ""
    if "⇌" in route:
        dep_name, arr_name = [x.strip() for x in route.split("⇌")[:2]]
    elif "⇄" in route:
        dep_name, arr_name = [x.strip() for x in route.split("⇄")[:2]]
    return {
        "route": {"dep": dep_name, "arr": arr_name},
        "dep_date": ("%s-%s" % (dep_m, dep_d)) if dep_m else "",
        "ret_date": ("%s-%s" % (ret_m, ret_d)) if ret_m else "",
        "total": total,
        "outbounds": sorted(outbounds, key=lambda r: (r["dep_time"],
                                                      r["price"])),
        "returns": sorted(returns, key=lambda r: (r["surcharge"],
                                                  r["dep_time"])),
        "selected_return": selected,
        "note": note,
    }


def parse_result_rows(xml: str):
    """WebView 结果页 → 航班行。

    价格串实测 `¥373¥336`：第一个是列表价，第二个是券后/会员价；
    主 price 取券后价，extra 里同时保留列表价与优惠说明。
    """
    ns = nodes(xml)
    deps = [n for n in ns if TIME_RE.match(n["text"]) and n["cx"] < 220]
    by_key = {}
    for dep in deps:
        arrs = [n for n in ns if TIME_RE.match(n["text"])
                and abs(n["cy"] - dep["cy"]) <= 6 and n["cx"] > dep["cx"]]
        if not arrs:
            continue
        arr = min(arrs, key=lambda n: n["cx"])
        near = [n for n in ns
                if dep["cy"] + 10 <= n["cy"] <= dep["cy"] + 50]
        airports = [n for n in near if _usable_airport(n["text"])
                    and n["x1"] < 600]
        dep_air = min(airports, key=lambda n: n["cx"])["text"] \
            if airports else ""
        arr_air = max(airports, key=lambda n: n["cx"])["text"] \
            if airports else ""
        prices = [n for n in ns if "¥" in n["text"]
                  and "可优惠约" not in n["text"]
                  and "省" not in n["text"]
                  and "券" not in n["text"]
                  and abs(n["cy"] - dep["cy"]) <= 35 and n["cx"] > 600]
        if not prices:
            continue
        # 国际/新版卡把「划线列表价」和「实付价」拆成两个节点（¥902 / ¥875），
        # 国内旧卡是同一节点 `¥373¥336`。统一收全本行价格，实付取最低、
        # 列表价取最高；已省/券类金额不是票价，已在过滤里排除。
        vals = []
        for n in prices:
            vals += [float(x) for x in
                     re.findall(r"\d+(?:\.\d+)?", n["text"])]
        vals = [v for v in vals if v >= 50]
        if not vals:
            continue
        pay = min(vals)
        listed = max(vals)
        discount = ""
        for n in ns:
            if ("可优惠约" in n["text"] or "已省" in n["text"]
                    or "优惠" in n["text"]) and abs(n["cy"] - dep["cy"]) <= 45:
                discount = n["text"]
                break
        flight_no = airline = cabin = aircraft = ""
        for n in ns:
            if not (dep["cy"] + 35 <= n["cy"] <= dep["cy"] + 120):
                continue
            m = FLIGHT_RE.search(n["text"])
            if m and not flight_no:
                flight_no = m.group(1)
                airline = n["text"].split(m.group(1))[0].strip()
            if "经济舱" in n["text"] and not cabin:
                cabin = n["text"]
            if ("空客" in n["text"] or "波音" in n["text"]
                    or "机型" in n["text"]) and not aircraft:
                aircraft = n["text"]
        if not flight_no:
            continue
        rec = {"flight_no": flight_no, "dep_time": dep["text"],
               "arr_time": arr["text"], "dep_airport": dep_air,
               "arr_airport": arr_air, "airline": airline,
               "cabin": cabin, "aircraft": aircraft,
               "price": float(pay), "list_price": float(listed),
               "discount_note": discount}
        key = (flight_no, rec["dep_time"], rec["arr_time"])
        old = by_key.get(key)
        if old is None or rec["price"] < old["price"]:
            by_key[key] = rec
    return sorted(by_key.values(),
                  key=lambda r: (r["dep_time"], r["price"]))
