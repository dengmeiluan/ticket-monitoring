# -*- coding: utf-8 -*-
"""去哪儿 App 往返页解析（纯函数，离线可测）。

真机 dump（2026-10-31，北京⇄上海 11-05 → 11-27，1600×900）**带结构化
content-desc**，不需要按几何猜：

    FlightsRound_go_selected      去程卡（该卡已被选中）
    go_depTime / go_arrTime       去程起降时刻
    go_aircraftType               去程航班号（`东航MU5186`）
    go_depPrice                   去程票价（**单程段价**）
    FlightsRound_back_selected    返程卡（该卡已被选中）
    back_depTime / back_arrTime   返程起降时刻
    back_aircraftType             返程航班号
    back_supplyPrice              **返程加价**（`补¥0 / 补¥42`），不是票价

票价口径（真机三次对照）：

    go_depPrice  938  + back_supplyPrice  0   → 页脚「往返价格 ¥938」
    go_depPrice  947  + back_supplyPrice -6   → 页脚「往返价格 ¥941」
    go_depPrice  938  + back_supplyPrice 42   → 页脚「往返价格 ¥980」

所以往返总价 = 去程段价 + 返程加价。页脚 `[x,834][…]` 的 `¥NNN` 节点是
**当前选中组合**的总价；解析器把它单独取出来，供调用方核对。

底部另有 `全屏列` 之外的 `往返总价：¥NNN`（日历弹层里），那是日历报价，
与列表页无关——本模块只认列表页（有 `FlightsRound_` 前缀的页面）。
"""
from __future__ import annotations

import re
from typing import List, Optional

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
_TEXT_RE = re.compile(r'text="([^"]*)"')
_DESC_RE = re.compile(r'content-desc="([^"]*)"')
_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_FLIGHT_RE = re.compile(r"([A-Z0-9]{2}\d{3,4})(?![0-9])")
_INT_RE = re.compile(r"-?\d+")

_PREFIX = "flight_module_search|"
_GO_CARD = _PREFIX + "QunarFlightList|FlightsRound_go_"
_BACK_CARD = _PREFIX + "QunarFlightList|FlightsRound_back_"
_W = _PREFIX + "round_way_flights|"


def _nodes(xml: str):
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        s = m.group(1)
        d = _DESC_RE.search(s)
        t = _TEXT_RE.search(s)
        b = _BOUNDS_RE.search(s)
        if not b:
            continue
        out.append({
            "desc": (d.group(1) if d else "").strip(),
            "text": (t.group(1) if t else "").strip(),
            "x1": int(b.group(1)), "y1": int(b.group(2)),
            "x2": int(b.group(3)), "y2": int(b.group(4)),
        })
    return out


def _cy(n):
    return (n["y1"] + n["y2"]) // 2


def is_round_trip_page(xml: str) -> bool:
    """往返结果页判据：左右两个可滚动列 + 去程卡。"""
    s = xml or ""
    return (_PREFIX + "QunarFlightList|ScrollView_go") in s and \
        (_PREFIX + "QunarFlightList|ScrollView_back") in s


def parse_go_rows(xml: str) -> List[dict]:
    """去程列每一行 → [{flight_no, depart_time, arrive_time, price, y1}]。

    卡与卡之间按 y 分段：卡容器 `FlightsRound_go_*` 的上下沿就是该卡
    （真机卡高 165–179px）。卡内 `go_depPrice` 缺失的行丢弃——不给 0。
    """
    ns = _nodes(xml)
    cards = [n for n in ns if n["desc"].startswith(_GO_CARD)]
    out: List[dict] = []
    for c in cards:
        inner = [n for n in ns
                 if c["y1"] <= _cy(n) <= c["y2"] and n["desc"].startswith(_W)]
        price = _first_int(inner, "go_depPrice")
        if price is None:
            continue
        dep = _first_text(inner, "go_depTime")
        arr = _first_text(inner, "go_arrTime")
        fno = ""
        for n in inner:
            if n["desc"].endswith("go_aircraftType"):
                m = _FLIGHT_RE.search(n["text"])
                if m:
                    fno = m.group(1)
                    break
        out.append({"flight_no": fno, "depart_time": dep,
                    "arrive_time": arr, "price": price,
                    "y1": c["y1"], "y2": c["y2"],
                    "cx": (c["x1"] + c["x2"]) // 2,
                    "cy": _cy(c)})
    out.sort(key=lambda r: r["y1"])
    return out


def parse_back_rows(xml: str) -> List[dict]:
    """返程列每一行 → [{flight_no, depart_time, arrive_time,
    supply_price, y1}]。

    `back_supplyPrice` 是**返程加价**（`补¥0/补¥42/补¥77`，实测同一去程下
    三档），不是返程票价：把它当票价会得到 0 元或几十元的假数据。
    """
    ns = _nodes(xml)
    cards = [n for n in ns if n["desc"].startswith(_BACK_CARD)]
    out: List[dict] = []
    for c in cards:
        inner = [n for n in ns
                 if c["y1"] <= _cy(n) <= c["y2"] and n["desc"].startswith(_W)]
        supply = _first_int(inner, "back_supplyPrice")
        fno = ""
        for n in inner:
            if n["desc"].endswith("back_aircraftType"):
                m = _FLIGHT_RE.search(n["text"])
                if m:
                    fno = m.group(1)
                    break
        out.append({"flight_no": fno,
                    "depart_time": _first_text(inner, "back_depTime"),
                    "arrive_time": _first_text(inner, "back_arrTime"),
                    "supply_price": supply, "y1": c["y1"]})
    out.sort(key=lambda r: r["y1"])
    return out


def parse_footer_total(xml: str) -> Optional[int]:
    """页脚「往返价格」的总价（当前选中组合）。

    真机页脚：`¥980`（y≈834） + `往返价格`（y≈876）。取「往返价格」文案
    上方 90px 内、带 `¥` 的数字节点；页脚不在（未选中组合）时返回 None。
    只看屏幕底部 200px：底部条之外的 `¥` 属于列表卡片。
    """
    ns = _nodes(xml)
    label = None
    for n in ns:
        if n["text"] == "往返价格":
            label = n
            break
    if label is None:
        return None
    best = None
    for n in ns:
        if label["y1"] - 100 <= n["y1"] <= label["y1"] + 20 and \
                n["text"].startswith(("¥", "￥")):
            m = _INT_RE.search(n["text"])
            if m:
                best = int(m.group(0))
    return best


def _first_text(inner, suffix):
    for n in inner:
        if n["desc"].endswith(suffix) and n["text"]:
            return n["text"]
    return ""


def _first_int(inner, suffix):
    for n in inner:
        if n["desc"].endswith(suffix):
            m = _INT_RE.search(n["text"])
            if m:
                return int(m.group(0))
    return None
