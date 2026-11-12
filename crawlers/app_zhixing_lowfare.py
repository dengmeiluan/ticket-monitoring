# -*- coding: utf-8 -*-
"""智行 App「特价」页解析：按日期逐天一条最低价（low_fare 发现源）。

真机实测（2026-10-31，海口→上海）结果页结构：

    02.16  周二        ¥ 1646
    02.15  周一        ¥ 1646
    02.14  周日        ¥ 1646

左侧「MM.DD」+ 星期，右侧「¥」与数字两个节点，同一 `cy`。

**这里曾经被记成"目的地低价榜、口径对不上"**——那是把首页「省钱攻略」
里按目的地报价的推荐卡当成了「特价」档。实际点开「特价」页签后，
该 page 是标准的「一条航线 × 逐天报价」，与 low_fare 契约一致。

判据要点（真机踩过）：
  * 页面里同时有「近期成交价¥462」这种历史参考价，不是当天报价，
    必须靠**同一排必须有日期**来锚定，绝不能把所有 ¥ 数字都当报价；
  * `02.16` 只有月日，没有年份——年份由调用方给的锚点日推（见 `to_ymd`）；
  * 价格节点是 `¥` 与数字分开两截（与列表页同款），也要认整串 `¥1646`。
"""
from __future__ import annotations

import re
from typing import List, Optional

from .app_zhixing_parse import _nodes, _same_row, _CURRENCY, _PRICE_FULL_RE

# 02.16 / 2.16（App 不补零月份的情况也要认）
_MD_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_DIGITS_RE = re.compile(r"^\d{2,5}$")

# 页面上还有「近期成交价¥462」这类**历史参考价**：它整串带前缀文案，
# 既不是单独的 `¥` 节点、也过不了 `^¥数字$` 的整串匹配，所以不会被
# 当成报价。真正防串行的是「必须与日期同一排」——见下方的 same_row。


def parse_low_fare_rows(xml: str) -> List[dict]:
    """返回 [{md, weekday, price}]，只含有日期且同一排有价的行。

    `md` 是页面上原样的「MM.DD」；价格解析不出就是 None（绝不给 0）。
    """
    if not xml or "<hierarchy" not in xml:
        return []
    nodes = _nodes(xml)

    prices = []          # [(value, node)]
    used = set()
    for i, n in enumerate(nodes):
        if n.text in _CURRENCY:
            for j in range(i + 1, min(i + 5, len(nodes))):
                nxt = nodes[j]
                if j in used or not _DIGITS_RE.match(nxt.text):
                    continue
                if not _same_row(n, nxt):
                    continue
                prices.append((int(nxt.text), nxt))
                used.add(j)
                break
        else:
            m = _PRICE_FULL_RE.match(n.text)
            if m:
                prices.append((int(m.group(1)), n))

    out: List[dict] = []
    seen = set()
    for n in nodes:
        m = _MD_RE.match(n.text)
        if not m:
            continue
        if n.text in seen:
            continue
        # 星期必须在同一排（结构校验：只有日期列表才这样成对出现）
        wd = ""
        for c in nodes:
            if c.text in _WEEKDAYS and _same_row(n, c) and c.x1 > n.x1:
                wd = c.text
                break
        price = None
        best_x = None
        for val, pn in prices:
            if not _same_row(n, pn):
                continue
            if pn.x1 <= n.x1:
                continue
            # 取**本行最靠右**的价：价格列在整页最右侧，左边的
            # 「已减 ¥75」之类是优惠标签，不是票价（真机构型）。
            if best_x is None or pn.x1 > best_x:
                best_x, price = pn.x1, val
        if price is None:
            continue
        seen.add(n.text)
        out.append({"md": n.text, "weekday": wd, "price": price})
    out.sort(key=lambda r: r["md"])
    return out


def to_ymd(md: str, anchor_ymd: str) -> str:
    """「MM.DD」→「YYYY-MM-DD」，年份按锚点日就近推断。

    特价页不显示年份。跨年时（锚点 12 月、票面 01 月）必须进到下一年，
    否则会把明年正月的价记到今年（反向同理）。
    """
    m = _MD_RE.match((md or "").strip())
    if not m or len(anchor_ymd) < 10:
        return ""
    mm, dd = int(m.group(1)), int(m.group(2))
    try:
        ay, am, ad = (int(anchor_ymd[0:4]), int(anchor_ymd[5:7]),
                      int(anchor_ymd[8:10]))
    except ValueError:
        return ""
    year = ay
    # 与锚点相差超过半年就按跨年处理（12 月看到 01 月 → 次年）
    if mm - am > 6:
        year = ay - 1
    elif am - mm > 6:
        year = ay + 1
    try:
        return "%04d-%02d-%02d" % (year, mm, dd)
    except Exception:
        return ""


def is_low_fare_page(xml: str) -> bool:
    """真机判据：有「搜索特价」或结果页的「出发日期」+「重新选择」。

    两个都认，是因为入口页与结果页文案不同：入口是「搜索特价」按钮，
    结果页是日期区间 + 「重新选择」。只看入口会在结果页判成 unknown。
    """
    x = xml or ""
    return ("搜索特价" in x) or ("重新选择" in x and "出发日期" in x)


def find_entry(xml: str):
    """首页/入口页上的「特价」页签节点（点击进入特价档）。"""
    for n in _nodes(xml):
        if n.text == "特价":
            return n
    return None


# 特价页自己写出的「航线」与「日期带」：用来确认页面当前选择是否就是
# 请求的那条。App 的页面会保留上次会话的选择，只读报价而不核对，就会把
# 上海-新加坡 2/14-16 的价格当成 上海-北京 11/10-12 的结果。
_ROUTE_RE = re.compile(r"([\u4e00-\u9fa5]{2,8})-([\u4e00-\u9fa5]{2,8})")
_BAND_RE = re.compile(
    r"(\d{1,2})月(\d{1,2})日\s*[-–—]\s*(\d{1,2})月(\d{1,2})日")


def page_selection(xml: str):
    """返回 (route, band)：route=(出发,到达)，band=(月,日,月,日)；缺失为 None。"""
    route = None
    for m in _ROUTE_RE.finditer(xml or ""):
        route = (m.group(1), m.group(2))
        break
    if route is None:
        # 表单页不写「A-B」：出发/到达是上下两行。顶部那句
        # 「海口到上海的机票」是**上一次的搜索历史**，不能拿来校验。
        rows = form_city_rows(xml)
        if len(rows) >= 2:
            route = (rows[0].text, rows[1].text)
    band = None
    m = _BAND_RE.search(xml or "")
    if m:
        band = tuple(int(g) for g in m.groups())
    return route, band


def selection_covers(xml: str, from_name: str, to_name: str, start, end):
    """页面当前选择是否**覆盖**请求的航线与日期带，返回 (ok, why)。"""
    route, band = page_selection(xml)
    if not route or not band:
        return False, ("特价页没有写出航线/日期带，无法确认是请求的 %s-%s"
                       % (from_name, to_name))
    if route != (from_name, to_name):
        return False, ("特价页当前是 %s-%s，不是请求的 %s-%s"
                       % (route[0], route[1], from_name, to_name))

    def k(m, d):
        return int(m) * 100 + int(d)

    if not (k(band[0], band[1]) <= k(start.month, start.day)
            and k(end.month, end.day) <= k(band[2], band[3])):
        return False, ("特价页日期带 %d月%d日-%d月%d日 不覆盖请求 %d月%d日-%d月%d日"
                       % (band[0], band[1], band[2], band[3],
                          start.month, start.day, end.month, end.day))
    return True, ""


def selection_within(xml: str, from_name: str, to_name: str, start, end):
    """核对请求窗口：允许**首日不可售**（带起点晚于 start）。

    特价 App 不渲染不可售日期（真机：2026-11-02 当天没有 `11-02` 格子，
    最早可售是 11-03）。这种「少一天」不是错配，不能像旧页面那样整条
    记空；但带**终点**必须覆盖到请求末日，否则说明日期没设上。
    返回 (ok, 实际起点(月,日) 或 None, why)。
    """
    route, band = page_selection(xml)
    if not route or not band:
        return False, None, ("特价页没有写出航线/日期带，无法确认是请求的 %s-%s"
                             % (from_name, to_name))
    if route != (from_name, to_name):
        return False, None, ("特价页当前是 %s-%s，不是请求的 %s-%s"
                             % (route[0], route[1], from_name, to_name))

    def k(m, d):
        return int(m) * 100 + int(d)

    if k(band[0], band[1]) < k(start.month, start.day):
        return False, None, ("日期带起点 %d月%d日 早于请求 %d月%d日"
                             % (band[0], band[1], start.month, start.day))
    if k(band[2], band[3]) < k(end.month, end.day):
        return False, None, ("日期带没有覆盖到请求末日 %d月%d日"
                             % (end.month, end.day))
    return True, (band[0], band[1]), ""


# ---------- 表单控件（把「只读页面选择」升级成按请求驱动） ----------
#
# 真机（2026-11-02）结构，特价表单与单程首页**不是同一套控件**：
#   * 出发/到达是上下两行（不是左右两端），到达支持多选，文案是
#     「新加坡，广州」这种「，」拼接；
#   * 页面顶部标题「海口到上海的机票」是上一次的搜索历史，**不是**
#     当前表单选择——按它校验会永远对不上；
#   * 日期是区间 `M月D日 - M月D日`，点开是「选择日期」长日历
#     （默认停在当前选择那个月，更早的月份要向下翻）。
_CITY_ROW_RE = re.compile(
    r"^[\u4e00-\u9fa5]{2,8}(?:，[\u4e00-\u9fa5]{2,8})*$")
_BAND_TEXT_RE = re.compile(
    r"^\d{1,2}月\d{1,2}日\s*[-–—]\s*\d{1,2}月\d{1,2}日$")


def form_city_rows(xml: str):
    """特价表单的 (出发, 到达) 两行，返回 parse.Node 列表（自上而下）。

    判据是「整行宽的中文城市名」：城市行是横贯表单的 TextView；广告/
    补贴文案带标点或过长，不会被 `_CITY_ROW_RE` 全匹配。上界取日期带
    所在 y——「搜索特价」按钮也是整行中文，但在日期带下面。
    """
    nodes = _nodes(xml or "")
    if not nodes:
        return []
    width = max(n.x2 for n in nodes) or 1
    limit = 10 ** 9
    for n in nodes:
        if _BAND_TEXT_RE.match(n.text or ""):
            limit = n.y1
            break
    cands = [n for n in nodes
             if _CITY_ROW_RE.match(n.text or "")
             and (n.x2 - n.x1) >= width * 0.55
             and n.y1 < limit]
    cands.sort(key=lambda n: n.y1)
    return cands[:2]


def pending_cities(xml: str):
    """多选城市弹层底部已选城市 chip；返回 [(text, x2, cy)]。

    「到达城市」是多选弹层：点城市只是加进底部待选区，必须再点「确认」。
    不清掉上一次的 chip，就会搜成「新加坡，广州」两条航线。
    """
    out = []
    for n in _nodes(xml or ""):
        if "Bottom_Bar_Item_Text" not in (n.rid or ""):
            continue
        out.append((n.text, n.x2, (n.y1 + n.y2) // 2))
    return out


_MONTH_HEAD_RE = re.compile(r"^(\d{4})年(\d{1,2})月$")
# 交易日历格子自带 ISO 日期 id（真机 2026-11-02）：这是**首选**判据，
# 比「月份标题 + 日号」稳——不可售的日期干脆不渲染，靠标题法无法区分
# 「滚出屏幕」与「不可售」。
_DATE_ID_RE = re.compile(
    r"flight_calendar_date_cell_date_text-(\d{4})-(\d{2})-(\d{2})")


def calendar_cells(xml: str):
    """「选择日期」长日历里的日格：[(y, m, d, cx, cy)]。

    优先按格子自带 ISO id 取；老版式没有 id 时回落到「2027年2月」
    标题 + 纯数字日格（标题之上的上月尾巴丢弃）。**不可售日期不渲染**，
    所以「找不到」不等于解析失败——调用方要据此跳到窗口内最近可售日。
    """
    nodes = _nodes(xml or "")
    out = []
    for n in nodes:
        m = _DATE_ID_RE.search(n.rid or "")
        if m:
            out.append((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        (n.x1 + n.x2) // 2, (n.y1 + n.y2) // 2))
    if out:
        return out
    heads = []
    for n in nodes:
        m = _MONTH_HEAD_RE.match(n.text or "")
        if m:
            heads.append((int(m.group(1)), int(m.group(2)),
                          (n.y1 + n.y2) // 2))
    heads.sort(key=lambda h: h[2])
    for n in nodes:
        t = (n.text or "").strip()
        if not t.isdigit() or not 1 <= int(t) <= 31:
            continue
        if not 20 <= (n.x2 - n.x1) <= 120:
            continue        # 排除横幅/价格里的长数字
        cy = (n.y1 + n.y2) // 2
        mo = None
        for y, mm, hy in heads:
            if hy < cy:
                mo = (y, mm)
        if mo is None:
            continue
        out.append((mo[0], mo[1], int(t), (n.x1 + n.x2) // 2, cy))
    return out


def calendar_months(xml: str):
    """「选择日期」里可见的月份 [(year, month)]，按页面顺序。"""
    out = []
    for n in _nodes(xml or ""):
        m = _MONTH_HEAD_RE.match(n.text or "")
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out

