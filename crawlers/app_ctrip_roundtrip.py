# -*- coding: utf-8 -*-
"""携程 App 往返结果页（去程/返程双栏）解析。

真机（2026-11-03）页面结构：
* 头部城市之间是双向箭头，左栏「去程」、右栏「返程」；
* 去程卡片上的价格就是**页脚「往返总价」**（默认返程为 +¥0 的最低价
  组合）；真机点第 2 条去程后，页脚从 ¥2146 变为该卡的 ¥2189，证明
  卡片价不是单程价，也不是两段相加；
* 返程小卡给的是相对当前去程的差价（+¥0 / +¥389 …），不是整价；
  所以往返总价只取去程卡片价 / 页脚，绝不拿返程差价冒充。
"""
from __future__ import annotations

import re

from .app_ctrip_parse import nodes

_FIELD = {
    # CLI dump（国际页实测）
    "起飞时间": "dep_time",
    "到达时间": "arr_time",
    "价格": "price",
    "起飞机场": "dep_airport",
    "到达机场": "arr_airport",
    "起飞机场高亮": "dep_airport",
    "到达机场高亮": "arr_airport",
    "航司名称": "airline",
    "飞行时长": "duration",
    "隔天信息": "cross",
    # u2 回退 dump（国内页实测，CLI 撞动画时走这条）
    "出发时间": "dep_time",
    "出发机场": "dep_airport",
    "出发机场高亮": "dep_airport",
    "航司信息": "airline",
    "机型": "aircraft",
}
_CARD_RE = re.compile(r"^(去程|返程)(?:小卡)?第(\d+)条航班(.+)$")
_SELECTED = ("被选中", "控件选中")
_FOOTER_DESCS = ("底部往返总价", "往返总价金额")


def _num(text):
    m = re.search(r"\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(m.group(0)) if m else None


def is_round_trip_page(xml: str) -> bool:
    """CLI dump 与 u2 回退 dump 的措辞不同，两种都认。"""
    if not xml:
        return False
    descs = [n["desc"] for n in nodes(xml)]
    has_go = "去程" in descs or "第一程标题" in descs or any(
        d.startswith("去程第") for d in descs)
    has_back = "返程" in descs or "第二程标题" in descs or any(
        d.startswith("返程第") for d in descs)
    return has_go and has_back


def is_round_trip_form(xml: str) -> bool:
    return bool(xml) and any(n["desc"] == "return date" for n in nodes(xml))


def is_round_trip_picker(xml: str) -> bool:
    return bool(xml) and any(
        n["text"] == "选择往返日期" for n in nodes(xml))


def picker_footer(xml: str):
    """往返日历底部已选的 (去程 MM-DD, 返程 MM-DD)；读不全返回空串。"""
    ds = [n["text"] for n in nodes(xml)
          if n["y1"] >= 1400 and re.fullmatch(r"\d{2}-\d{2}", n["text"] or "")]
    return (ds[0], ds[1]) if len(ds) >= 2 else ("", "")


def selected_card(cards, idx):
    for c in cards or []:
        if c.get("idx") == idx:
            return c
    return (cards or [{}])[0]


def parse_round_trip(xml: str):
    """→ {go, back, go_sel, back_sel, footer_total}；不是往返页返回 None。"""
    if not is_round_trip_page(xml):
        return None
    cards = {"go": {}, "back": {}}
    sel = {"go": None, "back": None}
    footer = None
    for n in nodes(xml):
        d = n["desc"]
        if d in _FOOTER_DESCS:
            footer = _num(n["text"])
            continue
        m = _CARD_RE.match(d)
        if not m:
            continue
        side = "go" if m.group(1) == "去程" else "back"
        idx = int(m.group(2))
        field = m.group(3).strip()
        if field.startswith("的"):
            field = field[1:]
        card = cards[side].setdefault(idx, {"idx": idx})
        if field in _SELECTED:
            sel[side] = idx
            continue
        if field in _FIELD:
            key = _FIELD[field]
            if key == "price":
                # 返程卡的价格是相对当前去程的差价，单独放，别当总价。
                key = "price" if side == "go" else "ret_diff"
            if key in ("price", "ret_diff"):
                v = _num(n["text"])
                if v is not None:
                    card[key] = v
            else:
                card[key] = n["text"]
            continue
        mm = re.match(r"航司(?:logo|LOGO)(?:二字码为)?\s*([A-Z0-9]{2})$",
                      field)
        if mm:
            card["airline_code"] = mm.group(1)
    go = [cards["go"][i] for i in sorted(cards["go"])
          if cards["go"][i].get("price") is not None]
    back = [cards["back"][i] for i in sorted(cards["back"])]
    return {"go": go, "back": back, "go_sel": sel["go"],
            "back_sel": sel["back"], "footer_total": footer}


def build_combos(parsed, dep_date: str, ret_date: str):
    """去程卡 × 当前选中返程 → 页面往返总价组合（不相加两段）。"""
    ret = selected_card(parsed.get("back") or [], parsed.get("back_sel"))
    combos = []
    for c in parsed.get("go") or []:
        if c.get("price") is None:
            continue
        combos.append({
            "price": float(c["price"]),
            "code": "",
            "name": c.get("airline") or "",
            "airlineCode": c.get("airline_code") or "",
            "depDate": dep_date,
            "depTime": c.get("dep_time") or "",
            "arrTime": c.get("arr_time") or "",
            "depAirport": c.get("dep_airport") or "",
            "arrAirport": c.get("arr_airport") or "",
            "duration": c.get("duration") or "",
            "cross": c.get("cross") or "",
            "retDate": ret_date,
            "retDepTime": ret.get("dep_time") or "",
            "retArrTime": ret.get("arr_time") or "",
            "retAirline": ret.get("airline") or "",
            "retDiff": ret.get("ret_diff"),
            "retLoaded": bool(ret),
            "tripType": "RT",
            "totalBasis": "page_roundtrip_total",
        })
    return combos
