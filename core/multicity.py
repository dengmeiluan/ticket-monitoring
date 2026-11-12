# -*- coding: utf-8 -*-
"""多程行程的数据契约（存储层已接，采集/配置/UI 尚未接）。

口径（HANDOFF_CAPABILITY_MATRIX §1.6）：
- 2–4 段；每段 from/to/date；
- 行级 extra 必须带 tripType="MC"、legs、totalBasis；
- 只接受渠道页面自报的整单总价；legs 里出现 price/total 一律拒绝，
  从形状上杜绝「两段单程相加冒充多程总价」。

矩阵 multi_city 仍为 ""：本模块只保证落库形状正确，不代表监控已接通。
"""
import datetime as _dt
import json
import re

TRIP_TYPE = "MC"
MIN_SEGMENTS = 2
MAX_SEGMENTS = 4
CODE_RE = re.compile(r"^[A-Z]{3}$")
# legs 允许字段：只放身份/时刻，不放任何价格字段
LEG_KEYS = ("flight_no", "airline", "from", "to", "date", "dep", "arr",
            "duration", "transfer")
PRICE_KEYS = ("price", "total", "total_price", "amount", "fare")


class MultiCityError(ValueError):
    """多程形状不合法（调用方应把它当数据错误，不落库）。"""


def _norm_code(v, where):
    s = str(v or "").strip().upper()
    if not CODE_RE.match(s):
        raise MultiCityError("%s 不是三字码：%r" % (where, v))
    return s


def _norm_date(v, where):
    s = str(v or "").strip()
    try:
        _dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        raise MultiCityError("%s 日期不是 YYYY-MM-DD：%r" % (where, v))
    return s


def normalize_segments(segments):
    """校验并归一 2–4 段；返回 [{"from","to","date"}]。"""
    if not isinstance(segments, (list, tuple)):
        raise MultiCityError("segments 必须是列表")
    if not (MIN_SEGMENTS <= len(segments) <= MAX_SEGMENTS):
        raise MultiCityError("多程段数必须为 %d–%d，收到 %d"
                             % (MIN_SEGMENTS, MAX_SEGMENTS, len(segments)))
    out = []
    for i, seg in enumerate(segments):
        where = "第 %d 段" % (i + 1)
        if isinstance(seg, dict):
            frm, to, date = seg.get("from"), seg.get("to"), seg.get("date")
        elif isinstance(seg, (list, tuple)) and len(seg) >= 3:
            frm, to, date = seg[0], seg[1], seg[2]
        else:
            raise MultiCityError("%s 形状不合法：%r" % (where, seg))
        out.append({"from": _norm_code(frm, where + " from"),
                    "to": _norm_code(to, where + " to"),
                    "date": _norm_date(date, where + " date")})
    return out


def segments_key(segments):
    """稳定键：SHA-NRT@2026-11-20|NRT-OSA@2026-11-23。"""
    segs = normalize_segments(segments)
    return "|".join("%s-%s@%s" % (s["from"], s["to"], s["date"])
                    for s in segs)


def build_mc_extra(legs, total_basis="page_multicity_total"):
    """构造 MC 行级 extra；legs 不得携带任何价格字段。"""
    if not isinstance(legs, (list, tuple)) or not legs:
        raise MultiCityError("legs 必须是非空列表")
    out = []
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise MultiCityError("第 %d 段 legs 不是对象：%r" % (i + 1, leg))
        bad = [k for k in PRICE_KEYS if k in leg]
        if bad:
            raise MultiCityError(
                "legs 不得带价格字段 %s（多程价只能是渠道整单总价）"
                % ",".join(bad))
        rec = {k: leg[k] for k in LEG_KEYS
               if leg.get(k) not in (None, "")}
        if not rec.get("flight_no"):
            raise MultiCityError("第 %d 段缺少 flight_no" % (i + 1))
        if "from" in rec:
            rec["from"] = _norm_code(rec["from"], "第 %d 段 from" % (i + 1))
        if "to" in rec:
            rec["to"] = _norm_code(rec["to"], "第 %d 段 to" % (i + 1))
        if "date" in rec:
            rec["date"] = _norm_date(rec["date"], "第 %d 段 date" % (i + 1))
        out.append(rec)
    return {"tripType": TRIP_TYPE, "legs": out,
            "totalBasis": str(total_basis or "page_multicity_total")}


def parse_mc_extra(extra):
    """把 extra（JSON 字符串/对象）解析为 MC 对象；非 MC 返回 None。"""
    obj = extra
    if isinstance(obj, str):
        try:
            obj = json.loads(obj or "null")
        except ValueError:
            return None
    if isinstance(obj, list):
        obj = next((x for x in obj if isinstance(x, dict)
                    and x.get("tripType") == TRIP_TYPE), None)
    if not isinstance(obj, dict) or obj.get("tripType") != TRIP_TYPE:
        return None
    if not isinstance(obj.get("legs"), list) or not obj["legs"]:
        return None
    return obj


def is_mc_extra(extra):
    return parse_mc_extra(extra) is not None
