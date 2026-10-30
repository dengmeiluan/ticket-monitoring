# -*- coding: utf-8 -*-
"""去哪儿 App 列表页解析（真机 dump 实测形态，2026-10-30）。

页面是 React Native 渲染，没有稳定 resource-id，只能按**几何 + 文案**取：

    y=746  21:35        23:40          ← 起降时刻（左右各一，同一行）
    y=780  北京大兴      虹桥T2          ← 机场
    y=818  东航MU123  实际乘坐 上航FM9102  ← 承运航班号（可能带共享号）
    y=739  ¥ 377                       ← 价格（¥ 与数字两个节点，右列）
    y=661  经济舱1.8折                  ← 舱位

关键陷阱（都在实测数据里踩过）：
  * 价格右列可能还有「已减 ¥70」优惠标签，**不能**把它当成票价；
    票价是没有「已减」前缀的那个。
  * 航班号可能带「含共享」「实际乘坐」后缀词，要取真正的 `[A-Z]{2}\\d{3,4}`。
  * 卡片是按 y 分段的，不能按文档顺序贪心配。
"""
from __future__ import annotations

import re
from typing import List

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
_ATTR_RE = r'%s="([^"]*)"'
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
# 不要在字母前用 `\b`：页面文案是「南航CZ8889」「东航MU123」，
# 中文与字母之间**没有**词边界，`\b[A-Z]{2}\d{3,4}\b` 会一个都匹配不到。
_FLIGHT_RE = re.compile(r"([A-Z]{2}\d{3,4})(?![0-9])")
_CURRENCY = ("¥", "￥")


def _nodes(xml: str):
    """[(text, x1, y1, x2, y2)]，只保留有文字的节点。"""
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


def _is_time(t):
    m = _TIME_RE.match(t or "")
    if not m:
        return False
    return int(m.group(1)) <= 23 and int(m.group(2)) <= 59


def parse_flight_rows(xml: str) -> List[dict]:
    """返回 [{flight_no, depart_time, arrive_time, price, masked}]。

    以**起降时刻行**为锚（每张卡片必有一对），向下找航班号、向右找价格。
    拿不到航班的卡片跳过；价格缺失时 price=None（绝不给 0）。
    """
    nodes = _nodes(xml)
    times = [n for n in nodes if _is_time(n[0])]
    prices = []       # (value, x1, cy)
    for i, n in enumerate(nodes):
        if n[0] not in _CURRENCY:
            continue
        for nxt in nodes[i + 1:i + 4]:
            if not re.fullmatch(r"\d{2,5}", nxt[0]):
                continue
            if abs(_cy(nxt) - _cy(n)) > 30:
                continue
            # 「已减 ¥70」是优惠标签不是票价：它紧贴在**票价右侧**连排
            # （实测与票价同一行，x 从 1560 起）；票价在右列但更靠左。
            is_discount = any(
                o[0] == "已减" and abs(_cy(o) - _cy(n)) <= 40
                and -20 <= n[1] - o[3] <= 200 for o in nodes)
            if not is_discount:
                prices.append((int(nxt[0]), n[1], _cy(nxt)))
            break

    # 卡片切分：以「左半屏(x1<200)的时刻」为锚，配同排右侧时刻为到达。
    # 实测纵坐标：时刻 y=363/589/746，卡片内航班号在其下 ~73px，
    # 价格在右列，**x1 实测 1490–1563（列表页）/ 772–863（结果页密集版）**，
    # 所以「右列」不能钉死 x>=1200——那样密集版一个价格都取不到
    # （真机踩过：解析出航班行但 price 全 None → no-priced-rows）。
    # 判据改为「在卡片右侧半屏」(x1 > 屏宽一半)。
    _screen_w = max((n[3] for n in nodes), default=900)
    _right = _screen_w // 2
    anchors = sorted((t for t in times if t[1] < 200), key=lambda n: n[2])
    rows = []
    used = set()
    for i, t in enumerate(anchors):
        partner = None
        for o in times:
            if o[1] <= t[1] or abs(_cy(o) - _cy(t)) > 24:
                continue
            partner = o
            break
        if partner is None:
            continue
        card_top = t[2]
        # 卡片下界 = 下一张卡片的时刻行（没有下一张就按 260px 估）
        card_bottom = (anchors[i + 1][2] if i + 1 < len(anchors)
                       else card_top + 260)
        # 航班号：卡片内（时刻行下方、下一卡片之前）第一个航班号
        code = ""
        cands = [o for o in nodes
                 if card_top <= o[2] < card_bottom and _FLIGHT_RE.search(o[0])]
        if cands:
            code = _FLIGHT_RE.search(min(cands, key=lambda o: o[2])[0]).group(1)
        # 价格：右侧半屏、落在卡片纵向范围内最靠上的那个（优惠标签已剔除）
        price, best = None, None
        for k, (val, x1, cy) in enumerate(prices):
            if k in used or x1 < _right:
                continue
            if not (card_top - 40 <= cy < card_bottom - 20):
                continue
            if best is None or cy < prices[best][2]:
                best = k
        if best is not None:
            price = prices[best][0]
            used.add(best)
        # 中转标记必须带出来：卡片里有「全程12时45分 / 停9时45分」这种
        # 两段时长，说明不是直飞。不带 transCity，下游会把中转当直飞塞进
        # 直飞最优池，行头价也会被中转低价顶掉（真机：￥420 的中转把
        # ￥455 的直飞压成行头）。
        trans = ""
        for o in nodes:
            if not (card_top - 20 <= o[2] < card_bottom):
                continue
            if o[0].startswith("停") and "时" in o[0]:
                trans = "中转"
                break
        rows.append({"flight_no": code, "depart_time": t[0],
                     "arrive_time": partner[0], "price": price,
                     "trans_city": trans, "masked": False})
    return rows


def detect_state(xml: str) -> str:
    """页面状态：login / empty / ok / unknown。

    列表页判据：**出现起降时刻对**才算 ok（航司字样不足以说明有票）。
    """
    if not xml or "<hierarchy" not in xml:
        return "unknown"
    if "请输入手机号" in xml or "获取验证码" in xml:
        return "login"
    nodes = _nodes(xml)
    times = [n for n in nodes if _is_time(n[0])]
    if len(times) >= 2:
        return "ok"
    if any(w in xml for w in ("没有找到", "暂无航班", "无直达航班")):
        return "empty"
    return "unknown"
