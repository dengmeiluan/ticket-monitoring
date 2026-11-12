# -*- coding: utf-8 -*-
"""携程 App 纯解析（列表卡片 / 表单 / 城市页 / 日历坐标）。

真机结构（MuMu Android 15，携程 8.97.0）与浏览器/去哪儿完全不同：
  * 机票表单是原生控件，城市位/日期位各自带 `content-desc`
    （`depart city` / `arrival city` / `depart date`）；
  * 城市页结果带 `城市页第N条搜索结果`，支持中文/拼音搜索；
  * 列表页是 React Native 无障碍树：每个航班卡片以
    `resource-id="第CA8322航班"` 为容器，子节点的 `content-desc` 带完整语义
    （`第CA8322航班出发时间` / `…价格` / `…出发机场+航站楼` / `…舱等信息`），
    价格与航班号都**不需要 OCR**；
  * 日历日格是自绘 View（dump 里没有日期/价格文本），只能按坐标点选；
    dump 读不到日历价，但截图 OCR 可读（见 `app_ctrip_calendar.py`），
    是否升 calendar 以真机端到端复验为准。

本模块只做纯函数，所有函数对空串/坏 XML 返回空结果，绝不抛栈。
"""
from __future__ import annotations

import datetime as _dt
import re
from xml.etree import ElementTree as ET

CARD_NO_RE = re.compile(r"^第([A-Z0-9]{2}\d{3,4})航班$")
# 国际列表卡没有航班号，容器是「第7条航班」；字段措辞也不同
# （起飞时间/起飞机场/航司名称）。不把序号冒充航班号。
CARD_ORD_RE = re.compile(r"^第(\d+)条航班$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月$")
LOGIN_MARKS = ("手机验证码登录", "请输入手机号", "获取验证码",
               "账号密码登录", "登录/注册")

#: 日历网格（900×1600 实测）。列中心 66/200/333/466/600/733/866，
#: 行距 100；月标题中心到第一行日期的偏移 51。
CAL_COL0_X = 66.0
CAL_COL_STEP = 133.3
CAL_ROW_STEP = 100.0
CAL_FIRST_ROW_DY = 51.0
# 上面四个常量是**按 900px 宽**标定的（2026-11-02 真机 900×1600）。
#
# 设备换成 vivo X200 Pro（1260×2800）后照常量算会落进相邻日期 ——
# 现场表现是"设日期后日期未变"，账本只记 `app-date timeout`。
# 所以补一套**实测标定**（2026-11-05，从 1260×2800 截图逐像素量出）：
#
#   列起点 = 90      （第 1 列日号中心）
#   列距   = 180     （正好 1260/7，7 等分整宽）
#   行距   = 165     （相邻两周的日号中心距，量了 4 段全部 165）
#   月标题→首行 = 139（月标题 cy 到**第一行**日号 cy）
#
# 这条 139 是踩了一次坑才定下来的：像素扫描在第 1 列只捞到 4 个波段
# （989/1154/1319/1484），我先把 989 当成首行 → 算出的点整体低一行，
# 实测点 (270,1318) 选中的是 **11月23日**而不是 16 日。
# 反推：第 1 列是 1/8/15/22/29 五天，4 个波段其实是 8/15/22/29
# （"1" 这根竖线在窄采样窗口里暗像素不足 3，被阈值滤掉了），
# 所以首行在 989-165=824，DY = 824-685 = 139。
# **验证方式**：点下去之后读表单日期文案，必须是目标日。
CAL_CALIB_WIDTH = 1260.0
CAL_CALIB = (90.0, 180.0, 165.0, 139.0)   # col0, col_step, row_step, first_dy


def _root(xml: str):
    if not xml or "<hierarchy" not in xml:
        return None
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def _node_info(n):
    b = n.get("bounds") or ""
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return {
        "text": (n.get("text") or "").strip(),
        "desc": (n.get("content-desc") or "").strip(),
        "rid": (n.get("resource-id") or "").strip(),
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2,
        "clickable": n.get("clickable") == "true",
    }


def nodes(xml: str):
    root = _root(xml)
    if root is None:
        return []
    out = []
    for n in root.iter("node"):
        info = _node_info(n)
        if info is not None:
            out.append(info)
    return out


def parse_form(xml: str):
    """机票表单的 (出发, 到达, 日期文案)；不是表单返回 None。"""
    dep = arr = date = ""
    for n in nodes(xml):
        d = n["desc"]
        if d == "depart city" and n["text"]:
            dep = n["text"]
        elif d == "arrival city" and n["text"]:
            arr = n["text"]
        elif d == "depart date" and n["text"]:
            date = n["text"]
    if not (dep or arr or date):
        return None
    return {"dep": dep, "arr": arr, "date": date}


# 表单页的结构标记（content-desc）。**空表单也有这些节点**——
# 这正是 2026-11-05 那个坑：冷启动后城市框是空的，`parse_form` 因为
# "dep/arr/date 全空"返回 None，于是 `is_form` 判 False，爬虫以为
# "没到表单页"，点完首页入口后干等 20 秒超时，整轮 0 条。
# 「是不是表单页」和「表单填没填」是两件事，必须分开判。
_FORM_DESCS = ("depart city", "arrival city", "depart date",
               "search flight", "flight search", "choose date")


def is_form_page(xml: str) -> bool:
    """结构上是不是机票表单页（**不要求航线已填**）。"""
    try:
        return any(n["desc"] in _FORM_DESCS for n in nodes(xml))
    except Exception:
        return False


def is_form(xml: str) -> bool:
    return parse_form(xml) is not None or is_form_page(xml)


def is_calendar(xml: str) -> bool:
    return "选择出发日期" in (xml or "") and "仅看直飞" in (xml or "")


def is_city_page(xml: str) -> bool:
    # 到达城市页标题是「选择目的地」（真机 2026-11-02 截图），
    # 只认「选择到达地」会把已经打开的城市页判成没打开。
    return any(k in (xml or "") for k in
               ("热门城市", "选择出发地", "选择到达地", "选择目的地",
                "城市页第1条搜索结果"))


def is_list_page(xml: str) -> bool:
    return ("单程列表页" in (xml or "")
            or bool(parse_flight_cards(xml)))


def is_login_wall(xml: str) -> bool:
    return any(k in (xml or "") for k in LOGIN_MARKS)


def login_slot(xml: str):
    """列表/表单页被登录墙顶掉时，返回登录墙可读判据（空串=不是）。"""
    for k in LOGIN_MARKS:
        if k in (xml or ""):
            return k
    return ""


def parse_months(xml: str):
    """日历里可见的月份标题 [(year, month, header_cy)]，按屏幕从上到下。"""
    out = []
    for n in nodes(xml):
        m = MONTH_RE.match(n["text"])
        if not m:
            continue
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and (y, mo) not in [(a, b) for a, b, _ in out]:
            out.append((y, mo, n["cy"]))
    return out


def calendar_xy(header_cy: int, year: int, month: int, day: int,
                width=None):
    """目标日期在日历里的点击坐标；日期非法返回 None。

    ``width`` 非空时按**实测标定集**（``CAL_CALIB``，1260×2800 逐像素量出）
    等比缩放后再算；不传时沿用 900 基准的老常量（行为与旧版逐字一致，
    既有测试与旧调用方不受影响）。
    """
    try:
        _dt.date(year, month, day)
        first = _dt.date(year, month, 1)
    except ValueError:
        return None
    if width:
        try:
            k = float(width) / CAL_CALIB_WIDTH
        except (TypeError, ValueError):
            k = 1.0
        col0, col_step, row_step, first_dy = (v * k for v in CAL_CALIB)
    else:
        col0, col_step, row_step, first_dy = (CAL_COL0_X, CAL_COL_STEP,
                                              CAL_ROW_STEP, CAL_FIRST_ROW_DY)
    # 周日=第 0 列；Python weekday() 周一=0 → 周日=(weekday+1)%7
    first_col = (first.weekday() + 1) % 7
    idx = first_col + day - 1
    row, col = divmod(idx, 7)
    x = col0 + col * col_step
    y = float(header_cy) + first_dy + row * row_step
    return int(round(x)), int(round(y))


def parse_city_candidates(xml: str, city: str):
    """城市页里与目标城市相关、可点的候选（搜索结果优先）。"""
    city = str(city or "").strip()
    if not city:
        return []
    out = []
    for n in nodes(xml):
        t = n["text"]
        if not t or city not in t:
            continue
        # 搜索结果带三字码/机场；热门城市格只有纯城市名。
        looks_result = bool(re.search(r"[A-Z]{3}", t)) or "机场" in t
        if looks_result or t == city:
            out.append(n)
    # 带机场/三字码的结果排在纯热门格前面；再按 y,x 稳定排序。
    out.sort(key=lambda n: (0 if (re.search(r"[A-Z]{3}", n["text"])
                                  or "机场" in n["text"]) else 1,
                            n["y1"], n["x1"]))
    return out


def _price_of(card_nodes, texts):
    for n in card_nodes:
        if n["desc"].endswith("价格"):
            m = re.search(r"\d+(?:\.\d+)?", n["text"].replace(",", ""))
            if m:
                return float(m.group(0))
    for t in texts:
        m = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", t)
        if m:
            return float(m.group(1))
    return None


def _clean(s):
    return str(s or "").replace("\u200b", "").strip()


def parse_flight_cards(xml: str):
    """列表页航班卡片 → [{flight_no, dep_time, arr_time, dep_airport,
    arr_airport, airline, cabin, price}]。

    只认 `第XXX航班` 容器；价格/时刻缺一不可（宁可少一行，不编造）。
    同一航班号+同一起降时刻只保留最低价（共享航班可能出多卡）。
    国际列表容器是「第N条航班」且不暴露航班号：`flight_no=""`，
    用 (序号, 时刻, 航司) 去重，绝不拿序号冒充航班号。
    """
    root = _root(xml)
    if root is None:
        return []
    by_key = {}
    for card in root.iter("node"):
        rid = (card.get("resource-id") or "").strip()
        desc = (card.get("content-desc") or "").strip()
        m = CARD_NO_RE.match(rid) or CARD_NO_RE.match(desc)
        ordinal = None
        if m:
            no = m.group(1)
        else:
            mo = CARD_ORD_RE.match(rid) or CARD_ORD_RE.match(desc)
            if not mo:
                continue
            no = ""
            ordinal = int(mo.group(1))
        info = _node_info(card)
        if info is None:
            continue
        kids = []
        for c in card.iter("node"):
            ci = _node_info(c)
            if ci is not None:
                kids.append(ci)
        rec = {"flight_no": no}
        if ordinal is not None:
            rec["_ordinal"] = ordinal
        texts = []
        for k in kids:
            d = k["desc"]
            tail = ""
            if m:
                suffix = "第%s航班" % no
                if d.startswith(suffix):
                    tail = d[len(suffix):]
            else:
                fm = re.match(r"^第\d+条航班的?(.+)$", d)
                if fm:
                    tail = fm.group(1)
            if tail in ("出发时间", "起飞时间"):
                rec["dep_time"] = _clean(k["text"])
            elif tail == "到达时间":
                rec["arr_time"] = _clean(k["text"])
            elif tail in ("出发机场+航站楼", "起飞机场"):
                rec["dep_airport"] = _clean(k["text"])
            elif tail in ("到达机场+航站楼", "到达机场"):
                rec["arr_airport"] = _clean(k["text"])
            elif tail in ("航司信息", "航司名称"):
                rec["airline"] = _clean(k["text"])
            elif tail == "舱等信息":
                rec["cabin"] = _clean(k["text"])
            elif tail == "机型":
                rec["aircraft"] = _clean(k["text"])
            if k["text"]:
                texts.append(k["text"])
        price = _price_of(kids, texts)
        if price is None or not rec.get("dep_time") or not rec.get("arr_time"):
            continue
        if not TIME_RE.match(rec["dep_time"]) or not TIME_RE.match(rec["arr_time"]):
            continue
        rec["price"] = float(price)
        for key in ("dep_airport", "arr_airport", "airline", "cabin"):
            rec.setdefault(key, "")
        key = (no, rec["dep_time"], rec["arr_time"],
               rec.get("airline", ""), ordinal)
        old = by_key.get(key)
        if old is None or rec["price"] < old["price"]:
            by_key[key] = rec
    return sorted(by_key.values(), key=lambda r: (r["dep_time"], r["price"]))
