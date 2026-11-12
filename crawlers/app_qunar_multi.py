# -*- coding: utf-8 -*-
"""去哪儿 App 两程多程页解析（2026-11-03 真机页面）。

页面形态（900x1600，RN）：
  * 顶部「选择航班」；左栏「第一程 01.30」、右栏「第二程 02.17」；
  * 第一程每行的列价是**默认第二程（+¥0）组合的整单总价**（实测 ¥5069）；
    换 +¥150 的第二程后**左列价不变**，只有页脚从 ¥5069 变 ¥5219——
    左列不是「当前选择」的总价，页脚才是；
  * 第二程每行给相对加价 `+¥N`；底部「已选 08:00-20:50 … +¥150」与
    CountUpPrice「¥5219」+「两程含税总价」才是整单口径。

解析只认页面自报的整单总价；`+¥N` 是加价、不是票价。当前仅两程
（`两程含税总价`）；三程及以上形态未验，返回 None，不猜。

**接入状态**：本模块是纯解析器，尚未接监控——产品的 `Route`/`FlightPrice`
仍是单 O-D，多段行程没有落库/配置形状；等 §1.6 的数据模型落地后再由
`fetch_multi` 调用，矩阵 multi_city 在接通前保持 `""`。
"""
from __future__ import annotations

import re
from typing import List, Optional

_NODE_RE = re.compile(r"<node([^>]*?)/?>")
_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def _attr(attrs: str, name: str) -> str:
    m = re.search(r'%s="([^"]*)"' % name, attrs)
    return m.group(1).strip() if m else ""

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_FLIGHT_ID_RE = re.compile(r"FlightsRound_([A-Z0-9]{2}\d{3,4})\|")
_TOTAL_LABEL = "两程含税总价"
_DUR_RE = re.compile(r"\d+时(?:\d+分)?")
_SUR_RE = re.compile(r"\+?\s*[¥￥]\s*(\d+(?:\.\d+)?)")
_AIRPORT_TAIL = re.compile(r"^T\d$")


def _nodes(xml: str) -> List[dict]:
    """u2 把行容器 id 放在 content-desc、可见文案放在 text。"""
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        attrs = m.group(1)
        text = _attr(attrs, "text") or _attr(attrs, "content-desc")
        b = _BOUNDS_RE.search(attrs)
        if not text or not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        out.append({"text": text, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2})
    return out


def _is_time(t: str) -> bool:
    m = _TIME_RE.match(t or "")
    if not m:
        return False
    return int(m.group(1)) <= 23 and int(m.group(2)) <= 59


def _num(t: str) -> Optional[float]:
    m = re.search(r"\d+(?:\.\d+)?", t or "")
    return float(m.group(0)) if m else None


def _airport(ns, y_lo, y_hi, x_lo, x_hi) -> str:
    """机场拼「城市+航站楼」：dump 里是 美兰 / T1 两个节点。"""
    terms = [n for n in ns if y_lo <= n["cy"] <= y_hi
             and x_lo <= n["x1"] <= x_hi and _AIRPORT_TAIL.match(n["text"])]
    for t in sorted(terms, key=lambda n: n["x1"]):
        name = [n for n in ns if abs(n["cy"] - t["cy"]) <= 6
                and n["x2"] <= t["x1"] and 2 <= len(n["text"]) <= 8
                and re.fullmatch(r"[一-鿿]{2,6}", n["text"])]
        if name:
            base = max(name, key=lambda n: n["x2"])["text"]
            return base + t["text"]
    return ""


def _container_flight(n: dict) -> str:
    m = _FLIGHT_ID_RE.search(n["text"] or "")
    return m.group(1) if m else ""


def _first_rows(ns, boxes) -> List[dict]:
    rows = []
    for box in boxes:
        if box["x2"] > 160:
            continue
        flight_no = _container_flight(box)
        if not flight_no:
            continue
        inside = [n for n in ns if box["y1"] <= n["cy"] <= box["y2"]
                  and n["x2"] <= 160]
        dep = next((n for n in inside if _is_time(n["text"])
                    and n["x1"] < 80), None)
        arr = next((n for n in inside if _is_time(n["text"])
                    and n["x1"] >= 80), None)
        price_n = next((n for n in inside if "¥" in n["text"]
                        and n["y1"] <= box["y1"] + 80
                        and n["x1"] < 80), None)
        pay = _num(price_n["text"]) if price_n else None
        if not (dep and arr and pay is not None):
            continue
        rows.append({"flight_no": flight_no, "dep_time": dep["text"],
                     "arr_time": arr["text"], "price": pay,
                     "price_basis": "page_multicity_base_total",
                     "direct": any("直飞" in n["text"] for n in inside)})
    return rows


def _second_rows(ns, boxes) -> List[dict]:
    rows = []
    for box in boxes:
        if box["x1"] < 150:
            continue
        flight_no = _container_flight(box)
        if not flight_no:
            continue
        inside = [n for n in ns if box["y1"] <= n["cy"] <= box["y2"]
                  and n["x1"] >= 159]
        dep = next((n for n in inside if _is_time(n["text"])
                    and 160 <= n["x1"] <= 260), None)
        arr = next((n for n in inside if _is_time(n["text"])
                    and 440 <= n["x1"] <= 540), None)
        sur_n = next((n for n in inside if "¥" in n["text"]
                      and ("+" in n["text"] or n["x1"] >= 800)
                      and n["y1"] <= box["y1"] + 80), None)
        sur = _num(sur_n["text"]) if sur_n else None
        if not (dep and arr and sur is not None):
            continue
        # 同卡里还有中转段时长（更靠左）；整段时长取最靠右的那个。
        durs = [(n["x1"], m.group(0)) for n in inside
                for m in [_DUR_RE.search(n["text"])]
                if m and n["x1"] > 260]
        dur = max(durs)[1] if durs else ""
        transfer = next((n["text"] for n in inside
                         if n["text"].startswith("转 ")
                         or re.match(r"^\d转", n["text"])), "")
        airline = next((n["text"] for n in inside
                        if ("航空" in n["text"] or "航司" in n["text"])),
                       "")
        rows.append({
            "flight_no": flight_no, "dep_time": dep["text"],
            "arr_time": arr["text"],
            "dep_airport": _airport(ns, box["y1"], box["y2"], 160, 300),
            "arr_airport": _airport(ns, box["y1"], box["y2"], 440, 560),
            "duration": dur, "transfer": transfer, "airline": airline,
            "surcharge": sur})
    return rows


def is_multi_city_page(xml: str) -> bool:
    s = xml or ""
    return _TOTAL_LABEL in s and "第一程" in s and "第二程" in s


def parse_multi_city(xml: str) -> Optional[dict]:
    """两程多程页 → 整单总价 + 两段行；三程/非总价页返回 None。"""
    if not is_multi_city_page(xml):
        return None
    ns = _nodes(xml)
    boxes = [n for n in ns
             if n["text"].startswith(
                 "flight_search_rn|QunarFlightInterList|FlightsRound_")]
    first = _first_rows(ns, boxes)
    second = _second_rows(ns, boxes)
    if not first or not second:
        return None
    label = next((n for n in ns if n["text"] == _TOTAL_LABEL), None)
    total = None
    if label is not None:
        cands = [n for n in ns if n["cy"] < label["cy"]
                 and 0 < label["cy"] - n["cy"] <= 50
                 and n["x2"] <= 150 and re.fullmatch(r"\d+(?:\.\d+)?",
                                                     n["text"])]
        if cands:
            total = float(max(cands, key=lambda n: n["cy"])["text"])
    if total is None:
        return None
    sel_node = next((n for n in ns if n["text"] == "已选"
                     and n["cy"] > 1400), None)
    sel = ""
    if sel_node is not None:
        near = sorted([n for n in ns if abs(n["cy"] - sel_node["cy"]) <= 15
                       and n["x1"] > sel_node["x2"]], key=lambda n: n["x1"])
        sel = " ".join([sel_node["text"]] + [n["text"] for n in near[:5]])
    sel_times = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", sel)
    selected = None
    if sel_times:
        dep, arr = sel_times.group(1), sel_times.group(2)
        selected = next((r for r in second
                         if r["dep_time"] == dep and r["arr_time"] == arr),
                        None)
        if selected is not None:
            selected = dict(selected, selected=True)
    discount = next((n["text"] for n in ns
                     if "全程下单可减" in n["text"]), "")
    if not discount:
        disc = next((n for n in ns if "全程下单可减" in n["text"]), None)
        discount = disc["text"] if disc else ""
    note = ""
    if selected is not None:
        note = "已选 %s-%s %s %s +¥%.0f" % (
            selected["dep_time"], selected["arr_time"],
            selected["duration"], selected["transfer"],
            selected["surcharge"])
    elif sel:
        note = sel
    return {
        "legs": 2,
        "total": total,
        "total_label": _TOTAL_LABEL,
        "total_basis": "page_multicity_total",
        "discount": discount,
        "first": sorted(first, key=lambda r: (r["dep_time"], r["price"])),
        "second": sorted(second, key=lambda r: (r["surcharge"],
                                                 r["dep_time"])),
        "selected_second": selected,
        "selected_note": note,
    }
