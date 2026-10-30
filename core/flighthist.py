# -*- coding: utf-8 -*-
"""航班维度键与舱位归一（航线全量采集 → 航班历史落库单源）。

与 webui `_srx_flight_key` / `_watch_cabin` 同口径：航班号复合段排序、
日期/起降/中转/跨天/经停全纳入；舱位按中文大类的第一个词归一。
"""
import re

from .flightnorm import cabin_text as _cabtxt
from .flightnorm import dep_mismatch as _dmis
from .flightnorm import normalize as _normalize

_CABIN_RE = re.compile(r"(超级?经济|经济|公务|头等|商务)")


def flight_key(from_city, to_city, date, code, dep, arr,
               trans="", cross="", stop=False):
    code = str(code or "").upper().replace(" ", "")
    dep = str(dep or "").strip()
    arr = str(arr or "").strip()
    if not code or not dep or not arr:
        return ""
    segs = [x for x in code.replace("，", "/").replace(",", "/").split("/") if x]
    code_n = "/".join(sorted(segs))
    return "|".join((str(from_city or ""), str(to_city or ""), code_n,
                     str(date or ""), dep, arr, str(trans or ""),
                     str(cross or ""), "1" if stop else "0"))


_CABIN_CODE = {"Y": "经济", "W": "超级经济", "S": "超级经济",
               "C": "公务", "J": "公务", "D": "公务",
               "F": "头等", "A": "头等", "P": "头等"}


def cabin_class(text):
    """中文舱位大类 / 显式舱位码；国内纯折扣词归经济舱，机型等噪音归空。

    国内渠道的 cabin_text 常只写「7.0折」「4.7折」「全价」「特价」——
    这些是经济舱的折扣描述（公务/头等会先被 _CABIN_RE 命中）。旧实现
    一律返回空，导致 flight_daily 的 cabin 桶为空：用户关注「经济舱」
    时，去哪儿/飞猪的折扣行全部失配，只剩携程的「经济舱」行（审计实测
    1/5 渠道）。纯机型/余票/乱码仍返回空，宁缺勿错。
    """
    s = str(text or "").strip()
    m = _CABIN_RE.search(s)
    if m:
        return m.group(1)
    if "折" in s or "全价" in s or "特价" in s:
        return "经济"
    return _CABIN_CODE.get(s.upper(), "")


def normalize_raw(raw, date, platform):
    """归一 raw 元素；返回 None 表示日期/价格口径不可用。"""
    if not isinstance(raw, dict) or raw.get("price") in (None, ""):
        return None
    g = dict(raw)
    g["_platform"] = platform
    _normalize(g, date or "")
    if _dmis(g, date or ""):
        return None
    return g


def key_from_raw(from_city, to_city, date, raw, platform):
    g = normalize_raw(raw, date, platform)
    if g is None:
        return None
    key = flight_key(from_city, to_city, date,
                     g.get("code"), g.get("depTime"), g.get("arrTime"),
                     g.get("transCity") or "", g.get("crossDayDesc") or "",
                     bool(g.get("stopover")))
    if not key:
        return None
    cabin = cabin_class(_cabtxt(g))
    try:
        price = round(float(g.get("price")))
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return g, key, cabin, price
