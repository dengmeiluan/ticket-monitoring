# -*- coding: utf-8 -*-
"""去哪儿 App「低价机票」页解析（纯函数，离线可测）。

页面形态（真机 2026-10-30，北京→上海，点了「搜索低价机票」之后）：

    y=112  10.31   11.01   11.02   11.03   11.04   11.05   ← 日期条（横排）
    y=133  今天    明天    后天    周二    周三    周四
    y=156  ¥410    ¥358    ¥420    ¥410    ¥450    ¥523    ← 每天最低价
    y=322  「直飞低价」区头，下面是当天的航班卡片（07:30→09:45 ¥358 …）

这就是 PC/H5 渠道 `low_fare` 维度要的那份「发现源」：**每天一条最低价**，
不参与明细比价、不带航班号。与 `parse_flight_rows` 的输出严格区分——
两者都读同一页，但低价票只取顶部日期条。
"""
from __future__ import annotations

import re
from typing import List

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
_ATTR_RE = r'%s="([^"]*)"'
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
_PRICE_RE = re.compile(r"^[\u00a5\uffe5]\s*(\d{2,5})$")
_WEEKDAY = ("今天", "明天", "后天", "周一", "周二", "周三", "周四",
            "周五", "周六", "周日")


def _nodes(xml: str):
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        s = m.group(1)
        t = re.search(_ATTR_RE % "text", s)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', s)
        if not b:
            continue
        text = (t.group(1) if t else "").strip()
        if not text:
            continue
        out.append((text, int(b.group(1)), int(b.group(2)),
                    int(b.group(3)), int(b.group(4))))
    return out


def _cy(n):
    return (n[2] + n[4]) // 2


def parse_low_fare_strip(xml: str, year: str = "") -> List[dict]:
    """顶部日期条 → [{date, weekday, price}]，按日期升序。

    只认**同一排**的日期与价格：日期在 `y` 一带、价格在 `y+40` 一带，
    且价格水平对齐日期那一列（x 差 < 80）。页面下方还有航班卡片的
    「起降时刻 + 票价」，那些不该进这里——它们是明细，不是每天最低价。

    价格缺失（未出价/接口没回来）时 price=None，绝不给 0。
    """
    nodes = _nodes(xml)
    dates = []
    for n in nodes:
        m = _DATE_RE.match(n[0])
        if not m:
            continue
        dates.append((n, int(m.group(1)), int(m.group(2))))
    if not dates:
        return []
    # 日期条：同一 y 带内至少 3 个日期，取最上面那一排
    by_y = {}
    for n, mm, dd in dates:
        by_y.setdefault(n[2], []).append((n, mm, dd))
    row_y = min(y for y, items in by_y.items() if len(items) >= 3)
    # 只取这一排（±6px）
    strip = sorted((it for it in dates if abs(it[0][2] - row_y) <= 6),
                   key=lambda it: it[0][1])
    out = []
    for n, mm, dd in strip:
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            continue
        ym = year or ""
        date = ("%s-%02d-%02d" % (ym, mm, dd)) if ym else \
            "%02d-%02d" % (mm, dd)
        price = None
        best_dx = None
        for p in nodes:
            m = _PRICE_RE.match(p[0])
            if not m:
                continue
            if not (n[4] <= p[2] <= n[4] + 60):
                continue
            dx = abs(p[1] - n[1])
            if dx > 80:
                continue
            if best_dx is None or dx < best_dx:
                best_dx, price = dx, int(m.group(1))
        # 星期/相对日：日期正下方那一排（`今天`/`明天`/`周三`），按列对齐。
        # 真机两者的 y1 正好相同（日期 [112,133]、星期 [133,154]），
        # 用严格 `>` 会把它们全排掉。
        wd = ""
        for w in nodes:
            if w[0] not in _WEEKDAY:
                continue
            if not (n[4] - 2 <= w[2] <= n[4] + 60):
                continue
            if abs(w[1] - n[1]) <= 80:
                wd = w[0]
                break
        out.append({"date": date, "mm_dd": "%02d-%02d" % (mm, dd),
                    "weekday": wd, "price": price})
    return out


def is_low_fare_page(xml: str) -> bool:
    """页面是不是「低价机票」结果页。

    判据 = 顶部日期条上有**每天的最低价格**。首页的 7 天条长得一样，
    但每天下面是「查价」按钮而不是价格（未触发查询），所以
    `parse_low_fare_strip` 解析出至少两条有价即认为是结果页。
    """
    priced = [r for r in parse_low_fare_strip(xml) if r["price"]]
    return len(priced) >= 2
