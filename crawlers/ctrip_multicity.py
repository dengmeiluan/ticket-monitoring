# -*- coding: utf-8 -*-
"""携程 PC 多程结果解析与 URL 构造（纯函数；轮尾采集已接，结果面/推送未接）。

口径：只读「多程超低价」组合卡；总价必须是页面自报的「多程含税价」，
legs 只放身份/时刻，不带价格字段（禁止两段单程相加冒充多程总价）。
"""
import re

from core.multicity import (MultiCityError, build_mc_extra,
                            normalize_segments)

_FLIGHT_RE = re.compile(r"^([A-Z0-9]{2}\d{2,4})\s+(.+)$")
_MONTH_RE = re.compile(r"^\d{1,2}月\d{1,2}日\s+(\d{2}:\d{2})$")
_PRICE_RE = re.compile(r"^¥\s*(\d+(?:\.\d+)?)$")


def build_multi_url(segments, cabin="y_s"):
    """city 码按段展开：SHA-TYO + TYO-OSA → multi-sha-tyo-tyo-osa。"""
    segs = normalize_segments(segments)
    codes = [c for s in segs for c in (s["from"].lower(), s["to"].lower())]
    dates = "_".join(s["date"] for s in segs)
    return ("https://flights.ctrip.com/online/list/multi-%s"
            "?depdate=%s&cabin=%s&adult=1&child=0&infant=0"
            % ("-".join(codes), dates, cabin))


def parse_multi_text(text, segments):
    """从结果页文本解析首个组合卡；返回 {price, legs, total_basis}。"""
    segs = normalize_segments(segments)
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    try:
        start = lines.index("多程超低价")
    except ValueError:
        raise MultiCityError("结果页没有「多程超低价」组合卡")
    total = None
    total_at = None
    for i in range(start + 1, min(len(lines), start + 120)):
        m = _PRICE_RE.match(lines[i])
        if m and i + 1 < len(lines) and "多程含税价" in lines[i + 1]:
            total = float(m.group(1))
            total_at = i
            break
    if total is None or total <= 0:
        raise MultiCityError("组合卡没有「多程含税价」总价")
    legs = []
    for n, seg in enumerate(segs, 1):
        hit = None
        for j in range(start + 1, total_at):
            if lines[j] != str(n):
                continue
            if j + 3 >= total_at:
                break
            if _FLIGHT_RE.match(lines[j + 2]):
                hit = j
                break
        if hit is None:
            raise MultiCityError("组合卡缺少第 %d 段" % n)
        fm = _FLIGHT_RE.match(lines[hit + 2])
        dep = _MONTH_RE.match(lines[hit + 3])
        arr = _MONTH_RE.match(lines[hit + 5])
        if not dep or not arr:
            raise MultiCityError("第 %d 段时刻不可解析" % n)
        legs.append({
            "flight_no": fm.group(1),
            "airline": lines[hit + 1],
            "from": seg["from"], "to": seg["to"], "date": seg["date"],
            "dep": dep.group(1), "arr": arr.group(1),
        })
    if len(legs) != len(segs):
        raise MultiCityError("组合卡段数与请求不一致")
    return {"price": total, "legs": legs,
            "total_basis": "page_multicity_total",
            "extra": build_mc_extra(legs)}
