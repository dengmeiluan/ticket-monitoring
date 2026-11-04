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

from core.models import PRICE_MIN

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
_ATTR_RE = r'%s="([^"]*)"'
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
# 不要在字母前用 `\b`：页面文案是「南航CZ8889」「东航MU123」，
# 中文与字母之间**没有**词边界，`\b[A-Z]{2}\d{3,4}\b` 会一个都匹配不到。
#
# 但**纯数字串永远不是航班号**：`11022`（`¥11022` 的价）会被
# `[A-Z0-9]{2}\d{3,4}` 匹配成"11 + 022"（2026-11-04 现场踩到：
# 入库 flight_no='11022'、price=11022，看着像航班其实是个价格）。
# 所以前缀要求**至少一个字母**——`3U8889` / `9C7293` 这类真实航司码仍在。
_FLIGHT_RE = re.compile(r"([A-Z0-9]{1,2}[A-Z][A-Z0-9]?\d{3,4})(?![0-9])")
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


# 中转航线的航班号**不在 text 里**（2026-11-04 现场）：
#
#     |  | flight_search_rn|QunarFlightInterList|FlightsRound_OD617|PVG-KUL
#        |2026-11-16/OD528|KUL-DMK|2026-11-16 |  | 0,481,
#
# text 为空、航班号全在 `content-desc`。而 `_nodes()` 只收有文字的节点，
# 于是中转行整条没有身份 → 入库 `flight_no=''`。
# 这条正则按「FlightsRound_<码>|起降|日期/ <码>|起降|日期」把每一段抠出来。
_FLIGHT_ROUND_RE = re.compile(
    r"FlightsRound_([A-Z0-9]{2}\d{3,4})\|")
_SEG_CODE_RE = re.compile(r"/([A-Z0-9]{2}\d{3,4})\|")


def _desc_flight_marks(xml: str):
    """从 ``content-desc`` 里取中转航班号：``[(code_text, cy)]``。

    直飞时 ``FlightsRound_ZH9516|SHA-BKK|...`` 只有一段；
    中转时 ``FlightsRound_OD617|PVG-KUL|.../OD528|KUL-DMK|...`` 有第二段。
    两段用 ``+`` 连起来（``OD617+OD528``）——可读且不歧义，
    下单程号会让"这到底是哪个航班"含糊。
    """
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        s = m.group(1)
        d = re.search(_ATTR_RE % "content-desc", s)
        if not d:
            continue
        desc = d.group(1) or ""
        if "FlightsRound_" not in desc:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', s)
        if not b:
            continue
        codes = _FLIGHT_ROUND_RE.findall(desc) + _SEG_CODE_RE.findall(desc)
        # 去重但保留顺序（第一段在 findall 里已经先出现）
        seen, uniq = set(), []
        for c in codes:
            if c in seen:
                continue
            seen.add(c)
            uniq.append(c)
        if not uniq:
            continue
        cy = (int(b.group(2)) + int(b.group(4))) // 2
        out.append(("+".join(uniq), cy))
    return out


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
    # 国际列表（QunarFlightInterList）的票价数字带**结构化 desc**：
    # `flight_search_rn|QunarFlightInterList|ItemPrice`，而它与 `¥` 符号
    # 并不相邻——中间隔着「下单可减 / ¥35」（2026-11-01 22:43 现场真实
    # 节点顺序：¥ → 下单可减 → ¥35 → 3305）。按「¥ + 紧邻数字」一条都
    # 取不到，整份国际列表 5 行全 price=None。按 desc 直接取，值域与
    # 国内同一条规则（纯 2–5 位数字），并与已有价格按「值 + 同一行」去重。
    #
    # **text 可能自带 `¥`**（2026-11-04 现场，`QunarFlightInterRoundMixList`）：
    #     | ¥5465 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice
    #     | ¥8418 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice
    # 原来只认纯数字（`\d{2,5}`），带符号的直接被丢掉 → 中转混合列表整页
    # 「有航班行、带价 0 行」。两次现场（09:51 / 10:33 SHA→BKK）都是这个。
    for m in _NODE_RE.finditer(xml or ""):
        seg = m.group(1)
        if "|ItemPrice" not in seg:
            continue
        t = re.search(_ATTR_RE % "text", seg)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', seg)
        if not (t and b):
            continue
        val = (t.group(1) or "").strip()
        # 价格归一走统一实现（`core.price.parse_price`）：剥 `¥`/千分位、
        # 拒遮罩 `4??`、拒 1 位与 6 位。**不要在这里另写一套正则**——
        # 2026-11-04 就是这里只认 `\d{2,5}` 而把六个 `¥5711` 全丢了。
        try:
            from core.price import parse_price
            _v = parse_price(val)
        except Exception:
            _v = None
        if _v is None:
            continue
        if isinstance(_v, float):
            _v = int(round(_v))
        x1, cy = int(b.group(1)), (int(b.group(2)) + int(b.group(4))) // 2
        if any(v == _v and abs(c - cy) <= 4 for v, _x, c in prices):
            continue
        prices.append((_v, x1, cy))

    # 卡片切分：以「左半屏(x1<200)的时刻」为锚，配同排右侧时刻为到达。
    # 实测纵坐标：时刻 y=363/589/746，卡片内航班号在其下 ~73px，
    # 价格在右列，**x1 实测 1490–1563（列表页）/ 772–863（结果页密集版）**，
    # 所以「右列」不能钉死 x>=1200——那样密集版一个价格都取不到
    # （真机踩过：解析出航班行但 price 全 None → no-priced-rows）。
    # 判据改为「在卡片右侧半屏」(x1 > 屏宽一半)。
    _screen_w = max((n[3] for n in nodes), default=900)
    _right = _screen_w // 2
    anchors = sorted((t for t in times if t[1] < 200), key=lambda n: n[2])
    # 中转行航班号的来源（见 `_desc_flight_marks` 的现场说明）
    desc_marks = _desc_flight_marks(xml)
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
        if not code:
            # 中转行的航班号只在 content-desc 里（text 为空被 `_nodes` 过滤），
            # 取卡片纵向范围内最靠上的那条。不补这步，入库 flight_no 为空，
            # 下游就看不出"这天最低价是哪一班"（2026-11-04 实测）。
            _dcand = [x for x in desc_marks
                      if card_top - 10 <= x[1] < card_bottom]
            if _dcand:
                code = min(_dcand, key=lambda x: x[1])[0]
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
        # 低于价格带下限的「价格」不是票价（实测优惠卡会把 ¥20/¥25 列在
        # 同一纵向范围）。无航班身份且无有效票价才整行跳过；有航班号但
        # 价格越界的行保留身份、price=None，绝不落 ¥20 假票价。
        # 2026-11-03 生产日志与 flight_prices 实证。
        _cheap = price is not None and price < PRICE_MIN
        if _cheap:
            price = None
        if not code and _cheap:
            continue
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
