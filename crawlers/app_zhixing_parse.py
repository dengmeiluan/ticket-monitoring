# -*- coding: utf-8 -*-
"""智行 App 的 UI dump 解析（纯函数，可离线测）。

真实结构（2026-10-29 dump，见 tests/fixtures/zhixing_list_dump.xml）：

  日历条：日期 / 星期 / 价格 三个兄弟节点同一行
    '10-29'  [22,118][67,141]
    '今天'    [70,118][104,141]
    '¥450'   [39,142][86,164]

  航班行：时刻 / 机场 / 航班号 / 价格分列，价格未登录时被拆成
    '￥'     [793,426][806,449]     ← 货币符号单独一个节点
    '4??'    [806,413][865,451]     ← 数字被遮罩

所以价格解析必须同时处理「¥450 整串」与「￥ + 4?? 分离」两种形态，
且**绝不能**把 `4??` 当成 4 元或 0 元——那是把"看不到"伪装成"很便宜"。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# 节点解析分两步：先取整个 <node ...> 标签，再分别抽属性。
# **不要用一个正则同时抓 text/resource-id/bounds**——惰性量词下
# 中间那个可选分组会永远匹配空（实测踩过：rid 恒为 None，
# 日历价整片丢成 None 却不报错）。
_TAG_RE = re.compile(r"<node\b[^>]*>")
_ATTR_CACHE = {}


def _attr(tag: str, name: str) -> str:
    key = (name,)
    pat = _ATTR_CACHE.get(key)
    if pat is None:
        pat = re.compile(name + r'="([^"]*)"')
        _ATTR_CACHE[key] = pat
    m = pat.search(tag)
    return m.group(1) if m else ""


_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

# 日历格子的稳定 id（实测）：date-item-3 / date-item-3-date-text /
# date-item-3-price-text。**按 id 配对优先于按坐标配对**——坐标会随
# 分辨率/字体缩放漂移，id 是 App 自己的结构约定。
_ITEM_ID_RE = re.compile(r"^date-item-(\d+)(?:-(date|day|price)-text)?$")

_DATE_RE = re.compile(r"^(\d{2})-(\d{2})$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_FLIGHT_RE = re.compile(r"\b([A-Z]{2}\d{3,4})\b")
# 货币符号有全角/半角两种写法，dump 里都出现过，必须都认
_CURRENCY = "\u00a5\uffe5"
# 整串价：¥450 / ￥450 / ¥ 450
_PRICE_FULL_RE = re.compile(r"^[" + _CURRENCY + r"]\s*(\d{2,5})$")
# 遮罩价：4?? / 3??
_PRICE_MASK_RE = re.compile(r"^\d[?？]{1,3}$")
# 单独的货币符号（遮罩价的前半截 / 拆开价格的前半截）
_CURRENCY_ONLY = tuple(_CURRENCY)
# 拆开的价格后半截：纯数字
_DIGITS_RE = re.compile(r"^\d{2,5}$")

_EMPTY_MARKS = ("没有找到符合条件的航班", "查不到相关航班",
                "暂无符合条件的航班", "没有符合条件")
_LOGIN_MARKS = ("立即登录", "登录解锁更低价", "手机号登录", "验证码登录")


class Node:
    __slots__ = ("text", "rid", "x1", "y1", "x2", "y2")

    def __init__(self, text: str, rid: str, x1: int, y1: int,
                 x2: int, y2: int):
        self.text = text
        self.rid = rid
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2

    def __repr__(self):
        return f"Node({self.text!r}, {self.rid!r}, {self.x1},{self.y1})"


def _nodes(xml: str) -> List[Node]:
    out = []
    for m in _TAG_RE.finditer(xml or ""):
        tag = m.group(0)
        text = _attr(tag, "text").strip()
        if not text:
            continue
        b = _BOUNDS_RE.search(tag)
        if not b:
            continue
        out.append(Node(text, _attr(tag, "resource-id").strip(),
                        int(b.group(1)), int(b.group(2)),
                        int(b.group(3)), int(b.group(4))))
    return out


def _parse_calendar_by_id(nodes: List[Node]) -> List[dict]:
    """按 date-item-N-* 的 resource-id 配对日期与价格。

    这是首选路径：id 是 App 自己的结构约定，比坐标稳。同一个 N 下
    date-text 给日期、price-text 给价格；缺 price 的格子按"该日无价"
    处理（不是 0）。
    """
    groups: Dict[str, dict] = {}
    for n in nodes:
        m = _ITEM_ID_RE.match(n.rid or "")
        if not m:
            continue
        idx, kind = m.group(1), m.group(2) or "root"
        g = groups.setdefault(idx, {})
        g[kind] = n
    if not groups:
        return []

    out = []
    for idx in sorted(groups, key=lambda k: int(k)):
        g = groups[idx]
        date_node = g.get("date")
        if date_node is None:
            continue
        date_text = date_node.text
        if not _DATE_RE.match(date_text):
            continue
        price_node = g.get("price")
        price, masked = None, False
        if price_node is not None:
            pm = _PRICE_FULL_RE.match(price_node.text)
            if pm:
                price = int(pm.group(1))
            elif _PRICE_MASK_RE.match(price_node.text):
                masked = True
            elif price_node.text in _CURRENCY_ONLY:
                # 「¥」单独一格，数字在相邻节点 —— 交给坐标兜底路径
                price = None
        out.append({"date": date_text, "price": price, "masked": masked})
    return sorted(out, key=lambda r: r["date"])


def _same_row(a: Node, b: Node, tol: int = 14) -> bool:
    """同一视觉行：中心 y 差在容差内（dump 里同一行会差几像素）。"""
    return abs(a.cy - b.cy) <= tol


def _same_column_group(a: Node, b: Node, tol: int = 34) -> bool:
    """同一天列内的上下叠放：日期在上、价格在下。

    实测：'10-29' cy=129，'¥450' cy=153，相差 24px——比"同一行"的
    容差大，所以不能用 _same_row 判定；但它们在水平方向几乎左对齐
    （x1 22 vs 39）。日历格子正是这种「上日期下价格」的竖排。
    """
    return abs(a.cy - b.cy) <= tol and abs(a.x1 - b.x1) <= 30


def parse_calendar(xml: str) -> List[dict]:
    """解析顶部日历条：返回 [{date, price, masked}]，缺价日 price=None。

    date 保持 MM-DD（App 上就是 MM-DD，年份由调用方按查询日期补）。

    两条路径：
      1. **resource-id 配对**（首选）——App 自己的结构约定，最稳；
      2. **坐标配对**（兜底）——某些版本/页面没有 id 时才用。实测
         '10-29' cy=129 与 '¥450' cy=153 差 24px，是"上日期下价格"的
         竖排格子，不是同一行，所以兜底不能用行容差。
    """
    nodes = _nodes(xml)
    by_id = _parse_calendar_by_id(nodes)
    if by_id:
        return by_id

    prices = []
    for n in nodes:
        m = _PRICE_FULL_RE.match(n.text)
        if m:
            prices.append((n, int(m.group(1))))
            continue
        if _PRICE_MASK_RE.match(n.text):
            prices.append((n, None))

    out: Dict[str, dict] = {}
    for n in nodes:
        m = _DATE_RE.match(n.text)
        if not m:
            continue
        # 找同一天格子内、水平方向最接近的价格节点（日期在上、价格在下）
        best = None
        for pnode, value in prices:
            if not _same_column_group(n, pnode):
                continue
            dx = abs(pnode.x1 - n.x1)
            if best is None or dx < best[0]:
                best = (dx, pnode, value)
        if best is None:
            out.setdefault(n.text, {"date": n.text, "price": None,
                                    "masked": False})
            continue
        _, pnode, value = best
        prev = out.get(n.text)
        # 同一天出现多次时，取有价的那个
        if prev and prev["price"] is not None and value is None:
            continue
        out[n.text] = {"date": n.text, "price": value,
                       "masked": value is None and _PRICE_MASK_RE.match(
                           pnode.text) is not None}
    return sorted(out.values(), key=lambda r: r["date"])


def _time_pairs(nodes: List[Node]) -> List[dict]:
    """把「同一排、左起右降」的时刻对识别成一趟航班。

    为什么不能以航班号为锚：**国际列表页根本没有航班号**（真机实测：
    浦东→成田/羽田一页 6 张卡片，只有航司名与时刻），以航班号为锚会
    判出 0 行，而 `detect_state` 同样按航班号判「有数据」，整页落到
    unknown，明细路径一直轮询到超时——日历价照出，明细永远为空。
    时刻对是两种版式都有的唯一稳定结构，所以锚定它；航班号变成可选
    的补充信息（同一排、左侧、命中 XX#### 才挂上）。

    同一排的判据用 `_same_row`（容差 14）：真机时刻节点 y 完全一致，
    而相邻卡片的到达列水平只差几像素，**不能用水平距离代替排**。
    """
    times = [n for n in nodes if _TIME_RE.match(n.text)]
    out: List[dict] = []
    used = set()
    for i, dep in enumerate(times):
        if i in used:
            continue
        arr_node, arr_i = None, None
        for j, cand in enumerate(times):
            if j == i or j in used:
                continue
            if cand.x1 <= dep.x1:
                continue
            if not _same_row(dep, cand):
                continue
            arr_node, arr_i = cand, j
            break
        if arr_node is None:
            continue
        used.add(i)
        used.add(arr_i)
        out.append({"dep": dep, "arr": arr_node})
    return out


def _airline_near(nodes: List[Node], dep: Node, arr: Node,
                  flight_no: str = "") -> str:
    """卡片里的航司名；取不到就返回空串（绝不拿标签/机场名凑数）。

    最可靠的锚是**航班号那一排**：真机国内卡片里「东航 MU5138」同排、
    左右相邻；国际卡片没有航班号，才退回「机场行之下的独占中文名」。

    为什么不能只看位置：同一纵向窗口里还挤着排序栏（「比价」「时间」
    「价格低-高」）、区头（「中转低价」「推荐·近期热销」「优选航班」）、
    机场行（「大兴」「浦东T2」）。按"第一个中文名"取，实测取到过
    「比价」「大兴」「优选航班」——全不是航司。
    """
    banned = ("机场", "出发", "到达", "补贴", "优惠", "全程", "剩", "北京时间",
              "时间", "总时长", "当地时间", "含税价", "筛选", "查看", "低价",
              "推荐", "往返", "中转", "比价", "直飞", "航司", "更多",
              "快线", "特惠", "保障", "解锁", "航班", "热销", "宠物", "友好",
              "学生", "专享", "新客", "补贴价")
    if flight_no:
        code_node = None
        for n in nodes:
            if flight_no in n.text:
                code_node = n
                break
        if code_node is not None:
            # 同排（容差 14）、左侧、纯中文 → 航司名
            best = None
            for n in nodes:
                if not (2 <= len(n.text) <= 8):
                    continue
                if not all("\u4e00" <= c <= "\u9fff" for c in n.text):
                    continue
                if any(b in n.text for b in banned):
                    continue
                if abs(n.cy - code_node.cy) > 14:
                    continue
                if n.x1 >= code_node.x1:
                    continue
                if best is None or n.x1 > best.x1:
                    best = n
            if best is not None:
                return best.text
    # 国际卡片：机场行之后再找航司名。机场行是「与起降时刻紧贴的那一排」，
    # 但真机航站楼名带字母数字（「浦东T2」「羽田T3」），不能按"纯中文"
    # 筛——那样只会匹配到右侧的「补贴后价」，把航司名整排吞掉。
    # 位置一律相对**起飞行的 y1**：机场行与时刻行的包围盒是重叠的
    # （时刻 [471,509]、机场 [507,532]），拿 dep.y2 做基准会算出 -2。
    airport_cy = None
    for n in nodes:
        dy = n.y1 - dep.y1
        if not (20 <= dy <= 70):
            continue
        if n.x1 > arr.x1 + 60:      # 右半屏是「补贴后价」等标签
            continue
        if any(b in n.text for b in banned):
            continue
        if len([c for c in n.text if "\u4e00" <= c <= "\u9fff"]) < 2:
            continue
        airport_cy = n.cy if airport_cy is None else min(airport_cy, n.cy)
    cands = []
    for n in nodes:
        if not (2 <= len(n.text) <= 8):
            continue
        cn = [c for c in n.text if "\u4e00" <= c <= "\u9fff"]
        # 国际航司名可能带「日本」「航空」（纯中文），国内可能带「航」；
        # 机场/航站楼名的中文部分不足 2 字（「T2」）时同样在这里过。
        if len(cn) < 2 or len(cn) != len(n.text):
            continue
        if any(b in n.text for b in banned):
            continue
        if n.text == "等":          # 「香港航空」右侧的独立「等」字节点
            continue
        if airport_cy is not None and n.cy <= airport_cy:
            continue
        dy = n.y1 - dep.y1
        if not (0 <= dy <= 160):
            continue
        cands.append(n)
    if not cands:
        return ""
    cands.sort(key=lambda n: n.y1)
    return cands[0].text
    if not cands:
        return ""
    cands.sort(key=lambda n: n.y1)
    return cands[0].text


# 「全程23h40m」= 这趟的总时长；「青岛 20h35m」= 经停城市 + 停留时长。
# 中转卡片靠后者识别：没有它，中转会被当成直飞进最优池（r682 实测）。
_TRANS_RE = re.compile(r"^([\u4e00-\u9fff]{2,6})\s+(\d{1,2}h\d{1,2}m|\d{1,3}分钟)$")
_TOTAL_DUR_RE = re.compile(r"^全程\s*(\d{1,2}h\d{1,2}m)$")


def _transfer_near(nodes: List[Node], dep: Node, arr: Node) -> str:
    """卡片里的经停城市；直飞返回空串。

    只看这一张卡片（起降时刻之间那一块 + 下方 100px 内），否则会把
    上一张/下一张中转卡的经停城市张冠李戴。
    """
    lo, hi = dep.cy - 40, dep.cy + 160
    for n in nodes:
        if not (lo <= n.cy <= hi):
            continue
        if n.x1 <= dep.x1:
            continue
        m = _TRANS_RE.match(n.text or "")
        if m:
            return m.group(1)
    return ""


def parse_flight_rows(xml: str) -> List[dict]:
    """解析航班行：以「起飞→到达同一排」为锚，向右取价格。

    返回 [{flight_no, airline, depart_time, arrive_time, price, masked}]；
    价格被遮罩时 price=None, masked=True（绝不给 0）；无航班号的版式
    （国际页）flight_no 为空串，绝不编造。

    列表页的价格是**两个独立节点**：`￥`（x1=793）紧跟 `270`（x1=806），
    并不像首页条那样整串 `¥256`。只看整串会把整页判成「有航班无价格」，
    进而被当成 `ok` 但有 0 行报价——明细整片作废（实测 11-05 踩过）。
    """
    nodes = _nodes(xml)
    price_nodes = []
    # 国际版式的价格节点是**裸数字**（988 / 1068），前面那个 ￥ 只是
    # 装饰；国内版式才是「￥ + 数字」两截。先按坐标把每个 `￥` 与它
    # 右边的数字配成一对，配上的数字不再单独算——否则同一格价会出现
    # 两次，且裸数字那条会落空（`988` 被当成了 `￥` 的后半截）。
    currency_used = set()
    for i, n in enumerate(nodes):
        if n.text in _CURRENCY_ONLY:
            for j in range(i + 1, min(i + 5, len(nodes))):
                nxt = nodes[j]
                if not _DIGITS_RE.match(nxt.text) or not _same_row(n, nxt):
                    continue
                if not (0 <= nxt.x1 - n.x1 <= 60):
                    continue
                price_nodes.append((nxt, int(nxt.text), False))
                currency_used.add(j)
                break
            else:
                # 后面紧跟 4?? 即遮罩价（遮罩价节点可能在 ￥ 左或右，
                # 真机国内页是 `4??`(x1=806) 在 `￥`(x1=793) 右侧同排）
                for nxt in nodes[i + 1:i + 5]:
                    if _PRICE_MASK_RE.match(nxt.text) and _same_row(n, nxt):
                        price_nodes.append((nxt, None, True))
                        break
            continue
        m = _PRICE_FULL_RE.match(n.text)
        if m:
            price_nodes.append((n, int(m.group(1)), False))
    # 没被任何 ￥ 认领的裸数字 / 遮罩价同样算价格候选（国际版式）。
    for i, n in enumerate(nodes):
        if i in currency_used:
            continue
        if _DIGITS_RE.match(n.text) and len(n.text) >= 3:
            price_nodes.append((n, int(n.text), False))
        elif _PRICE_MASK_RE.match(n.text):
            price_nodes.append((n, None, True))

    rows = []
    for pair in _time_pairs(nodes):
        dep, arr = pair["dep"], pair["arr"]
        # 航班号：与国际版式无关的可选信息。国内卡片里它在**时刻行下方
        # 约 68px**（航司名旁边），不在同一排；国际卡片没有。按「本卡片
        # 纵向范围内、起飞时刻右侧或下方」取，取不到就留空，绝不编。
        flight_no = ""
        for cand in nodes:
            dy = cand.cy - dep.cy
            if not (-20 <= dy <= 130):
                continue
            m = _FLIGHT_RE.search(cand.text)
            if m:
                flight_no = m.group(1)
                break
        # 价格：本卡片纵向范围内的价格节点，取**最靠右**的那个。
        # 不能按「在到达时刻右边」判：真机国内卡片的遮罩价 `4??`
        # 节点在 `￥` 左边（dump 文档序也反着），x1 甚至可能小于
        # 到达时刻；价格列本来就在整卡最右侧，用「最靠右」比坐标
        # 相对位置稳。纵向窗口：起飞行 ~ 下一张卡片之前（±40..120）。
        price, masked = None, False
        best_x = None
        for pnode, value, is_mask in price_nodes:
            dy = pnode.cy - dep.cy
            if dy < -40 or dy > 120:
                continue
            if best_x is None or pnode.x1 > best_x:
                best_x, price, masked = pnode.x1, value, is_mask
        rows.append({"flight_no": flight_no,
                     "airline": _airline_near(nodes, dep, arr, flight_no),
                     "trans_city": _transfer_near(nodes, dep, arr),
                     "depart_time": dep.text,
                     "arrive_time": arr.text,
                     "price": price, "masked": masked})
    return rows


def detect_state(xml: str) -> str:
    """页面状态：login / empty / ok / calendar / unknown。

    判据顺序（实测教训）：
      * **先判有数据**：未登录时页面顶部本来就有"登录解锁更低价"横幅，
        但列表照样渲染。若先判 login，会把"有数据但没登录"错误地当成
        "需要登录"，白白丢掉可用的日历价。
      * 再判空态：只有明确的"没有找到航班"文案才是 empty。
      * 最后才是 login：既无航班也没空态文案、但有登录墙，才归 login。

    「选择日期」日历弹层是**另一种有数据**的页面：它没有航班号，
    但有 flight_calendar_date_cell-* 的日期格子。不认它就会被判
    unknown，长窗口日历整片作废（实测踩过）。
    """
    if not xml or "<hierarchy" not in xml:
        return "unknown"
    if "flight_calendar_date_cell-" in xml:
        return "calendar"
    texts = [n.text for n in _nodes(xml)]
    joined = " ".join(texts)
    if any(_FLIGHT_RE.search(t) for t in texts):
        return "ok"
    # 国际列表页**没有航班号**：只有「起飞时刻→到达时刻」成对出现。
    # 不认它 → 判 unknown → 明细路径轮询到超时，日历价照出而明细永远空。
    # 同时首页日期条只有整串价（¥910），没有时刻对，不会被误判成 ok。
    if _time_pairs(_nodes(xml)):
        return "ok"
    if any(mark in joined for mark in _EMPTY_MARKS):
        return "empty"
    if any(mark in joined for mark in _LOGIN_MARKS):
        return "login"
    return "unknown"
