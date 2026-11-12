# -*- coding: utf-8 -*-
"""飞猪 App 结果页解析（Windows OCR 词块，纯函数，可离线测）。

飞猪 App 的航班页是 Flutter 画布：`uiautomator`/u2 只能拿到系统状态栏，
拿不到航班文本。2026-11-02 真机（900×1600 竖屏）验证 Windows 自带
zh-Hans-CN OCR 能稳定读出结果页的支付价、时刻、航班号与机场。

输入是 OCR 的**词块**列表（含 x/y/w/h），不是整行文本——OCR 会把左右
两列拼进同一行，按 y 分带、按 x 分列才可靠。行锚点取左列的出发时刻
（大字号两位数字），同一行内再取到达时刻、右侧支付价、机场、航班号。

价格口径：取右侧最大字号、最靠右的 3 位数字为**页面支付价**；左侧
小字号划线价单独保留为 `list_price`。App 未标注是否含税，不冒充含税。
"""
from __future__ import annotations

import re
from datetime import date as _date
from typing import Iterable, List

_PRICE_RE = re.compile(r"^\d{3}$")
_TWO_DIGIT = re.compile(r"^\d{2}$")
_FLIGHT_NO = re.compile(r"^([A-Z0-9]{2})(\d{3,4})$")
_TAGS = ("历史低价", "可能涨价", "限特定乘客", "少量")


def _words(items: Iterable[dict]) -> List[dict]:
    out = []
    for w in items or []:
        t = str(w.get("t") or w.get("text") or "").replace(" ", "")
        if not t:
            continue
        try:
            x, y = int(w["x"]), int(w["y"])
            ww, hh = int(w["w"]), int(w["h"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"t": t, "x": x, "y": y, "w": ww, "h": hh})
    return out


def _near(words, y, tol=10, x0=0, x1=10 ** 9):
    return sorted([w for w in words
                   if abs(w["y"] - y) <= tol and x0 <= w["x"] < x1],
                  key=lambda w: w["x"])


def _join(words):
    return "".join(w["t"] for w in words)


def _time_at(words, y, x0, x1):
    """同一行里按 x 取时刻：两个两位数字 + 中间冒号。"""
    cells = _near(words, y, tol=12, x0=x0, x1=x1)
    digits = [w["t"] for w in cells if _TWO_DIGIT.match(w["t"])
              and w["h"] >= 24]
    if len(digits) >= 2:
        return "%s:%s" % (digits[0], digits[1])
    return ""


def _fix_flight_no(raw: str) -> str:
    """OCR 把航班号里的字母 O 读成 0（实测 H01017=HO1017）。"""
    m = _FLIGHT_NO.match(raw or "")
    if not m:
        return ""
    pre, num = m.group(1), m.group(2)
    if "0" in pre:
        pre = pre.replace("0", "O")
    return pre + num


def _flight_no(words, y):
    for w in sorted(words, key=lambda w: w["x"]):
        if abs(w["y"] - y) <= 26 and w["x"] < 360:
            f = _fix_flight_no(w["t"])
            if f:
                return f, w
    return "", None


def _airline(words, y, fno_word):
    if fno_word is None:
        return ""
    left = _join([w for w in _near(words, fno_word["y"], tol=8, x0=0,
                                   x1=fno_word["x"])])
    m = re.search(r"([\u4e00-\u9fa5]{2,4})$", left)
    return m.group(1) if m else ""


def _airport(txt):
    """去掉经停/时长等混入词，只留机场+航站楼。"""
    txt = re.split(r"(?:经停|停\d|停\s*\d|经)", txt or "")[0]
    txt = txt.replace("TI", "T1").replace("Tl", "T1")
    return txt[:8]


def _center(box):
    return (box["x"] + box["w"] // 2, box["y"] + box["h"] // 2)


def _lines(words):
    """按 y + 水平间距把词块并成视觉行（「上海」「昆明」同一 y 也要分开）。"""
    lines = []
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        target = None
        for ln in lines:
            if (abs(w["y"] - ln["y"]) <= 12
                    and w["x"] <= ln["x2"] + 60):
                target = ln
                break
        if target is None:
            lines.append({"y": w["y"], "x2": w["x"] + w["w"],
                          "y2": w["y"] + w["h"], "parts": [w]})
            continue
        target["parts"].append(w)
        target["x2"] = max(target["x2"], w["x"] + w["w"])
        target["y2"] = max(target["y2"], w["y"] + w["h"])
    for ln in lines:
        parts = sorted(ln["parts"], key=lambda w: w["x"])
        ln["text"] = "".join(p["t"] for p in parts)
        ln["x"] = parts[0]["x"]
        ln["w"] = ln["x2"] - ln["x"]
        ln["h"] = ln["y2"] - ln["y"]
    return lines


def pick_best(rows):
    """渠道最低价：优先可公开购买的班次。

    「限特定乘客」（学生/长者等）仍保留在明细里，但不能当普通最低价；
    若整页只有受限价，才退回它并保留标签，不静默隐瞒。
    """
    if not rows:
        return None
    general = [r for r in rows
               if "限特定乘客" not in (r.get("tags") or [])]
    return min(general or rows, key=lambda r: r["price"])


# 表单页「城市行 / 日期行」的 y 区间：**按屏幕尺寸实测标定**。
#
# 为什么不能等比缩放（2026-11-05 实测）：900×1600 下城市行在 560..700，
# 按 h 比例（×1.75）应落在 980..1225；但 1260×2800 上真实城市行在
# **y≈853**（上海 x=94/168、北京 x=1023/1099）。等比缩放把窗口整体推低，
# 结果一个城市都框不到（`dep='' arr=''`），而窗口里反而剩档位 tab ——
# 这条既造成"把 tab 当城市"，也造成"到不了表单"的误判。
#
# 所以改成查表：已知屏幕用实测值，未知屏幕退回 900 基准的比例缩放。
_FORM_BANDS = {
    # (w, h): (城市行 y0, y1, 日期行 y0, y1, 最小行高)
    (900, 1600): (560, 700, 700, 830, 30),
    (1260, 2800): (800, 900, 1000, 1100, 45),
}


def _form_bands(screen):
    """返回 (city0, city1, date0, date1, min_h)；未知尺寸按 900 等比缩放。"""
    try:
        key = (int(screen[0]), int(screen[1])) if screen else None
    except (TypeError, ValueError, IndexError):
        key = None
    if key in _FORM_BANDS:
        return _FORM_BANDS[key]
    if not key:
        return _FORM_BANDS[(900, 1600)]
    kx, ky = key[0] / 900.0, key[1] / 1600.0
    return (560 * ky, 700 * ky, 700 * ky, 830 * ky, 30 * ky)


def parse_form_words(items, screen=None):
    """飞猪机票表单页 OCR 词块 → 当前航线/日期/可点坐标。

    表单也是 Flutter 画布；用大字号城市行和日期行定位。返回空字段表示
    该页不是可识别的机票表单（调用方应记 unsupported，不要盲点坐标）。

    ``screen=(w, h)`` 时按 `_FORM_BANDS` 查表取窗口（见上面的说明：
    这条不能等比缩放）。同时显式排除「单程/往返/多程」档位标签，
    避免把 tab 当成城市名。
    """
    city0, city1, date0, date1, min_h = _form_bands(screen)
    _TAB = ("单程", "往返", "多程", "国内", "国际", "单程往返")
    lines = _lines(_words(items))
    cities = [ln for ln in lines
              if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", ln["text"])
              and ln["text"] not in _TAB
              and ln["h"] >= min_h
              and city0 <= ln["y"] <= city1]
    cities.sort(key=lambda ln: ln["x"])
    dep = cities[0] if len(cities) >= 1 else None
    arr = cities[-1] if len(cities) >= 2 else None
    # 日期行 OCR 会按字号拆分（「11」「月」「2」「日」y 差 13px），
    # 不能按视觉行合并；按 y 区间 + x 排序重建。
    # 窗口来自 `_form_bands`（实测标定）；左侧 x 上界按屏宽比例放宽，
    # 1260 宽下去程日期在 x≈95..390，左侧 45% 足够。
    _xmax = (screen[0] * 0.45) if screen else 380
    dws = sorted([w for w in _words(items)
                  if date0 <= w["y"] <= date1 and w["x"] < _xmax],
                 key=lambda w: w["x"])
    date_text = "".join(w["t"] for w in dws)
    date_box = None
    if re.search(r"\d{1,2}月\d{1,2}日", date_text) and dws:
        date_box = {
            "x": min(w["x"] for w in dws),
            "y": min(w["y"] for w in dws),
            "w": max(w["x"] + w["w"] for w in dws)
                 - min(w["x"] for w in dws),
            "h": max(w["y"] + w["h"] for w in dws)
                 - min(w["y"] for w in dws),
        }
    search = next((ln for ln in lines if ln["text"] == "搜索机票"), None)
    return {
        "dep": dep["text"] if dep else "",
        "arr": arr["text"] if arr else "",
        "date_text": date_text,
        "dep_xy": _center(dep) if dep else None,
        "arr_xy": _center(arr) if arr else None,
        "date_xy": _center(date_box) if date_box else None,
        "search_xy": _center(search) if search else None,
    }


def parse_words(items, from_city="", to_city="", date=""):
    """OCR 词块 → 航班行（按页面顺序）。

    每行字段：price / list_price / dep_time / arr_time / arr_day_note /
    dep_airport / arr_airport / airline / flight_no / tags / cabin_note。
    """
    words = _words(items)
    anchors = [w for w in words
               if _TWO_DIGIT.match(w["t"]) and w["h"] >= 28
               and w["x"] < 220 and 600 <= w["y"] <= 1520]
    anchors.sort(key=lambda w: w["y"])
    merged = []
    for w in anchors:
        if merged and abs(w["y"] - merged[-1]["y"]) <= 24:
            continue
        merged.append(w)

    rows = []
    for a in merged:
        dep = _time_at(words, a["y"], 0, 300)
        arr = _time_at(words, a["y"], 300, 640)
        if not dep or not arr:
            continue
        big = [w for w in words
               if _PRICE_RE.match(w["t"]) and w["h"] >= 28
               and w["x"] >= 700 and abs(w["y"] - a["y"]) <= 32]
        if not big:
            continue
        pay = max(big, key=lambda w: w["x"])
        small = [w for w in words
                 if _PRICE_RE.match(w["t"]) and w["h"] <= 22
                 and 650 <= w["x"] < 740 and abs(w["y"] - a["y"]) <= 32]
        list_price = max(small, key=lambda w: w["x"])["t"] if small else ""
        fno, fw = _flight_no(words, a["y"] + 95)
        dep_air = _join([w for w in _near(words, a["y"] + 50, tol=16, x0=0,
                                          x1=300)])
        arr_air = _join([w for w in _near(words, a["y"] + 50, tol=16,
                                          x0=400, x1=700)])
        day_note = _join([w for w in words
                          if abs(w["y"] - (a["y"] - 30)) <= 18
                          and 380 <= w["x"] < 620])
        tags = [t for t in _TAGS
                if t in _join([w for w in words
                               if a["y"] - 70 <= w["y"] < a["y"]])]
        cabin = _join([w for w in words
                       if abs(w["y"] - (a["y"] + 52)) <= 20
                       and w["x"] >= 700])
        rows.append({
            "price": int(pay["t"]),
            "list_price": int(list_price) if list_price else None,
            "dep_time": dep,
            "arr_time": arr,
            "arr_day_note": day_note,
            "dep_airport": _airport(dep_air),
            "arr_airport": _airport(arr_air),
            "airline": _airline(words, a["y"] + 95, fw),
            "flight_no": fno,
            "tags": tags,
            "cabin_note": cabin[:20],
            "from_city": from_city,
            "to_city": to_city,
            "date": date,
        })
    # 同航班同刻只留最低支付价（列表滚动会重复）
    merged_rows = {}
    for r in rows:
        key = (r["flight_no"], r["dep_time"], r["arr_time"])
        old = merged_rows.get(key)
        if old is None or r["price"] < old["price"]:
            merged_rows[key] = r
    return sorted(merged_rows.values(),
                  key=lambda r: (r["dep_time"], r["price"]))


def weekday_col(year, month, day):
    """某天在「周日在前」的 7 列日历里应该落在第几列（0..6）。

    这条是日历的**硬约束**，用来校验"价格反推日号"的推断是否错位
    （见 parse_calendar_prices 的 B 段）。
    """
    try:
        first = _date(int(year), int(month), 1)
        c0 = (first.weekday() + 1) % 7      # weekday(): 周一=0 → 周日=0
        return (c0 + int(day) - 1) % 7
    except (TypeError, ValueError):
        return None


def parse_calendar_prices(items, months, today=None, extrapolate=False,
                          cols=None):
    """从飞猪**价格日历页**的 OCR 词块读出 ``[{date, price}]``。

    飞猪日历每格是「日号 + 其下方最低价」（截图实证：日号行 y≈1458、
    价格行 y≈1528，**纵向差约 70px**；无价的日子写「查看」）。
    所以只要把日号的行/列结构与价格对齐，就能整月读出每日最低价——
    这正是「低价源（calendar/low_fare）」这个维度。

    ``cols`` 传该屏幕**实测的 7 列中心 x**（周日→周六）。外推兜底
    （``extrapolate=True``）必须靠它才能把列差换算成日期差；不传就只能
    退回"从价格块聚类"，那种网格在缺列时会塌缩，属于未标定状态。

    ``months`` 是 `AppFliggyCrawler._visible_months()` 的返回值
    ``[(year, month, header_y), ...]``，用来把日号归到具体月份，
    并限定每个月的纵向区间（表头 → 下个月表头）。

    返回的每行是 ``{"date": "YYYY-MM-DD", "price": float, "src": "app-calendar"}``。
    """
    words = _words(items or [])
    if not words or not months:
        return []
    today = today or _date.today()

    bands = []
    for i, m in enumerate(months):
        lo = float(m[2])
        hi = (float(months[i + 1][2]) if i + 1 < len(months)
              else lo + 1500)
        bands.append(((int(m[0]), int(m[1])), lo, hi))
    if not bands:
        return []

    def _band_of(y):
        for ym, lo, hi in bands:
            if lo < y < hi:
                return ym
        return None

    # 1) 日号候选：1..31、≤2 位，且落在某个月的区间内
    day_toks = []
    for w in words:
        t = str(w.get("t") or "").strip()
        if not t.isdigit() or len(t) > 2:
            continue
        n = int(t)
        if not (1 <= n <= 31):
            continue
        y = float(w.get("y") or 0)
        x = float(w.get("x") or 0)
        ym = _band_of(y)
        if ym is None:
            continue
        day_toks.append({"n": n, "x": x + float(w.get("w") or 0) / 2.0,
                         "y": y + float(w.get("h") or 0) / 2.0, "ym": ym})
    if not day_toks:
        return []

    # 2) 行聚类：同一行 ≥4 个日号才算"日号行"（价格行元素少且多为 3 位数）
    rows = {}
    for d in day_toks:
        key = None
        for k in rows:
            if abs(k - d["y"]) <= 25:
                key = k
                break
        rows.setdefault(key if key is not None else d["y"], []).append(d)
    day_rows = [v for v in rows.values() if len(v) >= 4]
    if not day_rows:
        return []
    # 月份**最后一行**常不足 4 个日号（如 11 月只有 29、30），向下补一行，
    # 否则这几天的价格会被整片丢掉（日历价最贵的往往就是月底/节假日）。
    _max_y = max(min(d["y"] for d in g) for g in day_rows)
    for _k, g in rows.items():
        if g in day_rows:
            continue
        _y0 = min(d["y"] for d in g)
        if 0 < (_y0 - _max_y) <= 300:
            day_rows.append(g)
    keep = [d for grp in day_rows for d in grp]

    # 3) 价格：日号**同列下方** 25..130px，值 ≥ 50（票价下限，排除折扣角标）
    prices = []
    for w in words:
        t = str(w.get("t") or "").strip().replace("¥", "").replace("￥", "")
        if not t.isdigit():
            continue
        v = int(t)
        if v < 50:
            continue
        y = float(w.get("y") or 0)
        x = float(w.get("x") or 0)
        prices.append({"v": v, "x": x + float(w.get("w") or 0) / 2.0,
                       "y": y + float(w.get("h") or 0) / 2.0})

    # **锚行**：拿"读全了的日号行"标定出 列→日号 与 行距，
    # 供下面给「只有价格、没有日号」的行反推日号（见价格循环的 B 段）。
    #
    # 列网格来源有两条路，按可靠性排序：
    #   1. ``cols``（外部传入的**实测列中心**）——首选。实测值来自
    #      真机标定，最可靠。
    #   2. 从价格块 x 聚类——只在没标定时兜底；缺列时会塌缩成一两列，
    #      属于"未标定"，此时外推结果不可信。
    # 注意：**不能用锚行自己的 x 当网格**——锚行常常只覆盖中间几列
    # （12 月首行只有 1..5，左侧两列属于 11 月），拿它当网格会整体歪一列。
    anchors = sorted([g for g in day_rows if len(g) >= 4],
                     key=lambda g: min(d["y"] for d in g))
    _col_x, _col_day, _ay, _step = [], {}, None, None
    if anchors:
        if cols:
            _col_x = [float(c) for c in cols]
        else:
            _xs = sorted(p["x"] for p in prices)
            while _xs:                   # 1D 聚类成若干列中心
                base = _xs[0]
                grp = [x for x in _xs if x - base <= 90]
                _col_x.append(sum(grp) / len(grp))
                _xs = [x for x in _xs if x - base > 90]
        _ay = min(d["y"] for d in anchors[0])
        for d in anchors[0]:
            if _col_x:
                _ci = min(range(len(_col_x)),
                          key=lambda i: abs(_col_x[i] - d["x"]))
                _col_day.setdefault(_ci, d["n"])
        for _b in anchors[1:]:
            _by = min(d["y"] for d in _b)
            if _by - _ay > 100:
                _weeks = max(1, round((_by - _ay) / 200.0))
                _step = (_by - _ay) / _weeks
                break
        if _step is None:
            # 只有一行锚时，行距可从**价格行的 y 聚类**自洽求出：
            # 相邻两个价格 band 的差就是一个行距。
            _pys = sorted({round(p["y"] / 25.0) for p in prices})
            _gaps = [(_pys[i + 1] - _pys[i]) * 25.0
                     for i in range(len(_pys) - 1)]
            _gaps = [g for g in _gaps if 120 <= g <= 300]
            if _gaps:
                _step = sum(_gaps) / len(_gaps)

    out = {}
    used = set()

    def _rec(ym, day, val):
        y, m = ym
        try:
            dte = _date(y, m, day)
        except ValueError:          # 该月没有这一天（OCR 误读）
            return
        if dte < today:             # 过去的日子不采
            return
        key = dte.isoformat()
        if key not in out or val < out[key]["price"]:
            out[key] = {"date": key, "price": float(val),
                        "src": "app-calendar"}

    # A) 正常路径：日号行里读到了数字 → 直接对齐下方价格
    for d in keep:
        cands = [p for p in prices
                 if abs(p["x"] - d["x"]) <= 62
                 and 25 <= (p["y"] - d["y"]) <= 130]
        if not cands:
            continue
        p = min(cands, key=lambda c: c["y"] - d["y"])
        used.add(id(p))
        _rec(d["ym"], d["n"], p["v"])

    # B) **兜底路径：日号漏读、只有价格的行**
    #
    # 实测缺口（2026-11-05）：11 月 `08..21` 两行的日号 OCR 读不到，而价格
    # 读得到，于是那两周价格整片丢失（19/33 天）。这里用锚行标定的
    # 「列 → 日号」和行距，从**价格自己的位置**反推它是哪一天：
    # 价格在日号下方约 70px，所以日号行 y ≈ 价格 y − 70。
    if extrapolate and _col_x and _step and anchors:
        _anchor_ym = anchors[0][0]["ym"]
        for p in prices:
            if id(p) in used:
                continue
            weeks = int(round((p["y"] - 70 - _ay) / _step))
            if weeks < 0:
                continue
            ci = min(range(len(_col_x)),
                     key=lambda i: abs(_col_x[i] - p["x"]))
            # 锚行常常只覆盖中间几列（月初那几列属于上个月），所以不能
            # 只看「本列有没有已知日号」。改用**任一已知列做参照**：
            #   day = 参照列日号 + (本列 − 参照列) + 7 × 周数
            # 列是逐日递增的，列差就是日期差。
            if not _col_day:
                continue
            _ci_ref = min(_col_day, key=lambda i: abs(i - ci))
            day = _col_day[_ci_ref] + (ci - _ci_ref) + 7 * weeks
            if not (1 <= day <= 31):
                continue
            # **星期列校验**：推断出的日期必须落在与它星期几一致的列上，
            # 否则就是列映射偏了 —— 宁可少一条，也不记错日期。
            _want_col = weekday_col(_anchor_ym[0], _anchor_ym[1], day)
            if _want_col is not None and len(_col_x) == 7 \
                    and _want_col != ci:
                continue
            _rec(_anchor_ym, day, p["v"])

    return sorted(out.values(), key=lambda r: r["date"])

def parse_round_trip_footer(items):
    """解析往返日历底栏 → ``{"dep": (月, 日)|None, "ret": ..., "total": float|None}``。

    截图实证（2026-11-05，1260×2800 真机）底栏：

        去程：12月14日        返程：未选择         往返总价 ¥---

    这是往返流程**唯一的校验依据**：点完两个日期后必须能读出两个具体
    日期，否则不能相信自己点对了。底栏不写年份，所以这里只返回 (月, 日)，
    年份交给调用方按"今天"推断（跨年时 +1）。
    「返程」「回程」两种叫法都出现过，两个都认。
    """
    words = _words(items or [])
    if not words:
        return {"dep": None, "ret": None, "total": None}
    rows = {}
    for w in words:
        t = str(w.get("t") or "").strip()
        if not t:
            continue
        try:
            y = float(w.get("y") or 0)
            x = float(w.get("x") or 0)
        except (TypeError, ValueError):
            continue
        key = None
        for k in rows:
            if abs(k - y) <= 18:
                key = k
                break
        rows.setdefault(key if key is not None else y, []).append((x, t))
    if not rows:
        return {"dep": None, "ret": None, "total": None}
    # **把所有行拼起来一起找**，不要只取最后一行：
    # 底部「确定」按钮自成一行，比底栏更靠下；只取 max(rows) 会拿到按钮行，
    # 于是 dep/ret 全 None（2026-11-06 实测：截图里两个日期都已选中，
    # 校验却报"未选择/未选择"）。「去程/返程/总价」这些词在页面里唯一，
    # 全文搜索不会误命中。
    line = "".join(t for _y, items in sorted(rows.items())
                   for _x, t in sorted(items))

    def _md(label):
        m = re.search(label + r"[：:]?\s*(\d{1,2})月(\d{1,2})日", line)
        if not m:
            return None
        mo, dd = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= dd <= 31):
            return None
        return (mo, dd)

    dep = _md("去程")
    ret = _md("(?:返程|回程)")
    total = None
    m = re.search(r"(?:往返总价|总价)[^￥¥\d]{0,6}[￥¥]?\s*(\d+)", line)
    if m:
        try:
            total = float(m.group(1))
        except ValueError:
            total = None
    return {"dep": dep, "ret": ret, "total": total}


def parse_round_trip_result(items):
    """往返结果页 → ``{"total": float|None, "dep_min": float|None}``。

    ``total`` 只在页面上确实出现「往返总价」标签时才给（否则 None，
    绝不拿去程价冒充往返价）；``dep_min`` 是首条去程卡片的「起」价。
    """
    words = _words(items or [])
    if not words:
        return {"total": None, "dep_min": None}
    rows = {}
    for w in words:
        t = str(w.get("t") or "").strip()
        if not t:
            continue
        try:
            y = float(w.get("y") or 0)
            x = float(w.get("x") or 0)
            ww = float(w.get("w") or 0)
            hh = float(w.get("h") or 0)
        except (TypeError, ValueError):
            continue
        key = None
        for k in rows:
            if abs(k - y) <= 16:
                key = k
                break
        rows.setdefault(key if key is not None else y,
                        []).append((x, ww, hh, t))
    # 全文拼接（标签与值常在不同行，不能只看一行）
    line = "".join(t for _y, items in sorted(rows.items())
                   for _x, _w, _h, t in sorted(items))
    has_total_label = "往返总价" in line or "往返含税" in line

    # 价格 token：带 ¥ 或以数字开头、值 ≥ 50
    prices = []
    for w in words:
        raw = str(w.get("t") or "").strip()
        if not raw:
            continue
        if "¥" not in raw and "￥" not in raw and not raw[:1].isdigit():
            continue
        nums = re.findall(r"\d{2,6}", raw.replace(",", ""))
        if not nums:
            continue
        try:
            v = float(nums[0])
        except ValueError:
            continue
        if v < 50:
            continue
        prices.append((float(w.get("y") or 0), float(w.get("x") or 0), v))
    if not prices:
        return {"total": None, "dep_min": None}
    prices.sort()
    total = prices[-1][2] if has_total_label else None      # 最底部＝总价
    # 起价只在**卡片区**取：顶部有「50元优惠券」这类营销数字（y≈290），
    # 底部是总价区（y>2600），两者都不能当去程起价。
    cards = [(py, px, v) for py, px, v in prices if 600 <= py <= 2600]
    dep_min = cards[0][2] if cards else None
    return {"total": total, "dep_min": dep_min}
