# -*- coding: utf-8 -*-
"""去哪儿 App 渠道（com.Qunar）。

数据面事实（2026-10-30 真机实测，MuMu / Android 15 / 10.4.24）：
  * **必须登录**：未登录时首页仍是登录页，「搜索」和日历「查价」都会
    跳到 `UCLoginByPhoneActivity`，返回键也退不出去；
  * 登录后日历页给出 6 天真实价（¥450/¥280/¥399…），点「下一步」进列表，
    列表含航班号/起降时刻/价格（实测 3 班：CZ8889 ￥280 等）；
  * 首页深链 `qunarphone://flight` 可直达机票页（绕开首启登录墙，
    但搜索仍要登录）。

因此本渠道把登录视为**硬前置**：未登录一律记 `login`，绝不记 `empty`。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List

from core.models import FlightPrice

from .app_base import AppCrawler
from .app_qunar_parse import detect_state, parse_flight_rows

_APP_PKG = "com.Qunar"
_APP_LABEL = "去哪儿旅行"
_FLIGHT_HOME_URI = "qunarphone://flight"

# 首页控件（RN 页面只有少量稳定 id，其余靠文案）
_ID_DEP_CITY = "com.Qunar:id/atom_flight_tv_dep_city"
_ID_ARR_CITY = "com.Qunar:id/atom_flight_tv_arr_city"
_ID_DEP_DATE = "com.Qunar:id/atom_flight_ll_dep_date"
_ID_SEARCH = "com.Qunar:id/atom_flight_rl_search_btn"

_NODE_RE = re.compile(r"<node\b([^>]*?)/?>")
# 首页标志：搜索面板容器（列表页/日历页都没有它）
_HOME_MARK = "atom_flight_search_panel"
# 城市行可点的最低 y1：上滑后城市行被压到 y=0..30，点中心(y=15)会落进
# 状态栏、点 y=40 会误触别的控件（真机实测）。低于它就先下拉回默认位。
_CITY_SAFE_Y = 60
# 城市选择页的标志（首页/日历/列表页都没有）
_CITY_PAGE_MARK = "com.Qunar:id/city_suggest_view"
# 设城市「没反应」重拍的最小间隔（秒）。首页顶部有 Lottie 动图，
# 两帧 dump 永远不相等——所以只能用**时间**判重拍，不能比整页快照。
_CITY_RETAP_GAP_S = 8.0
# 城市页收起态的搜索占位行：点它才展开搜索框（这一版收起时 0 个 EditText）
_ID_CITY_SEARCH_PH = "com.Qunar:id/qd_placeholder"
# 往返档切换控件（单程/往返/多程三个 RadioButton）
_ID_SINGLE_RT_SWITCH = "com.Qunar:id/atom_flight_round_rb"
_ID_SINGLE_ONLY_SWITCH = "com.Qunar:id/atom_flight_single_rb"
# 返程日期位容器：只有「往返」档才在视图树里（单程/多程都没有）
_ID_BACK_DATE_LL = "atom_flight_ll_back_date"
# 去程日期位容器（往返档下是相对布局，单程档同 id 也存在）
_ID_DEP_DATE_LL = "atom_flight_ll_dep_date"
# 首页日期文案节点（`1月29日`）；判「日期是否已设为目标日」只认它
_ID_DEP_DATE_TV = "com.Qunar:id/atom_flight_tv_dep_date"
# 往返日期弹层判据：每日格子的 content-desc 前缀（列表页/首页都没有）
_RT_CALENDAR_MARK = "q_flight_calendarDayItem#"
# 城市页里**不该点**的分区标题：其下方的同名城市是「历史选择」，点它
# 不生效（页面不关、城市不变），却会让调用方以为选好了。
_CITY_HISTORY_MARK = "历史选择"
# 城市页顶部的「国内/港澳台 | 国际」档位（同一 id，两行文案）。
# 2026-11-04 现场实证（`setcity-timeout-arr` 快照）：上一轮跑完国际航线后，
# 城市页**停在「国际」档**（左侧列东南亚/日韩/欧洲…），下一轮国内航线选
# "海口"时在**国际列表**里永远找不到——直接导致 `app_qunar` 成功率只有 26%
# （最近三天 170 轮里 125 轮零结果，几乎全是 `设到达城市失败`）。
# 代码里原先假定"不需要碰档位"，实测不成立：档位会跨轮残留。
_ID_CITY_TAB = "atom_flight_tab_item_tv"
_TAB_DOMESTIC = "国内"
_TAB_INTL = "国际"


def _find_city_tab(xml: str, want: str):
    """城市页顶部档位按钮里文案含 ``want`` 的那个节点（找不到返回 None）。"""
    want = str(want or "")
    if not want:
        return None
    for n in _nodes(xml or ""):
        rid = str(n.get("resource_id") or n.get("id") or "")
        if _ID_CITY_TAB not in rid:
            continue
        if want in str(n.get("text") or ""):
            return n
    return None


def _looks_intl_city(city: str) -> bool:
    """这个城市名属于国际档还是国内档（用于决定切哪个 tab）。

    判据走 ``core.citydata`` 的国内城市表：**在表里 = 国内**，否则按国际。
    机场码（PEK/NRT）先经 ``airport_city_code`` 归一——真机里城市位显示
    中文名，直接拿码去查表会一律判成国际。
    """
    s = str(city or "").strip()
    if not s:
        return False
    try:
        from core.citydata import CODE_NAME
    except Exception:
        return False
    try:
        from core.intl import airport_city_code  # type: ignore
        code = airport_city_code(s) or s
    except Exception:
        code = s
    return not (code in CODE_NAME or s in CODE_NAME
                or s in set(CODE_NAME.values()))


def _tab_is_selected(xml: str, want: str) -> bool:
    """档位是否已选中。

    **不能只看 `_nodes()`**：那个解析器只保留 text/id/desc/bounds，
    ``selected`` 属性被丢掉了（2026-11-04 实测）。所以在原始 XML 上按
    「含档位 id + 含目标文案 + selected=true」三者同节点判断。

    退化判据：看 ``atom_flight_tab_item_line`` 下划线是否落在目标按钮的
    水平范围内——两种表达任一成立就算已选中，避免无谓点击把页面搅乱。
    """
    want = str(want or "")
    raw = str(xml or "")
    if not want or not raw:
        return False
    for m in re.finditer(r"<node[^>]*>", raw):
        tag = m.group(0)
        if _ID_CITY_TAB not in tag or want not in tag:
            continue
        if re.search(r'selected="(true|1)"', tag):
            return True
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        cx = (int(b.group(1)) + int(b.group(3))) // 2
        for ln in re.finditer(r"<node[^>]*atom_flight_tab_item_line[^>]*>", raw):
            lb = re.search(r'bounds="\[(\d+),\d+\]\[(\d+),\d+\]"', ln.group(0))
            if lb and abs((int(lb.group(1)) + int(lb.group(2))) // 2 - cx) <= 80:
                return True
    return False


def _pick_city_row(xml: str, city: str):
    """城市页里可选的城市行；跳过「历史选择」区。

    真机结构（`CityListActivity`）：

        选择目的地 / 搜索国家/城市/景点等 / 国内·港澳台 | 国际
        历史选择  [清除]
        上海                      ← 点它等于没选（页面不关）
        热门城市
        上海 北京 成都 …          ← 这个才是有效行

    两组同名城市都在视图树里，按文案取第一个必然取到历史区那条。
    """
    nodes = _nodes(xml)
    hist_y = None
    hot_y = None
    for n in nodes:
        if n["text"] == _CITY_HISTORY_MARK:
            hist_y = n["y2"]
        elif n["text"] == "热门城市":
            hot_y = n["y2"]
    for n in nodes:
        if n["text"] != city:
            continue
        if hot_y is not None:
            if n["y1"] >= hot_y:
                return n
            continue
        # 没有「热门城市」分区：历史区在「历史选择」标题**之后**，
        # 命中位置在标题下沿以下就要当历史行（真机：标题 y2=425、
        # 历史城市 y1=440，两个都 > 标题起点，按起点比永远判不出来）。
        if hist_y is not None and n["y1"] >= hist_y - 8:
            continue
        return n
    return None


def _nodes(xml: str):
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        s = m.group(1)
        t = re.search(r'text="([^"]*)"', s)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', s)
        r = re.search(r'resource-id="([^"]*)"', s)
        d = re.search(r'content-desc="([^"]*)"', s)
        if not b:
            continue
        out.append({"text": (t.group(1) if t else "").strip(),
                    "id": (r.group(1) if r else ""),
                    "desc": (d.group(1) if d else "").strip(),
                    "x1": int(b.group(1)), "y1": int(b.group(2)),
                    "x2": int(b.group(3)), "y2": int(b.group(4))})
    return out


def _rt_tap_day(dev, page: str, target: str) -> bool:
    """往返日期弹层里点目标日（`q_flight_calendarDayItem#YYYY-MM-DD`）。

    id 里内嵌 ISO 日期，不必像单程日历那样按月份块拼数字；屏幕外的月份
    （y 超出可视区）要先滚进来——弹层本身可纵向滚动。
    """
    h = (dev.window_size() or (0, 900))[1] or 900
    want = _RT_CALENDAR_MARK + target
    for _ in range(8):
        cell = None
        for n in _nodes(page):
            if n["desc"] == want:
                cell = n
                break
        if cell is not None:
            if 0 < cell["y2"] <= h:
                if not dev.tap(*_center(cell)):
                    return False
                _sleep(2)
                return True
            if cell["y1"] >= h:
                dev.swipe(800, 700, 800, 300, 400)
            else:
                dev.swipe(800, 300, 800, 700, 400)
        else:
            dev.swipe(800, 700, 800, 300, 400)
        _sleep(2)
        page = dev.dump() or ""
        if _RT_CALENDAR_MARK not in page:
            return False
    return False


def _selected_back(page: str, parse_back_rows):
    """当前选中的返程卡（`FlightsRound_back_selected`）。

    列表页把「已选」写进 content-desc（`_selected`/`_unselected`），所以
    直接按标记找，不靠 y 对齐：返程列是独立可滚动的，第一张卡与去程卡
    并不一一对应。
    """
    rows = parse_back_rows(page)
    if not rows:
        return {}
    for n in _nodes(page):
        if n["desc"].endswith("FlightsRound_back_selected"):
            for r in rows:
                if r["y1"] == n["y1"]:
                    return r
            break
    return {}



def _center(n):
    return (n["x1"] + n["x2"]) // 2, (n["y1"] + n["y2"]) // 2


def _find_id(xml, rid):
    for n in _nodes(xml):
        if n["id"] == rid:
            return n
    return None


def _find_text(xml, want, exact=True):
    for n in _nodes(xml):
        if (n["text"] == want) if exact else (want in n["text"]):
            return n
    return None


def _save_fail_scene(tag: str, xml: str, root: str = ""):
    """把「屏幕上可读的节点」落一份到 debug/scene，供事后定位卡在哪一屏。

    账本里一行 `set-city-dep` 只说结果，看不到当时界面上有什么——本轮
    重试机制上线后仍有失败，没有现场就只能猜。真机 dump 常 200KB 不宜
    整份保存：这里只留 150 条带文案/id/content-desc 的节点（含坐标）。
    写文件失败不影响采集。
    """
    try:
        # TICKET_SCENE_DIR 是测试隔离锚（tests/conftest.py）：替身设备故意
        # 失败时按 CWD 写会把合成现场混进生产 debug/scene（实测踩过）。
        d = (root or os.environ.get("TICKET_SCENE_DIR")
             or os.path.join("debug", "scene"))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "qunar_app_%s_%s.txt"
                         % (time.strftime("%Y%m%d_%H%M%S"), tag))
        rows = []
        for n in _nodes(xml):
            if not (n["text"] or n["id"] or n["desc"]):
                continue
            rows.append("%s | %s | %s | %s | %d,%d,%d,%d"
                        % (n["id"].split("/")[-1], n["text"], n["desc"],
                           "clickable" if n.get("clickable") else "",
                           n["x1"], n["y1"], n["x2"], n["y2"]))
            if len(rows) >= 150:
                break
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(rows) + "\n")
    except Exception:
        pass


def _find_edit_box(xml: str):
    """城市页的搜索输入框（按 class 取，不猜文案）。

    输入框的文字是占位符「搜索国家/城市/景点等」，点它这一排 TextView
    不一定聚焦；真正的 EditText 才是可输入的。

    r720：这一版城市页**收起时整页 0 个 EditText**（真机 dump 实测），
    只有一行 `com.Qunar:id/qd_placeholder` 占位文本；必须先点它把搜索态
    展开，EditText 才会出现。所以调用方拿到 None 时应先点占位符再取一次
    （见 `_set_city`），不能直接判定「没有搜索框」。
    """
    for m in re.finditer(r"<node\b[^>]*>", xml or ""):
        s = m.group(0)
        if "android.widget.EditText" not in s:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', s)
        if not b:
            continue
        return {"text": "", "id": "", "x1": int(b.group(1)),
                "y1": int(b.group(2)), "x2": int(b.group(3)),
                "y2": int(b.group(4))}
    return None


def _find_search_placeholder(xml: str):
    """城市页收起态的搜索占位行（点它才展开出 EditText）。"""
    return (_find_id(xml, _ID_CITY_SEARCH_PH)
            or _find_text(xml, "搜索国家", exact=False)
            or _find_text(xml, "请输入城市", exact=False)
            or _find_text(xml, "搜索城市", exact=False)
            or _find_text(xml, "输入城市", exact=False))


def _search_result_row(xml: str, city: str):
    """搜索结果里的城市行：`海口 海南 中国 HAK` / `上海（不限机场）`。

    真机 search 命中后会给一行城市聚合行，下面是机场子项。三字码必须
    通用（2026-11-02 18:15 真机：写死 `SHA` 时海口行 HAK 永远匹配不到，
    搜索框已显示「海口」也不点，30 秒后记设到达城市失败）。
    """
    nodes = _nodes(xml)
    for n in nodes:
        t = (n["text"] or "").strip()
        if not t.startswith(city):
            continue
        if "不限机场" in t or re.search(r"(?<![A-Z])[A-Z]{3}(?![A-Z])", t):
            return n
    # 城市名与三字码分属两个节点：同一行（纵向中心差 <40px）也认。
    city_nodes = [n for n in nodes
                  if (n["text"] or "").strip() == city]
    code_nodes = [n for n in nodes
                  if re.fullmatch(r"[A-Z]{3}",
                                  (n["text"] or "").strip() or "")]
    for n in city_nodes:
        cy = (n["y1"] + n["y2"]) / 2.0
        for c in code_nodes:
            if abs(cy - (c["y1"] + c["y2"]) / 2.0) < 40:
                return n
    return None


def _ymd_to_md(ymd: str) -> str:
    """2026-11-12 -> '11.12'（去哪儿日历的日期文案）。"""
    return "%s.%s" % (ymd[5:7], ymd[8:10])


def _sleep(seconds: float):
    time.sleep(seconds)
    return True


_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")

# 中间「日期列 + 查价」页的日期列文案：`11.05`
_DATE_SLOT_RE = re.compile(r"^\d{1,2}\.\d{1,2}$")


def _date_slot_tap(xml: str, target: str):
    """中间页上「目标日期那一列的查价」按钮。

    真机结构（点「搜索」之后，2026-10-30）：

        北京 ⇄ 上海
        11.05   11.06   11.07   11.08   11.09   11.10
        周四    周五    周六    周日    周一    周二
        查价    查价    查价    查价    查价    查价

    不是点日期格子本身，而是**同一列下面的「查价」**；每一列宽约 150px，
    列内 `x1` 基本对齐。按 x 距离配对，比"取第 N 个查价"稳（列数会变）。
    目标日不在这一屏时返回 None（调用方按 timeout 记账）。

    r721：日期文案**带前导零**（页面是 `01.29`，不是 `1.29`）。原先按
    `"%d.%02d"` 生成 `1.29` 去精确比对，除 10–12 月外永远匹配不上 →
    中间页一列都不点、60s 后记 `no-list-page`（国内航线整轮 0 行，
    日志却像"渠道没数据"）。这里两种写法都认。
    """
    mm, dd = int(target[5:7]), int(target[8:10])
    # 月/日是否补零在各版之间不一致（实测国内页是 `01.29`，国际页可能是
    # `1.09`），四种组合全认，避免再因格式差异整轮空跑。
    wants = {"%d.%d" % (mm, dd), "%d.%02d" % (mm, dd),
             "%02d.%d" % (mm, dd), "%02d.%02d" % (mm, dd)}
    nodes = _nodes(xml)
    slot = None
    for n in nodes:
        if n["text"] in wants:
            slot = n
            break
    if slot is None:
        return None
    best = None
    for n in nodes:
        if n["text"] != "查价":
            continue
        if n["y1"] <= slot["y2"]:
            continue
        dx = abs(n["x1"] - slot["x1"])
        if dx > 60:
            continue
        if best is None or dx < abs(best["x1"] - slot["x1"]):
            best = n
    return best


def _search_widget(xml: str):
    """首页的「搜索」控件：优先稳定 id，退到文字节点。

    同一块区域在不同渲染帧里有时给 `atom_flight_rl_search_btn`，有时只
    渲染 `atom_flight_tv_search_text` 这个文字节点；只认 id 会间歇性
    判成 `no-search-button`（真机实测，多轮里随机出现）。
    """
    w = _find_id(xml, _ID_SEARCH)
    if w is not None:
        return w
    w = _find_id(xml, "com.Qunar:id/atom_flight_tv_search_text")
    if w is not None:
        return w
    hit = _find_text(xml, "搜索")
    if hit is not None:
        return hit
    # 文字可能被整块画在容器里：用「搜索面板底部」兜底
    return _find_id(xml, "com.Qunar:id/atom_flight_ll_search_panel")


def _month_day_cell(xml: str, ymd: str):
    """整月网格里目标日所在格子（标题 `YYYY年M月` 到下一个标题之间）。

    日期是**纯数字**（`1`/`2`…），全页多个月都有同名数字，必须按
    「月份块」限定，否则会点到别的月份的同一天。找不到返回 None。
    """
    try:
        year, month, day = int(ymd[:4]), int(ymd[5:7]), int(ymd[8:10])
    except (TypeError, ValueError):
        return None
    ns = _nodes(xml)
    heads = []
    for n in ns:
        m = _MONTH_RE.fullmatch((n["text"] or "").strip())
        if m:
            heads.append((n["y1"], int(m.group(1)), int(m.group(2))))
    if not heads:
        return None
    # 今天那一格不显示数字，显示「今天」（实测 10-30：整行是
    # 25 26 27 28 29 [今天] 31）——只按数字找会漏掉当天。
    wants = {str(day)}
    if (year, month, day) == tuple(int(x) for x in _today_iso().split("-")):
        wants.add("今天")
    heads.sort()
    for i, (top, y, m) in enumerate(heads):
        if (y, m) != (year, month):
            continue
        bottom = heads[i + 1][0] if i + 1 < len(heads) else 10 ** 9
        hit = None
        for n in ns:
            if (n["text"] or "").strip() not in wants:
                continue
            if not (top < n["y1"] < bottom):
                continue
            if hit is None or n["y1"] < hit["y1"]:
                hit = n
        return hit
    return None


def _visible_months(xml: str):
    """日历里当前渲染出来的月份，按屏幕 y 从上到下：[(2027, 7), (2027, 8)]。

    用来决定「该往哪个方向翻」：日历弹层会记住上次停留的月份，目标可能
    在**上方**（早于可见区间）。只按「格子没渲染就往下滑」会把方向赌死。
    """
    out = []
    for n in _nodes(xml):
        m = _MONTH_RE.fullmatch((n["text"] or "").strip())
        if m:
            out.append((n["y1"], int(m.group(1)), int(m.group(2))))
    out.sort()
    return [(y, m) for _, y, m in out]


_CAL_DAY_RE = re.compile(r"q_flight_calendarDayItem#(\d{4}-\d{2}-\d{2})")


def _visible_cal_days(xml: str, year: int, month: int) -> list:
    """该月已渲染的日号（来自 day item 的 content-desc/resource-id）。"""
    days = set()
    for n in _nodes(xml):
        for raw in (n.get("desc"), n.get("id")):
            m = _CAL_DAY_RE.search(raw or "")
            if not m:
                continue
            iso = m.group(1)
            try:
                if int(iso[:4]) == year and int(iso[5:7]) == month:
                    days.add(int(iso[8:10]))
            except ValueError:
                continue
    return sorted(days)


def _calendar_scroll_dir(xml: str, target: str) -> str:
    """目标日在日历里该往哪边翻：up / down / ""（等一帧）。

    2026-11-02 21:58 真机：日历停在 11/29-30，目标 11/16 在同月但已滚
    出视口；只看月份头会误判“目标月可见、格子只是没渲染”，一直等待。
    """
    try:
        year, month, day = int(target[:4]), int(target[5:7]), int(target[8:10])
    except (TypeError, ValueError, IndexError):
        return ""
    vis = _visible_months(xml)
    days = _visible_cal_days(xml, year, month)
    if days:
        if day < days[0]:
            return "up"
        if day > days[-1]:
            return "down"
        return ""
    if not vis:
        return ""
    if (year, month) < vis[0]:
        return "up"
    if (year, month) > vis[-1]:
        return "down"
    return ""


def _save_tap_shot(dev, tag: str, root: str = ""):
    """点击疑似没生效时存一张**当时的屏幕截图**（PNG）。

    视图树只能证明"控件在"，证明不了"点击被谁吃掉了"——广告浮层、输入法、
    Lottie 动效都不进无障碍树。这张图是下一次归因的关键证据。
    写失败不影响采集。
    """
    try:
        png = dev.screencap()
        if not png:
            return
        d = (root or os.environ.get("TICKET_SCENE_DIR")
             or os.path.join("debug", "scene"))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "qunar_app_%s_%s.png"
                         % (time.strftime("%Y%m%d_%H%M%S"), tag))
        with open(p, "wb") as f:
            f.write(png)
    except Exception:
        pass


def _today_iso() -> str:
    """设备本地今天（YYYY-MM-DD）：校准「今天」这个特殊文案用。"""
    return time.strftime("%Y-%m-%d")


class AppQunarCrawler(AppCrawler):
    name = "app_qunar"
    package = _APP_PKG
    # 深链入口（基类 ANR 自愈重启时用它回到机票页，而不是落到启动页）
    home_uri = _FLIGHT_HOME_URI

    def login_url(self) -> str:
        return ("android://%s?login=phone —— 去哪儿 App 必须用手机号登录"
                "（含验证码），登录后本渠道才可用" % _APP_PKG)

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        rt = self.runtime()
        ok, why = rt.ensure_ready()
        if not ok:
            self.path_note("android-runtime", "unsupported",
                           detail=f"runtime not ready: {why}")
            self.logger.warning("[%s] Android 运行时未就绪：%s", self.name, why)
            return []
        dev = rt.device()
        if dev is None:
            self.path_note("android-device", "unsupported",
                           detail="device unavailable")
            return []

        with rt.device_lock(owner=self.name):
            # 每轮只允许一次「杀进程重建首页」（见 `_hard_reset_home`）
            self._home_hard_reset = False
            # 统一前置（登录态恢复 → 清权限框 → 清 ANR），与其它 App 渠道同源
            self.prepare_device(dev)
            # 每条航线从干净首页开始（复用上轮界面会被广告/动效残留吞点击）
            self._ensure_app_fresh(dev)
            if ret_date:
                return self._fetch_round_trip_locked(
                    dev, from_city, to_city, dates, ret_date)
            return self._fetch_locked(dev, from_city, to_city, dates)

    # ---------- 往返 ----------
    #: 去哪儿 App 的「往返」是真功能（真机 2026-10-31）：顶部单程/往返/
    #: 多程三档，选「往返」后出现返程日期位；结果页左右两列对应去程/
    #: 返程，页脚给出「往返价格」总额。
    supports_round_trip = True

    def _fetch_round_trip_locked(self, dev, from_city: str, to_city: str,
                                 dates: List[str], ret_date: str
                                 ) -> List[FlightPrice]:
        """往返：切「往返」档 → 设城市与去/返日期 → 搜索 → 读选中组合总价。

        口径与智行/同程一致：**价格是往返总价**，`extra` 里每条是
        「去程 + 返程」的组合。去哪儿没有「一个去程 × 一个返程 = 一个
        组合价」的现成接口——页脚只报**当前选中对**的总价，所以先读默认
        组合，再把去程逐张点过去、每张读一次页脚，得到该去程 + 当前返程
        的总价。这样产出的每一行都是页面**真实报出**的数字，不靠加法。
        """
        from .app_qunar_roundtrip import (is_round_trip_page, parse_back_rows,
                                          parse_footer_total, parse_go_rows)

        started = time.time()
        dep_date = (dates or [""])[0]
        if not dep_date or not ret_date:
            self.path_note("TRIP", "unsupported",
                           detail="往返需要去程日与返程日各一个")
            return []

        ok, why = self._set_round_trip_form(dev, from_city, to_city,
                                            dep_date, ret_date)
        if not ok:
            # 导航失败不是「已确认验证码」：blocked 会被 pacing 归 captcha
            # 并熔断 300s；真验证码由 _clear_blockers 识别后另记。
            self.path_note("app-route", "timeout", detail=why,
                           ms=int((time.time() - started) * 1000))
            self.logger.warning("[%s] 往返导航失败：%s", self.name, why)
            return []

        xml = self._scroll_home(dev, want="search")
        btn = _search_widget(xml)
        if btn is None:
            self.path_note("app-search", "timeout",
                           detail="往返首页找不到搜索按钮")
            return []
        if not dev.tap(*_center(btn)):
            self.path_note("app-search", "timeout", detail="点搜索失败")
            return []

        page = ""
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(4)
            page = dev.dump() or ""
            if self._is_login_page(page):
                self.login_suspect = True
                self.path_note("app-login", "login",
                               detail="往返搜索后要求登录")
                return []
            if is_round_trip_page(page):
                break
        if not is_round_trip_page(page):
            # 国际档实测不给往返结果页：表单确实是「往返 + 去程/返程日」，
            # 搜索后仍是单程国际列表（2026-11-01 SHA→LHR：25 张
            # QunarFlightInterList 卡、无 ScrollView_go/back、无「往返价格」）。
            # 这要如实记成 unsupported（不是超时），否则账本只会写
            # no-list-page，读起来像「页面没打开」。
            try:
                from core.intl import is_intl_route
                _intl = bool(is_intl_route(from_city, to_city))
            except Exception:
                _intl = False
            if _intl:
                self.path_note(
                    "TRIP", "unsupported",
                    detail="国际档未提供往返结果页（2026-11-01 SHA→LHR "
                           "实测：设了返程日仍出单程列表）")
            self.note_date(dep_date, [], "no-list-page",
                           ms=int((time.time() - started) * 1000))
            return []

        go_rows = parse_go_rows(page)
        if not go_rows:
            self.note_date(dep_date, [], "no-priced-rows",
                           ms=int((time.time() - started) * 1000))
            return []

        # 逐张去程卡点过去，读页脚「往返价格」。只收**页脚确实报出总价**
        # 的组合：选中态没生效时页脚还是上一张的价，那种值会张冠李戴。
        combos: List[dict] = []
        for row in go_rows:
            if not dev.tap(row["cx"], row["cy"]):
                continue
            time.sleep(2)
            after = dev.dump() or ""
            total = parse_footer_total(after)
            if total is None:
                continue
            back = _selected_back(after, parse_back_rows)
            combos.append({
                "price": float(total),
                "code": row["flight_no"],
                "name": row["flight_no"],
                "depDate": dep_date,
                "depTime": row["depart_time"],
                "arrTime": row["arrive_time"],
                "retDate": ret_date,
                "retDepTime": back.get("depart_time", ""),
                "retArrTime": back.get("arrive_time", ""),
                "retCode": back.get("flight_no", ""),
                "tripType": "RT",
            })
        if not combos:
            self.path_note("往返", "timeout",
                           detail="往返页没有读到任何「往返价格」")
            self.note_date(dep_date, [], "no-priced-rows",
                           ms=int((time.time() - started) * 1000))
            return []

        best = min(combos, key=lambda c: c["price"])
        self.path_note("往返", "ok", rows=len(combos),
                       detail="%d 条往返组合（页脚往返总价口径）" % len(combos),
                       ms=int((time.time() - started) * 1000))
        price = FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=dep_date, price=best["price"],
            flight_no=best["code"], depart_time=best["depTime"],
            arrive_time=best["arrTime"],
            extra=json.dumps(combos, ensure_ascii=False),
            prov=f"app:{_APP_PKG}:roundtrip",
        )
        self.note_date(dep_date, [price], "ok",
                       ms=int((time.time() - started) * 1000),
                       url=f"android://{_APP_PKG}?view=roundtrip")
        return [price]

    def _set_round_trip_form(self, dev, from_city: str, to_city: str,
                             dep_date: str, ret_date: str):
        """切「往返」档 + 设航线 + 两段日期。返回 (ok, detail)。

        日期弹层是**两段式**：第一次点「去程」日期位弹层定位去程，在里面
        点一天只是把「去程」标上；再点一天才是「返程」；最后按「确定」。
        分两段点错（或直接点日期位两次）会得到「去程=上一次的返程」。
        """
        xml = self._ensure_home(dev)
        if not xml:
            return False, "没能回到机票首页"
        if self.is_login_wall(xml) or self._is_login_page(xml):
            return False, "需要登录"

        seg = _find_id(xml, _ID_SINGLE_RT_SWITCH)
        if seg is None:
            seg = _find_text(xml, "往返")
        if seg is None:
            return False, "首页找不到「往返」档"
        dev.tap(*_center(seg))
        _sleep(3)

        xml = self._scroll_home(dev, want="city")
        from_name = self._city_name(from_city)
        to_name = self._city_name(to_city)
        if not self._set_city(dev, xml, from_name, side="dep"):
            return False, f"设出发城市失败：{from_name}"
        if not self._set_city(dev, dev.dump() or "", to_name, side="arr"):
            return False, f"设到达城市失败：{to_name}"

        xml = dev.dump() or ""
        # 去程日期位 → 弹层选「去程」，再选「返程」，确定。
        if not self._pick_round_trip_dates(dev, xml, dep_date, ret_date):
            return False, f"设往返日期失败：{dep_date}/{ret_date}"
        return True, ""

    def _switch_to_single(self, dev, xml: str) -> str:
        """首页若停在「往返」或「多程」档就点回「单程」，返回切档后的 XML。

        判据是**返程日期位在不在**（`atom_flight_ll_back_date`），不是
        RadioButton 的 checked——同一渲染帧里 checked 会滞后再更新。
        已经单程就直接返回，不白点。

        **多程也必须切**（2026-11-04 现场）：`nolist-2026-11-16` 那份 dump
        停在**多程**档——

            选择航班 / 抱歉未找到符合条件的多程航班
            第一程 上海→伦敦 11月16日 / 第二程 海口→东京 2月17日

        而原来只认"往返"（`atom_flight_ll_back_date`）。多程页**没有**
        返程日期位，于是判据不命中 → 认为"已是单程" → 不切档 → 直接搜索
        → 落到多程结果页（"未找到符合条件的多程航班"）→ `detect_state`
        拿不到时刻对 → 记 `no-list-page`。实测近两天 **34 次**全是这个。
        """
        low = xml or ""
        is_round = _ID_BACK_DATE_LL in low
        # 多程页特征：有「第一程」+「第二程」段落，且没有首页城市位。
        # 用一个能同时覆盖"在首页多程表单"和"在多程结果页"的判据。
        is_multi = ("第一程" in low and "第二程" in low)
        if not (is_round or is_multi):
            return xml
        seg = _find_id(xml, _ID_SINGLE_ONLY_SWITCH)
        if seg is None:
            seg = _find_text(xml, "单程")
        if seg is None:
            # 多程结果页上可能没有档位切换控件（那是列表/空态页，不是表单）。
            # 这种情况按 BACK 退回表单再找——**可能不止一层**（结果页 → 表单
            # 或 结果页 → 查询中间页 → 表单），所以循环退，最多 3 层。
            if is_multi and not is_round:
                page = xml
                for _ in range(3):
                    dev.keyevent("KEYCODE_BACK")
                    _sleep(2)
                    page = dev.dump() or page
                    seg = (_find_id(page, _ID_SINGLE_ONLY_SWITCH)
                           or _find_text(page, "单程"))
                    if seg is not None:
                        break
                    # 已经退回机票首页表单（有城市位）却没看到单程：
                    # 多半是渲染未完成，再给一帧；仍没有就放弃退栈。
                    if _ID_DEP_CITY in page:
                        _sleep(2)
                        page = dev.dump() or page
                        seg = (_find_id(page, _ID_SINGLE_ONLY_SWITCH)
                               or _find_text(page, "单程"))
                        break
                if seg is None:
                    return page
                dev.tap(*_center(seg))
                _sleep(3)
                return dev.dump() or page
            return xml
        dev.tap(*_center(seg))
        _sleep(3)
        return dev.dump() or xml

    def _pick_round_trip_dates(self, dev, xml: str, dep_date: str,
                               ret_date: str) -> bool:
        """在往返日期弹层里两段选日（先去程、后返程）+ 确定。"""
        dep_cn = "%d月%d日" % (int(dep_date[5:7]), int(dep_date[8:10]))
        ret_cn = "%d月%d日" % (int(ret_date[5:7]), int(ret_date[8:10]))
        # 已就位就跳过（多日期同航线时省一轮弹层）
        if _find_text(xml, dep_cn) is not None and \
                _find_text(xml, ret_cn) is not None:
            return True

        trigger = None
        for n in _nodes(xml):
            if n["id"].endswith(_ID_DEP_DATE_LL):
                trigger = n
                break
        if trigger is None:
            for n in _nodes(xml):
                if re.fullmatch(r"\d{1,2}月\d{1,2}日", (n["text"] or "").strip()):
                    trigger = n
                    break
        if trigger is None or not dev.tap(*_center(trigger)):
            return False

        deadline = time.time() + 12
        page = ""
        while time.time() < deadline:
            _sleep(2)
            page = dev.dump() or ""
            if _RT_CALENDAR_MARK in page:
                break
        if _RT_CALENDAR_MARK not in page:
            return False

        # 弹层里点第一下 = 去程，点第二下 = 返程。
        for want in (dep_date, ret_date):
            if not _rt_tap_day(dev, page, want):
                return False
            _sleep(2)
            page = dev.dump() or ""

        # 「确定」由灰变亮才可点：只有两段都选中了才亮。
        ok_btn = None
        for n in _nodes(page):
            if n["text"] == "确定":
                ok_btn = n
                break
        if ok_btn is None or not dev.tap(*_center(ok_btn)):
            return False
        _sleep(3)
        back = dev.dump() or ""
        if _RT_CALENDAR_MARK in back:
            return False
        return _find_text(back, dep_cn) is not None and \
            _find_text(back, ret_cn) is not None

    # ---------- 内部 ----------
    def _fetch_locked(self, dev, from_city: str, to_city: str,
                      dates: List[str]) -> List[FlightPrice]:
        started = time.time()

        # 冷启动后先把首页（含搜索面板）拿到手：登录墙必须最先识别，
        # 此时做任何点击都是白费。`_ensure_home` 已包含「回首页 + 补面板」，
        # 与后续每个日期用的是同一条判据（不再有两套首页判定）。
        xml = self._ensure_home(dev)
        if not xml:
            self.path_note("app-dump", "timeout",
                           detail="没能打开机票首页")
            return []
        state = detect_state(xml)
        if state == "login" or self._is_login_page(xml):
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="需要手机号登录（去哪儿不登录拿不到任何票价）")
            self.logger.warning("[%s] 页面要求登录，本渠道需先完成手机号登录",
                                self.name)
            return []

        # 档位复位：上一轮跑过往返，首页仍停在「往返」档（有返程日期位），
        # 此时单程流程的选日/搜索会按两段式弹层走 → `pick-date-failed`，
        # 更糟的是不报错时会把往返总价当成单程价记下来。判据就是返程
        # 日期位在不在，只点一次「单程」，与往返流程切档同源。
        xml = self._switch_to_single(dev, xml)

        from_name = self._city_name(from_city)
        to_name = self._city_name(to_city)

        out: List[FlightPrice] = []
        targets = [d for d in (dates or []) if d] or [""]
        for target in targets:
            try:
                got, why = self._one_date(dev, from_name, to_name, target,
                                          from_city, to_city)
            except Exception as e:
                self.logger.info("[%s] %s 采集异常：%s", self.name, target,
                                 type(e).__name__)
                got, why = [], "exception:" + type(e).__name__
            # 记账走基类单源（与智行同一套措辞与 empty 判据）
            self.note_date(target, got, why,
                           ms=int((time.time() - started) * 1000),
                           url=f"android://{_APP_PKG}?view=list")
            if got:
                out.extend(got)
        return out

    def _is_login_page(self, xml: str) -> bool:
        # 与基类 LOGIN_FORM_MARKS 同源（r723）：验证码页也是登录墙。
        # 各写一份判据会漂——实测这里少了验证码页两条，登录墙被当成普通页。
        return self.is_login_wall(xml)

    def read_route(self, dev):
        """从机票首页读当前航线 (出发名, 到达名)；不在首页/读不到返回 None。

        判据是屏幕上的城市文案（基类 `_route_unchanged` 据此比对）——
        多日期同航线时靠它跳过重复设城市，省掉一次 20s 的城市选择。
        """
        xml = dev.dump() or ""
        if _HOME_MARK not in xml:
            return None
        dep = _find_id(xml, _ID_DEP_CITY)
        arr = _find_id(xml, _ID_ARR_CITY)
        if dep is None or arr is None:
            return None
        return (dep["text"], arr["text"])

    def _one_date(self, dev, from_name: str, to_name: str,
                  target: str, from_city: str = "",
                  to_city: str = "") -> List[FlightPrice]:
        """设城市 → 选日期 → 点搜索 → 解析列表。返回 (prices, reason)。

        reason 只在没拿到价格时有意义：`empty` 表示**列表页确实打开了且
        该日无航班**；其他值（no-home/set-city/pick-date-failed/login）都是
        「这次没采成」，由基类 `note_date` 记成 timeout，绝不记 empty。
        """
        xml = self._ensure_home(dev)
        if not xml:
            return [], "no-home"
        # 航线未变就跳过设城市（与智行同一套判据：只看屏幕事实）。
        # 多日期场景下每个日期都会走到这里，重设一次城市就白花 ~20s。
        if self._route_unchanged(dev, from_city, to_city):
            self.logger.info("[%s] 航线未变（%s→%s），跳过重设",
                             self.name, from_name, to_name)
        else:
            # 先滚到「城市行完整可点」的位置（上滑位下城市被压到 y=0 点不动）
            xml = self._scroll_home(dev, want="city")
            # 国际/国内的城市列表是两套档位。判据与浏览器渠道同源：
            # 任一端在大陆码集外即国际。跑过国际再切国内时，城市页还停在
            # 国际档（分区是「东南亚/日韩/欧洲」），国内城市只剩历史记录
            # —— 不切回来就整轮 set-city。
            if not self._set_city(dev, xml, from_name, side="dep"):
                if self.login_suspect:
                    return [], "login"
                self.logger.info("[%s] 设出发城市失败：%s", self.name,
                                 from_name)
                return [], "set-city-dep"
            # 选完城市会回到首页，这里直接读页面即可。**不要再调
            # `_ensure_home`**：它为了「不在首页」会先按 3 次 BACK、再等
            # 25s 深链，实测一次要 33s；三个步骤各调一次就把 60s 搜索窗口
            # 吃光，整轮 0 行（真机踩过）。
            if not self._set_city(dev, dev.dump() or "", to_name, side="arr"):
                if self.login_suspect:
                    return [], "login"
                self.logger.info("[%s] 设到达城市失败：%s", self.name, to_name)
                return [], "set-city-arr"
        if target:
            if not self._pick_date(dev, dev.dump() or "", target):
                # 选日失败**不能继续搜索**：列表页无法校验「这份结果属于哪天」，
                # 搜下去只会把首页当时的日期（多日期时就是上一个日期）的价
                # 记到 target 名下——日期错位价，比缺数据更糟。宁可这天记
                # timeout，也不产出串味数据。先退回首页，别把日历弹层留给
                # 下一个日期。
                self.logger.warning("[%s] 选日期失败（%s），该日不产出数据",
                                    self.name, target)
                self._ensure_home(dev)
                return [], "pick-date-failed"
        return self._search_and_parse(dev, target, from_city, to_city)

    def _ensure_home(self, dev):
        """取机票首页 XML（只要在首页即可）；不在首页就退回深链。

        两个实测坑（都导致整轮 0 行）：
          1. App 停在日历页/列表页时，`qunarphone://flight` 深链常被 RN
             导航栈当成重复入口吞掉——先按 BACK 退栈，再发深链兜底；
          2. 首页的「城市位」和「搜索按钮」**互斥**：默认滚动位城市可点但
             搜索按钮不在视图树；上滑一屏搜索按钮出现、城市行却被压到
             y=0 点不动。所以这里只保证「在首页」，滚到哪一位交给
             `_scroll_home(want=...)` 按当前步骤决定。
        """
        xml = dev.dump() or ""
        if self._is_login_page(xml):
            # 登录页是**启动首屏**，不代表会话失效：真机实测（2026-10-30）
            # 前台停在 UCLoginByPhoneActivity 时发 `qunarphone://flight`
            # 能直接进机票首页，且是登录态（首页正常、下单不跳登录）。
            # 直接按 login 放弃，会把「明明登录着」判成「需要登录」——
            # 每次 force-stop 之后都会这样误报一轮。
            if dev.deep_link(_FLIGHT_HOME_URI):
                deadline = time.time() + 30
                while time.time() < deadline:
                    time.sleep(2.5)
                    probe = dev.dump() or ""
                    if _HOME_MARK in probe:
                        return probe
            return xml          # 深链也没绕过去：交给调用方按 login 入账
        if _HOME_MARK in xml:
            return xml
        # App 卡死（系统「没有响应」）会一直挡着，BACK/深链都无效——
        # 先点「等待」让它缓过来；等不回来会重启 App（基类统一处理）。
        self.recover_anr(dev, wait_s=60)
        xml = dev.dump() or ""
        if _HOME_MARK in xml or self._is_login_page(xml):
            return xml
        for _ in range(3):
            if not dev.keyevent("KEYCODE_BACK"):
                break
            time.sleep(2)
            xml = dev.dump() or ""
            if self._is_login_page(xml) or _HOME_MARK in xml:
                return xml
        # 深链在列表页常被 RN 导航栈吞掉（注释里写过，但兜底仍是深链）：
        # 实测跑完国际再切国内时，页面停在列表页，深链返回成功却什么都没
        # 发生，随后「设到达城市」拿着列表页的 dump 去找城市位必然失败
        # （整轮 set-city-arr）。深链前先 force-stop，让 App 从首页入口重建。
        dev.app_stop(_APP_PKG)
        # 冷启动到首页面板就绪实测 8–12s；force-stop 后立刻发深链会落到
        # `TabHomeActivity` 的白屏中间态（dump 0 节点），再等也不会自愈。
        # 先给它 3s 退干净，深链后再轮询 45s。
        time.sleep(3)
        if not dev.deep_link(_FLIGHT_HOME_URI):
            return ""
        deadline = time.time() + 45
        while time.time() < deadline:
            time.sleep(2.5)
            xml = dev.dump() or ""
            if self._is_login_page(xml) or _HOME_MARK in xml:
                return xml
        return ""

    def _scroll_home(self, dev, want: str = "search") -> str:
        """把首页滚到能操作目标控件的位置，返回该位置的 XML。

        `want="city"`   城市行要完整可见（默认滚动位，y1 在屏幕中段）；
        `want="search"` 搜索按钮要在视图树里（需要上滑一屏）。

        实测互斥关系：上滑后 `atom_flight_sp_search_panel` 顶到 y=0，
        城市行被压成 30px 且点击无效（点 y=20 无反应、点 y=40 误触跳页）；
        默认位则搜索按钮根本不在视图树。所以按步骤滚，不能一次滚到底。
        """
        xml = dev.dump() or ""
        for _ in range(4):
            if want == "search":
                if _ID_SEARCH in xml or "atom_flight_tv_search_text" in xml:
                    return xml
                dev.swipe(800, 700, 800, 320, 400)      # 上滑：露搜索
            else:
                dep = _find_id(xml, _ID_DEP_CITY)
                if dep is not None and dep["y1"] >= _CITY_SAFE_Y:
                    return xml
                dev.swipe(800, 320, 800, 760, 400)      # 下拉：回默认位
            time.sleep(2)
            xml = dev.dump() or ""
        return xml

    def _set_city(self, dev, xml: str, city: str, side: str) -> bool:
        """点城市位 → 在城市选择页选城市（支持国际）。

        城市选择页实测结构：两个 tab「国内/港澳台」「国际」+ 一个
        「搜索国家/城市/景点等」输入框。顺序是：当前列表有同名就直接点，
        没有就用搜索框——**点档位按钮这条路已删除**，见下面 ② 的实证。

        **选中必须校验「离开了城市页」且城市位真的变了**：页面自带
        「历史选择」区，里面就有刚用过的同名城市（真机：`历史选择 / 清除
        / 上海`）。按文案 `find(city)` 会先命中它，点下去等于什么都没选，
        函数却返回 True——随后 `_pick_date` 拿到的仍是城市页，日历打不开，
        整轮报 `pick-date-failed` 而账本上看不出卡在哪。
        """
        rid = _ID_DEP_CITY if side == "dep" else _ID_ARR_CITY
        # 选完出发城市回首页有转场：这一帧可能是**空页**（实测 2026-11-01
        # 19:10 落盘只有 1 字节）——别把它当成「没有城市控件」直接失败/重启，
        # 等几帧拿到真页面再判。
        for _ in range(6):
            if xml and _nodes(xml):
                break
            _sleep(1)
            xml = dev.dump() or ""
        node = _find_id(xml, rid)
        if node is None:
            # 登录墙优先于「没城市位」：会话过期时首页会被登录页顶掉，
            # 城市位当然不在——这时记 set-city-dep 会把「该去重登」误导成
            # 「选择器坏了」。现场实证：21:28 快照恢复已报「快照已失效
            # （仍停在登录墙）」，账本却仍记 set-city-dep。
            if self.is_login_wall(xml):
                self.login_suspect = True
                self.path_note(
                    "app-login", "login",
                    detail="登录态失效（页面停在登录墙），需在内嵌画面重新登录")
                return False
            # 城市位不在视图树里（页面根本没到机票首页 / 停在残缺首页）。
            # 这条早退**不点也不等**，所以更要留现场：账本只会写
            # `set-city-dep`，看不出是「点不中」还是「压根没这个控件」。
            _save_fail_scene("setcity-noid-" + side, xml)
            # 现场实证：这一屏的首页「形似而神不似」（日期行在、城市控件
            # 的 id 没了）——BACK 退栈救不回来，杀进程重建一次再认。
            if getattr(self, "_home_hard_reset", True):
                return False
            self._home_hard_reset = True
            page = self._hard_reset_home(dev)
            node = _find_id(page, rid)
            if node is None:
                _save_fail_scene("setcity-noid2-" + side, page)
                return False
        # 城市位文案可能带机场名（「上海虹桥」「上海浦东」）：用**包含**
        # 判断，精确相等会把已设好的城市当成没设，白点一次并可能把页面
        # 切到别处。
        if city and city in str(node["text"] or ""):
            return True
        if not dev.tap(*_center(node)):
            _save_fail_scene("settap-" + side, xml)
            return False

        def _on_city_page(page: str) -> bool:
            """城市页**真的**开着：有 suggest 组件、首页城市位不在，且带
            城市页自己的控件（搜索占位行/输入框/热门城市/历史选择）。

            现场实证两例：① 21:11 首页视图树里带着隐藏的 `city_suggest_view`
            （预加载），只看这个 id 会把首页判成城市页；首页与城市页互斥的
            标志是 `atom_flight_tv_dep_city` 在不在。② 22:08 的失败现场是
            **特价页**（国内/国际/往返 页签 + 搜索），它同样预加载 suggest
            组件、且没有城市位——只靠前两条会把它当城市页，于是在里面找
            城市行/搜索框全部落空。城市页自己的控件一个都没有的，就不是。
            """
            if not page or _CITY_PAGE_MARK not in page:
                return False
            if _ID_DEP_CITY in page:
                return False
            return (_find_search_placeholder(page) is not None
                    or _find_edit_box(page) is not None
                    or _find_text(page, "热门城市") is not None
                    or _find_text(page, _CITY_HISTORY_MARK) is not None)

        def _left_city_page(page: str) -> bool:
            return bool(page) and not _on_city_page(page)

        def _city_is_set(page: str) -> bool:
            """离开城市页后**核对城市位真的变成目标**。

            真机踩过两种「离开≠选上」：点档位直接回首页（城市还是旧值）、
            点城市行落到特价页（整页换掉）。只认「已离开城市页」就返回
            True，会把旧城市当成功，整轮搜错航线还查不出。
            """
            slot = _find_id(page or "", rid)
            return (slot is not None
                    and city in str(slot.get("text") or ""))

        # 点完先给转场 6 秒（1s 一帧，见到城市页就立刻往下走）。
        # 真机现场：横屏 1600×900 下首页→城市页 >2s；原来固定 sleep(2)
        # 就判「没打开」，第二拍正好落到**已经打开的城市页**列表上，把状态
        # 搅乱后停回首页，30 秒走完只留一行 `set-city-dep`。
        _deadline_open = time.time() + 6
        page = ""
        while time.time() < _deadline_open:
            _sleep(1)
            page = dev.dump() or ""
            if _on_city_page(page):
                break
        # 预算按**帧数**而不是纯时间：实测空载 dump ≈2.3–3.0s，而整机跑着
        # 五个浏览器渠道时单帧能到 ~20s（故障轮 45 秒只走了 2 帧，选择/搜索
        # 根本来不及尝试）。给到 12 帧；若首帧就超过 6s，把总时长放宽到 90s。
        deadline = time.time() + 45
        frames = 0
        _t_first = time.time()
        typed = False
        _tab_tried = False       # 档位自愈只做一次（避免来回切）
        retaps = 0
        last_tap = time.time()
        # 每帧落在哪个分支（home/city/other/empty）：失败时一次打出来，
        # 比事后靠最终快照猜「中途有没有进过城市页」可靠得多。
        trace = []
        while time.time() < deadline and frames < 12:
            _t_frame = time.time()
            frames += 1
            time.sleep(1)
            page = dev.dump() or ""
            if frames == 1 and (time.time() - _t_first) > 6:
                deadline = time.time() + 90     # 整机被浏览器拖慢：放宽总时长
            # ⓪' **点击没生效才重点**（账本实证：`set-city-dep` 43 次、
            # `set-city-arr` 5 次，占全部超时一半以上）。
            # 但「点没生效」的判据不能用「2 秒后还没看到城市页」：真机
            # 现场（2026-11-01 18:30 横屏 1600×900）首页→城市页转场 >2s，
            # 原来第二拍就落到了**已经打开的城市页**上（点到城市行/返回），
            # 状态被打乱后停回首页，30 秒走完只留一行 `set-city-dep`。
            # 现在按**时间**判「没反应」：点完先给 6s 转场（见到城市页就往下走），
            # 之后距上次点击 ≥8s 仍停在含城市位的页面才重拍，最多 2 次。
            _mark = _on_city_page(page)
            _n2 = None if _mark else _find_id(page, rid)
            trace.append("city" if _mark else
                         ("home" if _n2 is not None else
                          ("empty" if not page else "other")))
            if page and not _mark:
                node2 = _n2
                if node2 is not None:
                    if city in str(node2.get("text") or ""):
                        return True          # 城市已是目标（含机场名后缀）
                    # 首页有 Lottie 动图：两帧 dump 永不相等，按「整页快照
                    # 没变」判重拍会永远不重拍（实测 2026-11-01 19:01 超时）。
                    # 改为**按时间**：距上次点击 ≥8s 仍停在含城市位的页面才重拍。
                    if retaps < 2 and time.time() - last_tap >= _CITY_RETAP_GAP_S:
                        retaps += 1
                        if retaps == 1:
                            # 第一次「点了没反应」的当刻截图（视图树看不出浮层）
                            _save_tap_shot(dev, "tap1-" + side)
                        last_tap = time.time()
                        dev.tap(*_center(node2))
                        continue
                    # 重试够了还停在首页且城市未变：这条通路这次就是没点开，
                    # 直接失败。继续在首页上找搜索框只会白等满 30 秒，
                    # 还可能在首页误点其它元素。
                    _save_fail_scene("setcity-" + side, page)
                    return False
            # ① 当前列表里就有（国内热门城市走这条）→ 直接点。
            # **跳过历史选择区**：它的坐标在「历史选择」标题之上，点它不生效。
            hit = _pick_city_row(page, city)
            if hit is not None:
                if dev.tap(*_center(hit)):
                    # 真机：点完回到首页要 3–6s（RN 转场 + 首页重绘）。
                    # 慢机上每帧十几秒，这里只取 3 帧——取满 8 帧会把整个
                    # 窗口耗在等待上，后面的日期/搜索全没时间做。
                    for _ in range(3):
                        _sleep(1)
                        _p = dev.dump() or ""
                        if not _left_city_page(_p):
                            page = _p
                            continue          # 还在城市页：继续找
                        if _city_is_set(_p):
                            return True
                        page = _p
                        break                 # 离开却没设成：下一帧重来
            # ② 用搜索框（**唯一回退**）：国际城市、非热门城市、城市页停在
            # 另一档都走这条。真机探针（2026-11-01 22:22，空载 dump≈2.2s）：
            # 点搜索占位行 → 输入「伦敦」→ 点「伦敦（不限机场）」→ 回首页且
            # 到达城市位变伦敦，全程 43s，**不需要碰「国内/国际」档位**。
            # 档位按钮不再点：它会把整个页面换掉（22:06 直接回首页、22:08
            # 落到特价页），两轮失败现场都是这么来的；而搜索在任何档位都能用。
            if not typed:
                box = _find_edit_box(page)
                need_expand = box is None
                if need_expand:
                    # r720：这一版城市页收起时**整页 0 个 EditText**，先点
                    # 搜索占位行把搜索态展开，再轮询等 EditText 出现（实测
                    # 展开动画约 1–2s，取帧太早会读到还没展开的中间态）。
                    # **不能点 `qd_placeholder_v`**：那是页面最顶部整条
                    # （实测 bounds 0,0,1600,110 的容器，竖屏同位置），点它的
                    # 中心等于点返回/状态栏——22:28 真机轨迹 `city,home,city,
                    # home,city` 就是每次展开都把自己点回首页。要的是
                    # `qd_placeholder` 那行文字（搜索行内，点它才展开）。
                    ph = _find_search_placeholder(page)
                    if ph is not None:
                        dev.tap(*_center(ph))
                        box = None
                        for _ in range(3):
                            _sleep(1)
                            _p = dev.dump() or ""
                            if not _on_city_page(_p):
                                # 点占位行把城市页点没了（转场/返回被触发）：
                                # 别再拿首页当城市页找输入框，这一帧直接作废。
                                page = _p
                                break
                            page = _p
                            box = _find_edit_box(page)
                            if box is not None:
                                break
                if box is not None:
                    dev.tap(*_center(box))
                    time.sleep(1)
                    # 输入框可能残留上次文字（真机：`上海上海`），
                    # 先删干净再输入，否则搜出来是「上海上海」。
                    for _ in range(12):
                        dev.keyevent("KEYCODE_DEL")
                    time.sleep(0.5)
                    dev.input_text(city)
                    typed = True
                    time.sleep(2.5)
                    # 输入后重新取页面再找结果
                    continue
            # ③ 搜索结果里点城市行（`上海（不限机场） … SHA`）。
            # 搜索命中的是城市聚合行；机场行（浦东/虹桥）是它的子项，
            # 点机场行也能用，但城市行语义更稳。
            hit = _search_result_row(page, city)
            if hit is None and typed and not _tab_tried:
                # **搜了但没结果 → 很可能是档位残留**（2026-11-04 现场）。
                #
                # 上面那段注释是对的：**无条件**点档位有害（会把整页换掉）。
                # 但"完全不碰档位"在一种情况下会死循环——上一轮跑完国际航线，
                # 城市页停在「国际」档，这一轮国内航线搜"海口"时国际列表里
                # 根本没有它，于是等满 45s/12 帧记 `setcity-timeout-arr`。
                # 实测代价：`app_qunar` 最近三天 170 轮里 125 轮零结果
                # （成功率 26%），失败现场清一色是这个。
                #
                # 所以改成**有条件**切：只在"已经输入过、却一条结果都没有"
                # 时切一次档位，切完重新搜。这样既不动正常的搜索成功路径，
                # 又给出了一条自愈通路。
                _tab_tried = True
                want = _TAB_INTL if _looks_intl_city(city) else _TAB_DOMESTIC
                tab = _find_city_tab(page, want)
                if tab is not None and not _tab_is_selected(page, want):
                    self.logger.info(
                        "[%s] set-city(%s) 搜「%s」无结果，切到「%s」档重试",
                        self.name, side, city, want)
                    dev.tap(*_center(tab))
                    _sleep(2)
                    typed = False          # 允许重新输入
                    time.sleep(1)
                    continue
            if hit is not None and dev.tap(*_center(hit)):
                for _ in range(3):
                    _sleep(1)
                    _p = dev.dump() or ""
                    if not _left_city_page(_p):
                        page = _p
                        continue
                    if _city_is_set(_p):
                        return True
                    page = _p
                    break
        # 30s 走完还停在这里：城市页开着但没选中（档位不对/结果行没出）。
        # 这条最容易「无声失败」——账本只知道 set-city，不知道当时列表长什么样。
        try:
            self.logger.info("[%s] set-city(%s) 轨迹 %s", self.name, side,
                             ",".join(trace[-24:]))
        except Exception:
            pass
        _save_fail_scene("setcity-timeout-" + side, page)
        _save_tap_shot(dev, "timeout-" + side)
        return False

    def _pick_date(self, dev, xml: str, target: str) -> bool:
        """选目标日；成功返回 True（多日期采集的正确性全靠它）。

        三处实测事实（每次踩都导致整轮 0 行或日期串味）：
          1. 首页日期行是**中文**「10月31日」，不是「10.31」；
          2. 点日期行弹出的是**整月网格**（标题 `2026年11月` + 纯数字日
             `1`/`2`… + 每日价格），不是点分日期条；
          3. dump 一次能同时拿到相邻多个月（实测 10/11/12 月都在），
             但屏幕外的月份格子点不到——必须先滚进可视区。
        """
        want_cn = "%d月%d日" % (int(target[5:7]), int(target[8:10]))

        # ① 首页日期行已经是目标日 → 直接算选好。
        # **不能点它**：点日期行是「打开日历」的手势（实测点完就停在
        # 选择日期弹层，首页搜索按钮随之不可见 → no-search-button）。
        #
        # r722：判据必须**只看首页那一行日期位**，不能全文搜 `%d月%d日`。
        # 真机实测：首页日期是 1月29日，而 dump 里同时含日历网格的
        # 「11月16日」候选文案 → 全文搜到就返回 True，于是根本没设日期，
        # 后面把 1月29日 的结果记到 11-16 名下（日期错位价，比缺数据更糟）。
        # 这里按「日期行节点自身文本」比对；拿不到该节点就当作未设置。
        _date_node = _find_id(xml, _ID_DEP_DATE_TV)
        if _date_node is None:
            _date_node = _find_id(xml, _ID_DEP_DATE_LL)
        if _date_node is not None and \
                (_date_node["text"] or "").strip() == want_cn:
            return True

        # ② 打开日历网格
        if "选择日期" not in (xml or ""):
            # 账本实证（2026-11-01）：app_qunar 的 78 条 timeout 里有 33 条
            # 是 `pick-date-failed`，集中在 2027-01-29/30。原实现**只点一次**
            # 日期行，点不中就 return False；而日期行同样是 RN 元素，滚动后
            # 那一帧的坐标会点不中。这里给 2 次尝试（每次 6s，最坏耗时与
            # 原来的 12s 持平）：没等到弹层就用**新 dump 的坐标**再点一次。
            for _try in range(2):
                trigger = None
                for n in _nodes(xml):
                    if re.fullmatch(r"\d{1,2}月\d{1,2}日",
                                    (n["text"] or "").strip()):
                        trigger = n
                        break
                if trigger is None:
                    # 日期行不在视图树：刚跑完低价机票/别的路径复位后，页面
                    # 可能停在「搜索位」（日期行被滚出视图树），也可能是别的
                    # 子页（实测下拉手势会误触首页活动位，打开 HyWebActivity）。
                    # 不做手势，直接 force-stop 重建首页——确定性最高。
                    self._back_to_home(dev)
                    xml = dev.dump() or ""
                    for n in _nodes(xml):
                        if re.fullmatch(r"\d{1,2}月\d{1,2}日",
                                        (n["text"] or "").strip()):
                            trigger = n
                            break
                if trigger is None:
                    return False
                if not dev.tap(*_center(trigger)):
                    xml = dev.dump() or ""
                    continue
                # 弹层是独立 Activity（`RNContainerActivity`），转场 3–6s。
                # 只 sleep(3) 取一帧会读到「还没起来」的中间态，直接判失败
                # （真机：国际档第一次选日 100% 失败，第二次才成功）。
                deadline_open = time.time() + 6
                while time.time() < deadline_open:
                    _sleep(2)
                    xml = dev.dump() or ""
                    if "选择日期" in xml:
                        break
                if "选择日期" in xml:
                    break

        if "选择日期" not in (xml or ""):
            _save_fail_scene("pickdate-open", xml)
            return False

        # ③ 在月份网格里定位并点中（必要时滚动）
        h = (dev.window_size() or (0, 1600))[1] or 1600
        for _ in range(8):
            cell = _month_day_cell(xml, target)
            if cell is not None and 0 < cell["y2"] <= h * 0.94:
                if not dev.tap(*_center(cell)):
                    return False
                _sleep(2)
                # 选完必须核对首页日期行真的换成了目标日：没换时点「搜索」
                # 会重查上一天，结果被打上目标日期——价格错配且毫无异常。
                back = dev.dump() or ""
                if "选择日期" in back:
                    # **弹层没关可恢复**（与智行同一类现场）：按 BACK 关掉再点一次。
                    # 直接放弃会让整条航线白跑（"选不上日期"）。
                    try:
                        from .app_base import dismiss_until_gone
                        gone, back = dismiss_until_gone(dev, "选择日期", tries=1)
                    except Exception:
                        gone = "选择日期" not in back
                    if not gone:
                        return False        # 弹层没关 = 没选上
                    cell2 = _month_day_cell(dev.dump() or "", target)
                    if cell2 is None:
                        return False
                    if not dev.tap(*_center(cell2)):
                        return False
                    _sleep(2)
                    back = dev.dump() or ""
                    if "选择日期" in back:
                        return False
                return _find_text(back, want_cn) is not None
            # 目标月份块还没滚到可视区（或在屏幕外）：朝目标方向滚一屏。
            # 网格只渲染可见区，所以「格子不在」要翻页——但**方向不能赌**：
            # 日历弹层会记住上次停留的月份（2026-11-01 生产现场：目标
            # 2027-01-30，弹层停在「2027年7月/8月」），原实现「未渲染就
            # 往下滑」只会越滑越远，8 次后必然 pick-date-failed。
            if cell is not None and cell["y1"] > h * 0.94:
                dev.swipe(800, 1200, 800, 600, 400)     # 目标在下方
            elif cell is not None:
                dev.swipe(800, 600, 800, 1200, 400)     # 目标在上方
            else:
                _dir = _calendar_scroll_dir(xml, target)
                if _dir == "up":
                    dev.swipe(800, 600, 800, 1200, 400)   # 目标在上方（更早）
                elif _dir == "down":
                    dev.swipe(800, 1200, 800, 600, 400)   # 目标在下方（更晚）
                else:
                    # 目标日在可见区间、却没解析出格子：多在转场中
                    # （现场实证：这一帧 day item 的 bounds 高度是 0）。
                    # 此时**别滑**——滑走反而离开目标位置，等下一帧重量。
                    _sleep(2)
                    xml = dev.dump() or ""
                    if "选择日期" not in xml:
                        _save_fail_scene("pickdate-cell", xml)
                        return False
                    continue
            _sleep(2)
            xml = dev.dump() or ""
            if "选择日期" not in xml:
                _save_fail_scene("pickdate-cell", xml)
                return False
        _save_fail_scene("pickdate-cell", xml)
        return False

    def _search_and_parse(self, dev, target: str, from_city: str = "",
                          to_city: str = ""):
        """点搜索并解析列表。返回 (prices, reason)，reason 见 `_one_date`。"""
        # 点搜索前先滚到「搜索按钮可见」的位置（默认位下按钮不在视图树里）
        xml = self._scroll_home(dev, want="search")
        # 搜索控件有两种落法（同一 div 在不同渲染帧里给 id 或只给文字），
        # 只认 id 会间歇性 `no-search-button`——真机实测过。
        btn = _search_widget(xml)
        if btn is None:
            return [], "no-search-button"
        if not dev.tap(*_center(btn)):
            return [], "tap-search-failed"
        deadline = time.time() + 60
        last = ""
        saw_list_page = False     # 曾确认「列表页打开了」（有起降时刻对）
        tapped_slot = False       # 中间「日期列 + 查价」页只点一次
        while time.time() < deadline:
            time.sleep(4)
            xml = dev.dump() or ""
            if self._is_login_page(xml):
                self.login_suspect = True
                self.path_note("app-login", "login",
                               detail="搜索后要求登录（登录态失效）")
                return [], "login"
            # 中间页（真机 2026-10-30）：点「搜索」不一定直达列表，当前版本
            # 会先到一排日期列（`11.05 周四 / 查价`…），必须再点目标日那列
            # 的「查价」才进航班列表。不认这一页 → 一直等到超时，账本记
            # `no-list-page`，看起来像"渠道没数据"。
            # 点完那一列要等**骨架屏**（灰条占位）渲成真实卡片，实测 10–20s。
            if not tapped_slot and "查价" in xml and \
                    any(_DATE_SLOT_RE.match(n["text"]) for n in _nodes(xml)):
                slot = _date_slot_tap(xml, target)
                if slot is not None:
                    tapped_slot = True
                    dev.tap(*_center(slot))
                    deadline = max(deadline, time.time() + 45)
                    continue
            if detect_state(xml) != "ok":
                # 等待期间**必须处理拦路物**：卡住时不去操作，App 会自己
                # 弹浮层（用户实测「登录后卡在查价、下一步一直不动，就弹
                # 悬浮窗，然后掉登录」）。广告自动关；验证码/人脸只记账
                # 不点击，交给人。
                cleared, block = self._clear_blockers(dev, xml)
                kind = getattr(block, "kind", "")
                if kind:
                    self.path_note("app-blocker", kind,
                                   date=target, detail=block.detail)
                    # 广告已在 _clear_blockers 里自动关掉，继续等；
                    # 验证码/人脸/登录只能人处理，立刻返回并如实入账。
                    if kind in ("captcha", "face", "login"):
                        self.login_suspect = kind in ("login", "captcha")
                        return [], kind
                last = xml
                continue
            saw_list_page = True
            # 列表页要等价格渲染完：有航班号但没价格时再等一轮
            rows = parse_flight_rows(xml)
            if rows and any(r.get("price") for r in rows):
                prices = self._to_prices(rows, target, from_city, to_city)
                if prices:      # _to_prices 可能因价格带不合格返回空
                    return prices, "ok"
            last = xml
        if last:
            rows = parse_flight_rows(last)
            if rows:
                prices = self._to_prices(rows, target, from_city, to_city)
                if prices:
                    return prices, "ok"
                # 价格比航班号晚一拍渲染（骨架屏）：整窗等完后**再等一拍**。
                # 真机 22:36 SHA→LHR 就是「有航班行、一行都不带价」——
                # 慢机上 60s 只够 3 帧，最后那一帧可能仍在骨架屏。多给一次
                # 机会比直接记 no-priced-rows 更接近事实；仍无价就把现场
                # 落盘（`nopriced-<date>`），下一轮不用再猜。
                _sleep(10)
                again = dev.dump() or ""
                rows2 = parse_flight_rows(again) or rows
                prices = self._to_prices(rows2, target, from_city, to_city)
                if prices:
                    return prices, "ok"
                _save_fail_scene("nopriced-" + (target or ""), again or last)
                try:
                    self.logger.info(
                        "[%s] %s 列表 %d 行、带价 %d 行（再等一拍仍无可用价）",
                        self.name, target, len(rows2),
                        sum(1 for r in rows2 if r.get("price")))
                except Exception:
                    pass
                # 解析出了航班行但一行都没有可用价格：这是「解析不到价」，
                # 不是「这天没票」——记 no-priced-rows 更诚实。
                return [], "no-priced-rows"
        # 列表页打开过但确实没航班（或全部无价）→ 这才是 empty；
        # 连列表页都没出现 → 超时，不是「没票」。
        if not saw_list_page:
            # **必须留现场**（2026-11-04）：这条分支原来只返回 `no-list-page`
            # 就结束了，账本上只有一句"未取到可用结果"，**看不出当时在哪一页**
            # —— 是停在首页、还是卡在城市页、还是列表页骨架没渲染。
            # 实测两次 `no-list-page` 各花了 154s/170s 设备时间却查不出原因。
            _save_fail_scene("nolist-" + (target or ""), last)
            try:
                # 一行说清"当时停在哪"：首页标记 / 城市页标记 / 列表页标记
                # 各在不在，比事后打开 8KB 的 dump 快得多。
                _hint = []
                for _lab, _mark in (("首页", "机票查询"),
                                    ("城市页", "搜索国家/城市"),
                                    ("列表页", "选择航班"),
                                    ("登录", "登录")):
                    if _mark in (last or ""):
                        _hint.append(_lab)
                self.logger.info(
                    "[%s] %s 列表页未出现（%d 字，命中：%s），已落现场 nolist",
                    self.name, target, len(last or ""),
                    "/".join(_hint) or "无已知标记")
            except Exception:
                pass
        return [], ("empty" if saw_list_page else "no-list-page")

    def _to_prices(self, rows: List[dict], date: str,
                   from_city: str, to_city: str) -> List[FlightPrice]:
        """该日期全部航班 → **一条** FlightPrice（extra 是航班数组）。

        与其余渠道同一契约：一渠道一日期一行，extra 携带当天全部航班；
        消费端（webui 列表池 / Alerter 推送池）都是按数组读的。
        """
        flights, best = [], None
        for r in rows:
            price = r.get("price")
            if price is None:
                continue
            trans = r.get("trans_city", "")
            item = {"price": float(price),
                    "code": r.get("flight_no", ""),
                    "name": r.get("flight_no", ""),
                    "depDate": date,
                    "depTime": r.get("depart_time", ""),
                    "arrTime": r.get("arrive_time", "")}
            if trans:
                item["transCity"] = trans
            flights.append(item)
            # 行头价取**最低直飞**；全为中转时才退回中转最低（与智行同律：
            # 中转低价顶掉直飞会让「这渠道当天直飞多少钱」凭空变便宜）。
            if trans:
                if best is None or (best.get("transCity")
                                    and price < best["price"]):
                    best = item
            elif best is None or best.get("transCity") or price < best["price"]:
                best = item
        if not flights:
            return []
        return [FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=date, price=best["price"],
            flight_no=best["code"], depart_time=best["depTime"],
            arrive_time=best["arrTime"],
            extra=json.dumps(flights, ensure_ascii=False),
            prov=f"app:{_APP_PKG}:list",
        )]

    # ---------- 低价机票（low_fare 维度） ----------
    #
    # 与 `fetch()` 完全不同的一个问题：`fetch` 问「某天这条航线多少班、
    # 几点、多少钱」，返回明细；`low_fare` 问「**未来一段时间里哪天最便宜**」，
    # 返回每天一条最低价（不带航班号），供特价发现源使用。
    #
    # 页面是真的：首页「低价机票」→ 选好城市 → 「搜索低价机票」，
    # 顶部就是一条日期带，每天下面是当天最低价（真机 2026-10-30：
    # 北京→上海 10.31 ¥410 / 11.01 ¥358 / 11.02 ¥420 …）。
    def low_fare(self, from_city: str, to_city: str,
                 days: int = 14) -> List[dict]:
        """返回 [{date, weekday, price}]（只含有价的日期）。

        失败一律返回 `[]` 并用 `path_note` 写明卡在哪——低价发现源宁可
        空，也不能拿错价冒充（下游会跨渠道核实价格）。
        """
        import datetime as _dt
        rt = self.runtime()
        ok, why = rt.ensure_ready()
        if not ok:
            self.path_note("android-runtime", "unsupported",
                           detail=f"runtime not ready: {why}")
            return []
        dev = rt.device()
        if dev is None:
            self.path_note("android-device", "unsupported",
                           detail="device unavailable")
            return []
        with rt.device_lock(owner=self.name):
            self.prepare_device(dev)
            return self._low_fare_locked(dev, from_city, to_city, days)

    def calendar(self, from_city: str, to_city: str) -> List[dict]:
        """整月日历逐日价（独立于 low_fare 日期带）。

        低价的 6 天/14 天日期带**不能**冒充日历；这里走同一页的「日历」
        弹层，按 `q_flight_calendarDayItem#YYYY-MM-DD` 日格子树解析
        ¥ 价。真机 BJS→SHA 一次解析 **60 天 / 2 个月**
        （2026-11-02..2026-12-31，90.6s）；更远月份在同一日历滚动区，
        当前不继续滚动。`low_fare` 内部会打开日历并把
        `path_note("日历","calendar", rows=<日格数>)` 写入证据链，返回值仅日历行。
        """
        self._calendar_rows = []
        self.low_fare(from_city, to_city, days=14)
        return list(getattr(self, "_calendar_rows", []) or [])

    def _low_fare_locked(self, dev, from_city: str, to_city: str,
                         days: int) -> List[dict]:
        from .app_qunar_lowfare import (is_h5_low_fare_activity,
                                        is_low_fare_page,
                                        parse_full_calendar,
                                        parse_low_fare_strip)
        started = time.time()
        xml = self._ensure_home(dev)
        if not xml:
            self.path_note("app-dump", "timeout", detail="没能打开机票首页")
            return []
        if self._is_login_page(xml):
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="需要手机号登录（去哪儿不登录拿不到任何票价）")
            return []
        # ① 首页「低价机票」入口
        entry = _find_text(xml, "低价机票")
        if entry is None:
            self.path_note("low-fare", "timeout",
                           detail="首页找不到「低价机票」入口")
            return []
        if not dev.tap(*_center(entry)):
            self.path_note("low-fare", "timeout", detail="点击入口失败")
            return []
        _sleep(4)
        xml = dev.dump() or ""
        # ② 低价面板上设城市（它有自己的城市位，复用主流程的选城市）
        from_name = self._city_name(from_city)
        to_name = self._city_name(to_city)
        dep = _find_id(xml, _ID_DEP_CITY) or _find_text(xml, from_name)
        if dep is not None and dep["text"] != from_name:
            if not dev.tap(*_center(dep)):
                self.path_note("low-fare", "timeout", detail="点出发城市失败")
                return []
            _sleep(3)
            xml = dev.dump() or ""
            hit = _pick_city_row(xml, from_name) or _search_result_row(
                xml, from_name)
            if hit is None:
                self.path_note("low-fare", "timeout",
                               detail=f"低价页选不到出发城市 {from_name}")
                return []
            dev.tap(*_center(hit))
            _sleep(3)
            xml = dev.dump() or ""
        arr = _find_id(xml, _ID_ARR_CITY) or _find_text(xml, to_name)
        if arr is not None and arr["text"] != to_name:
            if not dev.tap(*_center(arr)):
                self.path_note("low-fare", "timeout", detail="点到达城市失败")
                return []
            _sleep(3)
            xml = dev.dump() or ""
            hit = _pick_city_row(xml, to_name) or _search_result_row(
                xml, to_name)
            if hit is None:
                self.path_note("low-fare", "timeout",
                               detail=f"低价页选不到到达城市 {to_name}")
                return []
            dev.tap(*_center(hit))
            _sleep(3)
            xml = dev.dump() or ""
        # ③ 点「搜索低价机票」，等日期带出价（实测 10–20s）
        btn = _find_text(xml, "搜索低价机票")
        if btn is None:
            self.path_note("low-fare", "timeout",
                           detail="低价页找不到「搜索低价机票」按钮")
            return []
        dev.tap(*_center(btn))
        _sleep(3)
        try:
            _act = str(dev.current_activity() or "")
        except Exception:
            _act = ""
        if is_h5_low_fare_activity(_act):
            # 结果页已是 WebView：dump 里没有 text 节点，日期带解析器
            # 再等 45s 也读不到。按「这条通路接不上」如实入账，不记
            # timeout（那会让人以为是被风控/网络）。
            self.path_note(
                "low-fare", "unsupported",
                detail=("低价机票结果页是 H5 WebView（%s）：文本不进入"
                        "无障碍树，日期带解析器读不到；真机 2026-11-02 "
                        "北京→广州/上海均显示「暂无航班」"
                        % (_act.split("/")[-1] or _act)))
            return []
        import datetime as _dt
        year = _dt.date.today().year
        rows: List[dict] = []
        deadline = time.time() + 45
        while time.time() < deadline:
            _sleep(4)
            xml = dev.dump() or ""
            if self._is_login_page(xml):
                self.login_suspect = True
                self.path_note("low-fare", "login", detail="查询后要求登录")
                return []
            if not is_low_fare_page(xml):
                continue
            parsed = parse_low_fare_strip(xml, str(year))
            priced = [r for r in parsed if r["price"]]
            if len(priced) >= 2:
                rows = priced
                break
        if not rows:
            self.path_note("low-fare", "timeout",
                           detail="日期带没有出价（可能被拦住或接口未返回）")
            return []
        # 日期带一屏只渲染 6 列（其余在屏幕外）。要 days 天就得往左滑，
        # 每滑一屏合并一次（按日期去重）。实测滑 3 屏能覆盖到第 18 天。
        seen = {r["date"]: r for r in rows}
        _w, _h = dev.window_size() or (900, 1600)
        # 日期条在屏幕最上方（y≈135），横向滑它即可加载后续日期。
        _y = 135 if _h > 1000 else int(_h * 0.09)
        for _ in range(6):
            if len(seen) >= days:
                break
            before = len(seen)
            dev.swipe(int(_w * 0.85), _y, int(_w * 0.12), _y, 500)
            _sleep(3)
            xml = dev.dump() or ""
            if not is_low_fare_page(xml):
                break
            for r in parse_low_fare_strip(xml, str(year)):
                if r["price"] and r["date"] not in seen:
                    seen[r["date"]] = r
            if len(seen) == before:
                break       # 滑到头了（没有新日期）
        rows = self._pick_window(sorted(seen.values(), key=lambda r: r["date"]),
                                 days)
        self._calendar_rows = []
        try:
            cal_btn = _find_text(xml, "日历")
            if cal_btn is None:
                self.path_note("日历", "error",
                               detail="低价页找不到「日历」入口")
            else:
                dev.tap(*_center(cal_btn))
                _sleep(6)
                cal_rows = []
                for _ in range(3):
                    cal_xml = dev.dump() or ""
                    cal_rows = parse_full_calendar(cal_xml)
                    if cal_rows:
                        break
                    _sleep(3)
                if cal_rows:
                    self._calendar_rows = cal_rows
                    months = len({r["date"][:7] for r in cal_rows})
                    self.path_note(
                        "日历", "calendar", rows=len(cal_rows),
                        detail="整月日历逐日价 %s..%s（%d 个月）"
                               % (cal_rows[0]["date"], cal_rows[-1]["date"],
                                  months),
                        ms=int((time.time() - started) * 1000))
                else:
                    self.path_note("日历", "error",
                                   detail="日历弹层已打开但未解析出日期价")
        except Exception as e:
            self.path_note("日历", "error", detail=str(e)[:140])
        self.path_note("low-fare", "ok", rows=len(rows),
                       detail="%d 天最低价" % len(rows),
                       ms=int((time.time() - started) * 1000))
        # 采完必须把 App 送回机票首页：低价页与首页是两条栈，
        # `_ensure_home` 的深链在这里会被 RN 吞掉，紧接着查明细就会
        # 整轮 `pick-date-failed` / `set-city-dep`（真机：同进程里
        # 先跑低价再跑明细 100% 失败）。force-stop 后重建最稳。
        try:
            self._back_to_home(dev)
        except Exception:
            pass
        return rows

    def _hard_reset_home(self, dev) -> str:
        """杀进程重开机票页，返回新 dump（城市控件 id 整片丢失时用）。

        现场实证（debug/scene/qunar_app_20261101_181820_setcity-noid-arr.txt）：
        首页 dump 里城市行的 `resource-id` 整片退化成 `arg`、顶部还挂着上一轮
        的「上海到新加坡的机票」路由头、城市只剩 content-desc「交换出发城市和
        到达城市」——但日期行和「机票查询」都在，`_is_flight_home` 照样判
        「这就是首页」，BACK 退栈救不回来。只有杀掉进程重开才能拿到带
        `atom_flight_*` 的完整首页。**每轮只做一次**（调用方用
        `_home_hard_reset` 把关），避免把「真没这个控件」拖成重启循环。
        """
        try:
            dev.app_stop(_APP_PKG)
        except Exception:
            pass
        _sleep(2)
        try:
            dev.app_start(_APP_PKG)
        except Exception:
            pass
        _sleep(6)
        page = dev.dump() or ""
        if _find_id(page, _ID_DEP_CITY) is None:
            try:
                dev.deep_link(_FLIGHT_HOME_URI)
            except Exception:
                pass
            _sleep(6)
            page = dev.dump() or ""
        return page

    def _back_to_home(self, dev) -> bool:
        """把 App 送回**机票**首页（供 low_fare 之后复位，避免污染明细链路）。

        最容易踩的一点：首页顶部是分段「机票 / 低价机票 / 火车票」，低价
        机票与机票是**同一个 TabHome 的两个分段**——从低价页退栈回到的是
        「低价机票」分段（搜索按钮文案都是「搜索低价机票」、没有日期行），
        `_HOME_MARK` 却照样命中，于是 `_pick_date` 找不到日期入口，整轮
        `pick-date-failed`（真机实测）。所以这里以「看得见日期行」为判据，
        而不是首页容器在不在。
        """
        def _is_flight_home(page: str) -> bool:
            if _HOME_MARK not in page:
                return False
            if "搜索低价机票" in page:
                return False        # 低价机票分段
            return any(re.fullmatch(r"\d{1,2}月\d{1,2}日", n["text"] or "")
                       for n in _nodes(page))

        # ① 先尝试点顶部「机票」分段。**必须排在 BACK 之前**：从低价页
        # 退栈会离开 TabHome，退完再点分段就点不到了（真机：先 BACK 三次
        # 导致 back_to_home 恒 False）。
        page = dev.dump() or ""
        if "搜索低价机票" in page:
            seg = None
            for n in _nodes(page):
                if n["text"] == "机票" and n["id"].endswith("rb_sigle_v2"):
                    seg = n
                    break
            if seg is not None:
                dev.tap(*_center(seg))
                _sleep(3)
                if _is_flight_home(dev.dump() or ""):
                    return True
        if _is_flight_home(page):
            return True
        # ② BACK 退栈
        for _ in range(3):
            if not dev.keyevent("KEYCODE_BACK"):
                break
            _sleep(2)
            page = dev.dump() or ""
            if _is_flight_home(page):
                return True
            if "搜索低价机票" in page:
                seg = None
                for n in _nodes(page):
                    if n["text"] == "机票" and n["id"].endswith("rb_sigle_v2"):
                        seg = n
                        break
                if seg is not None:
                    dev.tap(*_center(seg))
                    _sleep(3)
                    if _is_flight_home(dev.dump() or ""):
                        return True
        if dev.deep_link(_FLIGHT_HOME_URI):
            for _ in range(8):
                _sleep(3)
                if _is_flight_home(dev.dump() or ""):
                    return True
        dev.app_stop(_APP_PKG)
        _sleep(3)
        if not dev.deep_link(_FLIGHT_HOME_URI):
            return False
        for _ in range(15):
            _sleep(3)
            if _is_flight_home(dev.dump() or ""):
                return True
        return False

    @staticmethod
    def _pick_window(rows: List[dict], days: int) -> List[dict]:
        """只保留从今天起的 `days` 天（含今天）。

        日期带会把跨年那几天也渲染出来；不裁剪会让「14 天窗口」变成
        一整年，下游按日期窗聚合时混入远期价。
        """
        import datetime as _dt
        today = _dt.date.today()
        end = today + _dt.timedelta(days=max(1, int(days)) - 1)
        out = []
        for r in rows:
            try:
                d = _dt.date.fromisoformat(r["date"])
            except (TypeError, ValueError):
                continue
            if today <= d <= end:
                out.append(r)
        return out
