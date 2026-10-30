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
# 城市页里**不该点**的分区标题：其下方的同名城市是「历史选择」，点它
# 不生效（页面不关、城市不变），却会让调用方以为选好了。
_CITY_HISTORY_MARK = "历史选择"


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
        if not b:
            continue
        out.append({"text": (t.group(1) if t else "").strip(),
                    "id": (r.group(1) if r else ""),
                    "x1": int(b.group(1)), "y1": int(b.group(2)),
                    "x2": int(b.group(3)), "y2": int(b.group(4))})
    return out


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


def _find_edit_box(xml: str):
    """城市页的搜索输入框（按 class 取，不猜文案）。

    输入框的文字是占位符「搜索国家/城市/景点等」，点它这一排 TextView
    不一定聚焦；真正的 EditText 才是可输入的。
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


def _search_result_row(xml: str, city: str):
    """搜索结果里的城市行：`上海（不限机场）  上海  中国  SHA`。

    真机 search 命中后会给一行「城市名（不限机场）」，下面是机场子项。
    按 `city` 前缀 + 「不限机场」/三字码定位，避免点到机场行。
    """
    for n in _nodes(xml):
        t = n["text"] or ""
        if t.startswith(city) and ("不限机场" in t or "SHA" in t):
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
    """
    want = "%d.%02d" % (int(target[5:7]), int(target[8:10]))
    nodes = _nodes(xml)
    slot = None
    for n in nodes:
        if n["text"] == want:
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

        with rt.device_lock():
            # 统一前置（登录态恢复 → 清权限框 → 清 ANR），与其它 App 渠道同源
            self.prepare_device(dev)
            return self._fetch_locked(dev, from_city, to_city, dates)

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
        return "请输入手机号" in (xml or "") or "获取验证码" in (xml or "")

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
            try:
                from core.intl import is_intl_route
                intl = bool(is_intl_route(from_city, to_city))
            except Exception:
                intl = False
            if not self._set_city(dev, xml, from_name, side="dep", intl=intl):
                self.logger.info("[%s] 设出发城市失败：%s", self.name,
                                 from_name)
                return [], "set-city-dep"
            # 选完城市会回到首页，这里直接读页面即可。**不要再调
            # `_ensure_home`**：它为了「不在首页」会先按 3 次 BACK、再等
            # 25s 深链，实测一次要 33s；三个步骤各调一次就把 60s 搜索窗口
            # 吃光，整轮 0 行（真机踩过）。
            if not self._set_city(dev, dev.dump() or "", to_name, side="arr",
                                  intl=intl):
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

    def _set_city(self, dev, xml: str, city: str, side: str,
                  intl: bool = False) -> bool:
        """点城市位 → 在城市选择页选城市（支持国际）。

        城市选择页实测结构：两个 tab「国内/港澳台」「国际」+ 一个
        「搜索国家/城市/景点等」输入框。热门城市列表只覆盖国内大城市，
        **国际城市（如东京）只有搜索框能选到**——所以顺序是：
        先看当前列表有没有同名，没有就用搜索框输入。

        **选中必须校验「离开了城市页」**：页面自带「历史选择」区，里面
        就有刚用过的同名城市（真机：`历史选择 / 清除 / 上海`）。按文案
        `find(city)` 会先命中它，点下去等于什么都没选，函数却返回 True——
        随后 `_pick_date` 拿到的仍是城市页，日历打不开，整轮报
        `pick-date-failed` 而账本上看不出卡在哪。
        """
        rid = _ID_DEP_CITY if side == "dep" else _ID_ARR_CITY
        node = _find_id(xml, rid)
        if node is None:
            return False
        if node["text"] == city:
            return True
        if not dev.tap(*_center(node)):
            return False

        def _left_city_page(page: str) -> bool:
            return bool(page) and _CITY_PAGE_MARK not in page

        deadline = time.time() + 30
        typed = False
        switched = False
        while time.time() < deadline:
            time.sleep(2)
            page = dev.dump() or ""
            # ⓪ 城市页保留上一次的档位：跑过国际之后，国内城市只在
            # 「历史选择」里出现，热门城市列表换成了「东南亚/日韩/欧洲」。
            # 此时按文案必选不中 → 整轮 set-city。**点一次对应档位的 tab**
            # 把列表换回来（真机：点「国内/港澳台」后直接回首页并带出
            # 国内城市，所以点完继续走"是否已离开城市页"的校验）。
            if not switched:
                want_tab = "国际" if intl else "国内/港澳台"
                tab = _find_text(page, want_tab) if intl else None
                if not intl:
                    for n in _nodes(page):
                        if n["text"].startswith("国内"):
                            tab = n
                            break
                if tab is not None:
                    switched = True
                    if dev.tap(*_center(tab)):
                        for _ in range(6):
                            _sleep(1)
                            if _left_city_page(dev.dump() or ""):
                                return True
                        continue
            # ① 当前列表里就有（国内热门城市走这条）。**跳过历史选择区**：
            # 它的坐标在「历史选择」标题之上，点它不生效。
            hit = _pick_city_row(page, city)
            if hit is not None:
                if dev.tap(*_center(hit)):
                    # 真机：点完回到首页要 3–6s（RN 转场 + 首页重绘）。
                    # 只等 2.5s 就取一帧会读到**还在城市页**的中间态，
                    # 被判成「没选上」→ 再点一次 → 整轮 pick-date-failed。
                    # 这里给到 8s，每 1s 取一帧。
                    for _ in range(8):
                        _sleep(1)
                        if _left_city_page(dev.dump() or ""):
                            return True
                    # 点了仍停在城市页：继续找（可能是搜索框还没出结果）
            # ② 用搜索框（国际城市/非热门城市只此一路）
            if not typed:
                box = _find_edit_box(page) \
                    or _find_text(page, "搜索国家", exact=False) \
                    or _find_text(page, "请输入城市", exact=False) \
                    or _find_text(page, "搜索城市", exact=False) \
                    or _find_text(page, "输入城市", exact=False)
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
            if hit is not None and dev.tap(*_center(hit)):
                for _ in range(8):
                    _sleep(1)
                    if _left_city_page(dev.dump() or ""):
                        return True
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
        if _find_text(xml, want_cn) is not None:
            return True

        # ② 打开日历网格
        if "选择日期" not in (xml or ""):
            trigger = None
            for n in _nodes(xml):
                if re.fullmatch(r"\d{1,2}月\d{1,2}日",
                                (n["text"] or "").strip()):
                    trigger = n
                    break
            if trigger is None or not dev.tap(*_center(trigger)):
                return False
            # 弹层是独立 Activity（`RNContainerActivity`），转场 3–6s。
            # 只 sleep(3) 取一帧会读到「还没起来」的中间态，直接判失败
            # （真机：国际档第一次选日 100% 失败，第二次才成功）。
            deadline_open = time.time() + 12
            while time.time() < deadline_open:
                _sleep(2)
                xml = dev.dump() or ""
                if "选择日期" in xml:
                    break

        if "选择日期" not in (xml or ""):
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
                    return False        # 弹层没关 = 没选上
                return _find_text(back, want_cn) is not None
            # 目标月份块还没滚到可视区（或在屏幕外）：朝目标方向滚一屏。
            # 网格**只渲染可见区**（实测 11 月只渲染到 7 号，后面的要滚动
            # 才出现），所以「格子不在」= 往后翻一屏再找，不能往前翻。
            if cell is not None and cell["y1"] > h * 0.94:
                dev.swipe(800, 1200, 800, 600, 400)     # 目标在下方
            elif cell is not None:
                dev.swipe(800, 600, 800, 1200, 400)     # 目标在上方
            else:
                dev.swipe(800, 1200, 800, 600, 400)     # 未渲染：往下找
            _sleep(2)
            xml = dev.dump() or ""
            if "选择日期" not in xml:
                return False
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
                # 解析出了航班行但一行都没有可用价格：这是「解析不到价」，
                # 不是「这天没票」——记 no-priced-rows 更诚实。
                return [], "no-priced-rows"
        # 列表页打开过但确实没航班（或全部无价）→ 这才是 empty；
        # 连列表页都没出现 → 超时，不是「没票」。
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
        with rt.device_lock():
            self.prepare_device(dev)
            return self._low_fare_locked(dev, from_city, to_city, days)

    def _low_fare_locked(self, dev, from_city: str, to_city: str,
                         days: int) -> List[dict]:
        from .app_qunar_lowfare import (is_low_fare_page,
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
        self.path_note("low-fare", "ok", rows=len(rows),
                       detail="%d 天最低价" % len(rows),
                       ms=int((time.time() - started) * 1000))
        return rows

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
