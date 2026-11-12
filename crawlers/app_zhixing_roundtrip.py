# -*- coding: utf-8 -*-
"""智行 App 往返页解析（纯函数，离线可测）。

页面形态（真机 2026-10-31，北京⇄上海，点「往返」→「机票查询」之后）：

    y=124   去程(x≈25)              返程(x≈470)
    y=211   11-21 … 11-27           11-24 … 12-01      ← 每列一条日期带
    y=297   14:00        16:30      21:05        23:20  ← 起降时刻（左列/右列各一）
    y=328   大兴         浦东T2     浦东T1       大兴   ← 机场
    y=373   南航CZ8882   ¥706+      东航MU5185   ¥0     ← 航班号 + 往返总价 / 返程加价
    y=438   11:55        14:10      08:25        10:40
    y=514   吉祥HO1258   ¥736+      吉祥HO1257   ¥26

关键事实：

* **总价只在左列**（去程那侧），形如 `¥ 706 +`；右列的 `¥ 0 / ¥ 26` 是
  「返程需加价」，不是总价——把它当票价会得到 0 元假数据。
* 一屏同时渲染**多个去程 × 多个返程**，页面上的 ¥706 属于哪一对，属于
  哪一行，靠 y 对齐；不能把最便宜的票价随便配一个航班号。
* 「临近推荐」区（y≈579 起）是**火车接驳/多程**的另一套卡片，`¥704 起`
  是单程起价，不是往返总价——必须整段排除。

所以这里的口径是：**一屏只认左列每一行的「往返总价」+ 该行去程航班号**
（返程航班号一并带上，供核对），不拼也不猜没显示出来的组合。
"""
from __future__ import annotations

import re
from typing import List

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
_ATTR_RE = r'%s="([^"]*)"'
_FLIGHT_RE = re.compile(r"([A-Z0-9]{2}\d{3,4})(?![0-9])")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_CURRENCY = ("¥", "￥")
_TOTAL_PLUS_RE = re.compile(r"^\+$")


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
        out.append({"text": text, "x1": int(b.group(1)), "y1": int(b.group(2)),
                    "x2": int(b.group(3)), "y2": int(b.group(4))})
    return out


def _cy(n):
    return (n["y1"] + n["y2"]) // 2


def _is_time(text: str) -> bool:
    m = _TIME_RE.match(text or "")
    return bool(m) and int(m.group(1)) <= 23 and int(m.group(2)) <= 59


def split_columns(xml: str):
    """(左列右边界, 屏宽)——往返页左右两列并排。

    判据优先级（真机 2026-10-31，1600 宽屏）：
      1. 两列各有一个「筛选」：左 x≈393-429、右 x≈838-874，取两者中点；
      2. 「去程 / 返程」标题的中点；
      3. 屏宽一半。

    只拿标题中点不够准：标题自己很窄（去程 25-71、返程 470-516），
    中点算出来约 270，会把左列的价格（x≈375）错判到右列去——解析直接
    返回 0 行（实测）。
    """
    nodes = _nodes(xml)
    width = max((n["x2"] for n in nodes), default=1600)
    filters = sorted((n for n in nodes if n["text"] == "筛选"),
                     key=lambda n: n["x1"])
    if len(filters) >= 2 and filters[0]["x1"] < filters[1]["x1"]:
        return (filters[0]["x2"] + filters[1]["x1"]) // 2, width
    left_title = right_title = None
    for n in nodes:
        if n["text"] == "去程":
            left_title = n
        elif n["text"] == "返程":
            right_title = n
    if left_title and right_title and left_title["x1"] < right_title["x1"]:
        return (left_title["x2"] + right_title["x2"]) // 2, width
    return width // 2, width


def parse_round_trip_rows(xml: str) -> List[dict]:
    """解析往返页 → [{flight_no, return_flight_no, depart_time,
    arrive_time, ret_depart_time, ret_arrive_time, price}]。

    只收**左列、且本行有整串往返总价**的行。价格缺失的行丢弃（不给 0）。
    """
    nodes = _nodes(xml)
    mid, width = split_columns(xml)
    # 「临近推荐」是另一套卡片（火车接驳/多程起价），整段排除
    cutoff = None
    for n in nodes:
        if n["text"] in ("临近推荐", "猜你喜欢", "更多推荐"):
            cutoff = n["y1"]
            break
    body = [n for n in nodes if cutoff is None or n["y1"] < cutoff]

    left = [n for n in body if n["x2"] <= mid]
    right = [n for n in body if n["x1"] >= mid]
    if not left:
        return []

    # 左列每个航班号是一行的锚（真机：`南航CZ8882` 与总价 `¥ 706 +` 同排）
    rows = []
    for n in left:
        m = _FLIGHT_RE.search(n["text"])
        if not m:
            continue
        flight_no = m.group(1)
        cy = _cy(n)
        # 时刻：**同卡片、且在航班号上方**。真机一张卡片纵向分布是
        # 时刻 cy=312 → 机场 cy=339 → 航班号/总价 cy=386，跨度 74px；
        # 下一张卡片的时刻在 +141px 外。窗口取 80 能覆盖本卡全部、又不
        # 越过下一卡（曾用 26 导致时刻全空，用 90 则把下一卡配进来）。
        times = [t for t in left
                 if _is_time(t["text"]) and 0 <= (cy - _cy(t)) <= 80]
        times.sort(key=lambda t: t["x1"])
        dep = times[0]["text"] if times else ""
        arr = times[1]["text"] if len(times) > 1 else ""
        # 总价：同排右侧的 `¥` + 数字（总价只在左列）
        price = None
        best_dy = None
        for i, p in enumerate(left):
            if p["text"] not in _CURRENCY:
                continue
            if not (cy - 40 <= _cy(p) <= cy + 40):
                continue
            for nxt in left[i + 1:i + 4]:
                if not re.fullmatch(r"\d{2,5}", nxt["text"]):
                    continue
                if abs(_cy(nxt) - _cy(p)) > 24:
                    continue
                dy = abs(_cy(p) - cy)
                if best_dy is None or dy < best_dy:
                    best_dy, price = dy, int(nxt["text"])
                break
        if price is None:
            continue
        # 返程字段：只取**与去程同一 cy 带**（±80px）的右列内容。
        # 右列是独立的可滚动列表，屏幕上的第一张返程卡与去程卡并不对应
        # ——把"右列第一个时刻"当返程，会得到 23:20 这种错配值（实测）。
        # 同 y 带取不到就留空：**往返总价与去程航班号已经足够可信**，
        # 返程信息是补充，宁可空着也不给错值。
        ret_no, ret_dep, ret_arr = "", "", ""
        for r in right:
            dy = _cy(r) - cy
            if not (-80 <= dy <= 80):
                continue
            m2 = _FLIGHT_RE.search(r["text"])
            if m2 and not ret_no:
                ret_no = m2.group(1)
        same_band = [t for t in right
                     if _is_time(t["text"]) and abs(_cy(t) - cy) <= 80]
        same_band.sort(key=lambda t: t["x1"])
        if same_band:
            ret_dep = same_band[0]["text"]
            ret_arr = same_band[1]["text"] if len(same_band) > 1 else ""
        rows.append({"flight_no": flight_no, "return_flight_no": ret_no,
                     "depart_time": dep, "arrive_time": arr,
                     "ret_depart_time": ret_dep, "ret_arrive_time": ret_arr,
                     "price": price})
    return rows
