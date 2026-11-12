# -*- coding: utf-8 -*-
"""携程 App 渠道（ctrip.android.view）。

真机事实（MuMu Android 15 / 携程 8.97.0 arm64）：
  * 机票表单可显式拉起：
    `ctrip.android.view/ctrip.business.planthome.CtripPlantHomeActivity`；
  * 表单城市位/日期位带 content-desc（depart city / arrival city /
    depart date），城市页支持中文搜索；
  * **国内列表未登录就能出完整明细**（航班号/时刻/机场/航司/价格），
    列表是 React Native 无障碍树，每个卡片 `第XXX航班…` 的 content-desc
    直接给出字段语义，不需要 OCR；
  * 日历日格是自绘 View，dump 里没有日期/价格文本；但截图经 Windows OCR
    可读逐日价（2026-11-02 17:47 真机截图实证）。`app_ctrip_calendar.py`
    做截图解析，`calendar()/low_fare()` 已端到端复验；能力取值只以
    `core/channels.py::CHANNEL_DIMENSIONS` 为唯一事实源，本注释不重复声明。

与浏览器渠道同一条账本契约：拿不到就记 login/blocked/timeout，
绝不把「没看见」记成「没票」；遇到登录/验证页停下等人。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date as _date, timedelta
from typing import List

from core.models import FlightPrice

from .app_base import AppCrawler
from .base import swipe_design
from .app_ctrip_parse import (calendar_xy, is_calendar, is_city_page,
                              is_form, is_form_page, is_list_page,
                              is_login_wall,
                              login_slot, nodes, parse_city_candidates,
                              parse_flight_cards, parse_form, parse_months)
from .app_ctrip_roundtrip import (build_combos, is_round_trip_form,
                                  is_round_trip_page, is_round_trip_picker,
                                  parse_round_trip, picker_footer,
                                  selected_card)

_APP_PKG = "ctrip.android.view"
_FORM_ACTIVITY = ("ctrip.android.view/"
                  "ctrip.business.planthome.CtripPlantHomeActivity")
_CITY_SEARCH_HINT = "支持搜索城市/国家 中英文或拼音"
_QUERY_TEXT = "查 询"
_CITY_TAB_INTL = "国际/中国港澳台"


def _center(n):
    return n["cx"], n["cy"]


def _find_desc(xml, desc):
    for n in nodes(xml):
        if n["desc"] == desc:
            return n
    return None


def _find_text(xml, want):
    for n in nodes(xml):
        if n["text"] == want:
            return n
    return None


def _screen_w(dev):
    """设备屏幕宽度（读不到返回 None → 调用方按基准宽度算）。"""
    try:
        w, _h = dev.window_size()
        return int(w) or None
    except Exception:
        return None


def cal_scroll_dir(months, y, m):
    """日历该往哪边滚：``"back"``（拉出更早的月份）/``"forward"``。

    抽成纯函数是因为这条判断踩过两次坑（2026-11-06）：
      * 原来只会**前翻**。表单残留远期日期（实测 `2027年2月14日`）时
        日历就开在 2027-02，目标是 2026-11-16 → 永远滚不到，
        报「日历滚动后仍找不到」。
      * 前翻用的滚动坐标还写死成 900×1600 的 `(450,1400)→(450,600)`，
        在 1260×2800 上只滑到上半屏，**首屏之外的所有日期都取不到**。

    ``months`` 是 `parse_months()` 的结果：``[(年, 月, 表头y), ...]``。
    空列表时按"前翻"处理（保留原来的行为，不至于更糟）。
    """
    try:
        vis = [(int(a), int(b)) for a, b, _c in months or []]
    except (TypeError, ValueError):
        return "forward"
    if not vis:
        return "forward"
    if (int(y), int(m)) < min(vis):
        return "back"
    return "forward"


def _calendar_day_cell(xml, header_cy, day, block_bottom=None):
    """在日历 UI 树里找目标「日」的格子中心；找不到返回 None。

    为什么不用 `calendar_xy` 那套常量：它是按 **900×1600** 标定的
    （COL0=66 / STEP=133.3 / ROW=100）。设备改到 1260×2800 之后列宽变成
    1260/7≈180，常量算出来的点会落进**相邻日期**，现场表现就是
    "设日期后日期未变"，账本只记 `app-date timeout`，看不出根因。

    日号在一个月块内是唯一的，所以按文本找格子天然与分辨率无关。
    `block_bottom` 是下一个月块的表头 y（有的话），用它把搜索限制在
    本月内，避免捡到相邻月份里同样的日号。
    """
    want = str(int(day))
    best = None
    for n in nodes(xml or ""):
        if n["text"] != want:
            continue
        if n["cy"] <= float(header_cy):
            continue
        if block_bottom is not None and n["cy"] >= float(block_bottom):
            continue
        if best is None or n["cy"] < best["cy"]:
            best = n
    if best is None:
        return None
    return best["cx"], best["cy"]


def _find_flight_tile(xml):
    """首页的「机票」入口（顶部宫格，y<500）。"""
    cands = [n for n in nodes(xml)
             if n["text"] == "机票" and n["cy"] < 500]
    if not cands:
        return None
    return min(cands, key=lambda n: (n["cy"], abs(n["cx"] - 450)))


def _wait_for(dev, predicate, timeout=30, interval=1.5):
    deadline = time.time() + timeout
    page = ""
    while time.time() < deadline:
        page = dev.dump() or ""
        try:
            if page and predicate(page):
                return page
        except Exception:
            pass
        time.sleep(interval)
    return page


class AppCtripCrawler(AppCrawler):
    name = "app_ctrip"
    package = _APP_PKG
    #: 往返：国际/国内均真机端到端（去/返双栏，去程卡价=页脚往返总价）；
    #: 返程卡可能晚一帧渲染，解析前最多等 10s。
    supports_round_trip = True

    def login_url(self) -> str:
        return ("android://%s?login=phone —— 携程 App 手机号/验证码登录；"
                "国内列表可匿名查看，登录后走账号会话" % _APP_PKG)

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        # 日期超出 App 视野就直接交浏览器（能力边界，记 unsupported）：
        # App 日历只支持近未来，远期日期每条白耗 100–150 秒设备时间。
        if self.early_skip(dates):      # 停服/需登录：不发请求
            return []
        if self.reject_far_dates(dates):
            return []
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
        # 链路闸门（r1063 T9）：**必须在拿设备锁之前**按阶段问——闸门要等
        # 时不能占着设备睡（App 渠道的设备是串行独占的，在锁里等＝让排队
        # 等锁的其它 App 渠道全体陪跑）。一次 fetch 走「登录 → 列表」两段
        # （往返查询走「登录 → 往返」），两段各问一次；被停用的阶段只记
        # `paced` 并交空结果，**不记失败**（记失败会把整家渠道的熔断拉开）。
        if not self.path_gate("app-login", "detail"):
            return []
        if ret_date:
            if not self.path_gate("往返", "round_trip"):
                return []
        elif not self.path_gate("app-list", "detail"):
            return []
        with rt.device_lock(owner=self.name):
            self.prepare_device(dev)
            self._ensure_app_fresh(dev)
            form = self._ensure_form(dev)
            if form is None:
                return []
            if ret_date:
                return self._fetch_round_trip_locked(
                    dev, from_city, to_city, dates, ret_date)
            if not self._set_one_way_mode(dev):
                return []
            if not self._set_route(dev, from_city, to_city):
                return []
            out: List[FlightPrice] = []
            for date in dates:
                # 单日隔离：一天抛异常不再拖垮整段（其余日期照常出数）
                got = self.date_guard(
                    date, self._one_date, dev, from_city, to_city, date)
                if got:
                    out.append(got)
            return out

    # ---------- 导航 ----------
    def _ensure_form(self, dev):
        """把 App 带到机票表单；失败/登录墙返回 None 并落账。"""
        page = dev.dump() or ""
        if is_form(page):
            return page
        if is_login_wall(page) and _find_flight_tile(page) is None:
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="携程要求登录：%s" % login_slot(page))
            return None
        if not dev.start_component(_FORM_ACTIVITY):
            # 显式 Activity 失败时退回首页再点「机票」
            self.logger.info("[%s] 显式启动机票页失败，回退首页", self.name)
            dev.app_start(_APP_PKG)
            page = _wait_for(
                dev, lambda x: x and not is_form(x), timeout=15)
        page = dev.dump() or ""
        if is_form(page):
            return page
        # **显式启动"看起来成功"但页面不是表单时，必须先冷启动回首页**
        # （2026-11-05 实测）。
        #
        # 现场：`start_component` 返回真，但落到的是一张 75 节点的半开页
        # （既不是表单也不是登录墙），在这张页上找「机票」宫格点到的是
        # 别的东西，然后干等 20 秒超时——整轮 0 条。
        # 而**先 force-stop 再 monkey 冷启动 → 等首页 → 点宫格**这条路径
        # 是稳定可用的（实测 260 节点、is_form=True，5 秒内到表单）。
        #
        # 判据：页面里既没有表单标记、也不是首页宫格时，说明当前界面是
        # "别人留下的中间态"，最便宜的处置就是重来一次。
        if is_form_page(page) is False and _find_flight_tile(page) is None:
            self.logger.info("[%s] 当前页非表单也非首页，冷启动重来", self.name)
            try:
                dev.app_stop(_APP_PKG)
            except Exception:
                pass
            time.sleep(1.5)
            dev.app_start(_APP_PKG)
            page = _wait_for(
                dev, lambda x: x and _find_flight_tile(x) is not None,
                timeout=25)
        # 冷启动后显式 Activity 可能被系统落到首页：点顶部「机票」宫格。
        #
        # **要点两轮**（2026-11-05 实测）：冷启动 ~14s，`prepare_device`
        # 里的 `_ensure_own_app` 只等 2.5s 就返回，此时首页常常还在加载
        # 骨架——骨架里已经有「机票」节点，但那次点击**落在未就绪的控件上
        # 无效**，于是干等 20s 超时。隔离测试里我等了 15s 再点，5 秒就到表单，
        # 差别就在这里。
        for attempt in range(2):
            tile = _find_flight_tile(page)
            if tile is None:
                break
            if attempt:
                # 第二轮前先让首页稳定下来
                time.sleep(2.5)
                page = dev.dump() or ""
                tile = _find_flight_tile(page)
                if tile is None:
                    break
            self.logger.info("[%s] 首页点「机票」入口（第 %d 次）",
                             self.name, attempt + 1)
            if dev.tap(*_center(tile)):
                page = _wait_for(dev, is_form, timeout=20)
            if is_form(page):
                return page
            # 没进表单：可能点了空骨架，或落到了中间页 → 重新取页面再来一次
            page = dev.dump() or ""
            if is_form(page):
                return page
        if is_form(page):
            return page
        if is_login_wall(page) and _find_flight_tile(page) is None:
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="携程要求登录：%s" % login_slot(page))
            return None
        self.path_note("app-form", "timeout",
                       detail="40s 内未到机票表单页（不是表单/登录墙，"
                              "首页入口也点不进去）")
        # 失败时别把 Ctrip 留在前台：同一台设备还要串行跑其它 App 渠道，
        # 抢前台会让下一个渠道的 app_start 被忽略（2026-11-02 实测）。
        try:
            dev.app_stop(self.package)
        except Exception:
            pass
        return None

    def read_route(self, dev):
        try:
            form = parse_form(dev.dump() or "")
        except Exception:
            return None
        if not form or not form.get("dep") or not form.get("arr"):
            return None
        return (form["dep"], form["arr"])

    def _set_route(self, dev, from_city: str, to_city: str) -> bool:
        dep = self._city_name(from_city)
        arr = self._city_name(to_city)
        try:
            from core.intl import is_intl_route
            intl = bool(is_intl_route(from_city, to_city))
        except Exception:
            intl = False
        if not self._set_city(dev, dep, "depart city", intl=intl):
            return False
        if not self._set_city(dev, arr, "arrival city", intl=intl):
            return False
        self.logger.info("[%s] 航线已设：%s→%s", self.name, dep, arr)
        return True

    def _set_city(self, dev, city: str, desc: str, intl: bool = False) -> bool:
        started = time.time()
        page = dev.dump() or ""
        slot = _find_desc(page, desc)
        if slot is None:
            self.path_note("app-city-%s" % desc.split()[0], "timeout",
                           detail="表单找不到城市位（%s）" % desc)
            return False
        if city in (slot["text"] or ""):
            return True
        if not dev.tap(*_center(slot)):
            return False
        page = _wait_for(dev, is_city_page, timeout=12)
        if not is_city_page(page):
            # 转场动效会吞第一次点击（真机 SHA→CAN 第三次复验踩到）；
            # 重取当前表单再点一次，不拿旧页面硬猜。
            page = dev.dump() or ""
            slot = _find_desc(page, desc)
            if slot is not None:
                dev.tap(*_center(slot))
                page = _wait_for(dev, is_city_page, timeout=12)
        if not is_city_page(page):
            self.path_note("app-city-%s" % desc.split()[0], "timeout",
                           detail="点城市位后重试仍未打开城市页")
            return False
        # 国际城市先切「国际/中国港澳台」，再在同一个搜索框里搜。
        intl_tab = _find_desc(page, _CITY_TAB_INTL)
        if intl_tab is None:
            for n in nodes(page):
                if n["text"] == _CITY_TAB_INTL:
                    intl_tab = n
                    break
        # 搜索框：优先按占位文案找，找不到退回顶部固定坐标。
        box = _find_desc(page, _CITY_SEARCH_HINT)
        if box is None:
            box = _find_text(page, _CITY_SEARCH_HINT)
        if box is None:
            box = {"cx": 205, "cy": 265}
        if intl and intl_tab is not None:
            dev.tap(*_center(intl_tab))
            time.sleep(1)
            page = dev.dump() or ""
        if not dev.tap(box["cx"], box["cy"]):
            self.path_note("app-city-%s" % desc.split()[0], "timeout",
                           detail="点城市搜索框失败")
            return False
        time.sleep(1)
        if not dev.input_text(city):
            self.logger.warning("[%s] 城市搜索输入未确认：%s", self.name, city)
        page = _wait_for(
            dev, lambda x: bool(parse_city_candidates(x, city)), timeout=12)
        cands = parse_city_candidates(page, city)
        if not cands:
            # 没输进去/无搜索结果：退回热门城市格（仅对热门城市有效）
            hit = _find_text(page, city)
            cands = [hit] if hit is not None else []
        if not cands:
            self.path_note("app-city-%s" % desc.split()[0], "empty",
                           detail="城市页未找到 %s" % city)
            return False
        if not dev.tap(cands[0]["cx"], cands[0]["cy"]):
            return False
        page = _wait_for(dev, is_form, timeout=15)
        form = parse_form(page)
        ok = bool(form and city in (form.get(
            "dep" if desc.startswith("depart") else "arr") or ""))
        if not ok:
            self.path_note("app-city-%s" % desc.split()[0], "timeout",
                           detail="选完城市未回到表单/城市位未变（目标 %s）"
                                  % city,
                           ms=int((time.time() - started) * 1000))
        return ok

    # ---------- 往返 ----------
    def _set_one_way_mode(self, dev) -> bool:
        """单程请求先显式切回单程档：上轮往返查询会把表单留在双日期档，
        继续沿用会出双栏页，`is_list_page` 永远等不到。"""
        page = dev.dump() or ""
        if is_form(page) and not is_round_trip_form(page):
            return True
        tab = _find_text(page, "单程") or _find_desc(page, "单程")
        if tab is None:
            return True          # 表单没有档位开关时沿用默认单程
        if not dev.tap(*_center(tab)):
            return False
        page = _wait_for(
            dev, lambda x: is_form(x) and not is_round_trip_form(x),
            timeout=10)
        if not (is_form(page) and not is_round_trip_form(page)):
            self.path_note("app-form", "timeout",
                           detail="点「单程」后未回到单程表单")
            return False
        return True

    def _fetch_round_trip_locked(self, dev, from_city, to_city, dates,
                                 ret_date):
        """往返：切档 → 设城市/双日期 → 查询 → 读去程卡+当前返程。

        去程卡价格就是页脚「往返总价」；返程小卡是差价，绝不相加。
        """
        started = time.time()
        dep_date = (dates or [""])[0]
        if not dep_date or not ret_date:
            self.path_note("TRIP", "unsupported",
                           detail="往返需要去程日与返程日各一个")
            return []
        if not self._set_round_trip_mode(dev):
            return []
        if not self._set_route(dev, from_city, to_city):
            return []
        if not self._pick_round_trip_dates(dev, dep_date, ret_date):
            return []
        page = dev.dump() or ""
        btn = _find_desc(page, "do inquire") or _find_text(page, _QUERY_TEXT)
        if btn is None:
            self.path_note("app-search", "timeout",
                           detail="往返表单找不到查询按钮")
            return []
        if not dev.tap(*_center(btn)):
            self.path_note("app-search", "timeout", detail="点查询失败")
            return []
        page = _wait_for(dev, is_round_trip_page, timeout=45)
        if not is_round_trip_page(page):
            self.note_date(dep_date, [], "往返结果页未打开",
                           ms=int((time.time() - started) * 1000))
            return []
        # 返程栏可能比去程卡晚一帧渲染；等它出现再解析，避免只有总价
        # 没有返程时刻。等不到仍按页面总价落账，但标记 retLoaded=false。
        deadline = time.time() + 10
        parsed = parse_round_trip(page)
        while time.time() < deadline and not (parsed and parsed.get("back")):
            time.sleep(1.0)
            page = dev.dump() or ""
            parsed = parse_round_trip(page)
        if not parsed or not parsed.get("go"):
            self.note_date(dep_date, [], "往返页未读到去程卡",
                           ms=int((time.time() - started) * 1000))
            return []
        combos = build_combos(parsed, dep_date, ret_date)
        if not combos:
            self.note_date(dep_date, [], "往返页去程卡无价格",
                           ms=int((time.time() - started) * 1000))
            return []
        sel = selected_card(parsed.get("go") or [], parsed.get("go_sel"))
        footer = parsed.get("footer_total")
        if (footer is not None and sel.get("price") is not None
                and abs(float(footer) - float(sel["price"])) > 1):
            self.logger.warning(
                "[%s] 往返页脚总价 %s 与选中去程卡 %s 不一致；按卡片价落账",
                self.name, footer, sel.get("price"))
        best = min(combos, key=lambda c: c["price"])
        url = f"android://{_APP_PKG}?view=roundtrip"
        price = FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=dep_date, price=float(best["price"]),
            airline=str(best.get("name") or "")[:20],
            flight_no="", depart_time=str(best.get("depTime") or ""),
            arrive_time=str(best.get("arrTime") or ""),
            extra=json.dumps(combos, ensure_ascii=False),
            prov=f"app:{_APP_PKG}:roundtrip")
        ms = int((time.time() - started) * 1000)
        self.path_note("往返", "ok", rows=len(combos), date=dep_date,
                       detail="首屏 %d 条去程 × 当前返程（页面往返总价口径）"
                              % len(combos), ms=ms, url=url)
        self.note_date(dep_date, [price], "ok", ms=ms, url=url)
        self.logger.info("[%s] 往返 %s→%s %s/%s %d 条 · 最低 ￥%.0f",
                         self.name, from_city, to_city, dep_date, ret_date,
                         len(combos), best["price"])
        return [price]

    def _set_round_trip_mode(self, dev) -> bool:
        page = dev.dump() or ""
        if not is_form(page):
            page = _wait_for(dev, is_form, timeout=10)
        if is_round_trip_form(page):
            return True
        tab = _find_desc(page, "往返") or _find_text(page, "往返")
        if tab is None:
            self.path_note("app-form", "timeout",
                           detail="机票表单找不到「往返」档")
            return False
        if not dev.tap(*_center(tab)):
            return False
        page = _wait_for(dev, is_round_trip_form, timeout=10)
        if not is_round_trip_form(page):
            self.path_note("app-form", "timeout",
                           detail="点「往返」后 10s 未出现返程日期位")
            return False
        return True

    def _tap_picker_date(self, dev, page, y, m, d) -> bool:
        for _ in range(5):
            months = parse_months(page)
            for i, (yy, mm, cy) in enumerate(months):
                if (yy, mm) != (y, m):
                    continue
                # **优先从 UI 树里找那一格**（2026-11-05）：
                # `calendar_xy` 用的是按 900×1600 标定的栅格常量
                # （COL0=66 / STEP=133.3 / ROW=100），设备换成 1260×2800 后
                # 列宽变了（1260/7≈180），照常量算出来的点会落进相邻日期，
                # 于是"设日期后日期未变"、整轮 0 条。
                # 日号在一个月块内唯一，按文本找格子天然与分辨率无关。
                bottom = months[i + 1][2] if i + 1 < len(months) else None
                xy = _calendar_day_cell(page, cy, d, bottom)
                if xy is None:
                    xy = calendar_xy(cy, y, m, d, width=_screen_w(dev))
                if xy is None:
                    return False
                return bool(dev.tap(*xy))
            swipe_design(dev, 450, 1250, 450, 700, duration_ms=400)
            time.sleep(1.2)
            page = dev.dump() or ""
            if not is_round_trip_picker(page):
                return False
        return False

    def _pick_round_trip_dates(self, dev, dep_date, ret_date) -> bool:
        started = time.time()
        try:
            dy, dm, dd = map(int, dep_date.split("-"))
            ry, rm, rd = map(int, ret_date.split("-"))
        except ValueError:
            self.path_note("app-date", "unsupported",
                           detail="日期格式不是 YYYY-MM-DD：%s/%s"
                                  % (dep_date, ret_date))
            return False
        page = dev.dump() or ""
        slot = _find_desc(page, "depart date")
        if slot is None:
            self.path_note("app-date", "timeout",
                           detail="往返表单找不到出发日期位")
            return False
        if not dev.tap(*_center(slot)):
            return False
        page = _wait_for(dev, is_round_trip_picker, timeout=15)
        if not is_round_trip_picker(page):
            self.path_note("app-date", "timeout",
                           detail="点日期位后 15s 未打开往返日历")
            return False
        if not self._tap_picker_date(dev, page, dy, dm, dd):
            self.path_note("app-date", "timeout",
                           detail="往返日历滚不到去程 %s" % dep_date)
            return False
        page = dev.dump() or ""
        if not self._tap_picker_date(dev, page, ry, rm, rd):
            self.path_note("app-date", "timeout",
                           detail="往返日历滚不到返程 %s" % ret_date)
            return False
        page = dev.dump() or ""
        want = ("%02d-%02d" % (dm, dd), "%02d-%02d" % (rm, rd))
        got = picker_footer(page)
        if got != want:
            self.path_note("app-date", "timeout",
                           detail="往返日历落点不符：期望 %s/%s，实际 %s/%s"
                                  % (want[0], want[1], got[0] or "?",
                                     got[1] or "?"),
                           ms=int((time.time() - started) * 1000))
            return False
        btn = _find_text(page, "确认") or _find_desc(page, "确认")
        if btn is None:
            self.path_note("app-date", "timeout",
                           detail="往返日历找不到确认按钮")
            return False
        if not dev.tap(*_center(btn)):
            return False
        page = _wait_for(dev, is_round_trip_form, timeout=10)
        if not is_round_trip_form(page):
            self.path_note("app-date", "timeout",
                           detail="确认日期后未回到往返表单")
            return False
        texts = [n["text"] for n in nodes(page)]
        for m, d in ((dm, dd), (rm, rd)):
            want_txt = "%d月%d日" % (m, d)
            if not any(want_txt in t for t in texts):
                self.path_note("app-date", "timeout",
                               detail="表单日期未变为 %s" % want_txt,
                               ms=int((time.time() - started) * 1000))
                return False
        return True

    def _pick_date(self, dev, target: str) -> bool:
        """打开日历并按坐标点目标日期；日期格是自绘 View，没有文本节点。"""
        try:
            y, m, d = map(int, target.split("-"))
        except ValueError:
            self.path_note("app-date", "unsupported",
                           detail="日期格式不是 YYYY-MM-DD：%s" % target)
            return False
        started = time.time()
        page = dev.dump() or ""
        if not is_form(page):
            page = _wait_for(dev, is_form, timeout=10)
        slot = _find_desc(page, "depart date")
        if slot is None:
            self.path_note("app-date", "timeout", detail="表单找不到日期位")
            return False
        if not dev.tap(*_center(slot)):
            return False
        page = _wait_for(dev, is_calendar, timeout=15)
        if not is_calendar(page):
            self.path_note("app-date", "timeout",
                           detail="点日期位后 15s 未打开日历")
            return False
        # 目标月不在屏内就滚；最多 7 次，避免无限滚。
        #
        # **方向要按目标相对可见月份决定**（2026-11-06 修）：
        # 原实现只会向上滑（= 找更晚的月），一旦表单残留的是**远期日期**
        # （实测残留 `2027年2月14日`，日历就开在 2027-02），目标是
        # 2026-11-16 时就永远滚不到，报「日历滚动后仍找不到」。
        # 向下滑才会把更早的月份拉出来（实测下滑 2 次出现 2026年11月）。
        picked = None
        for _ in range(7):
            months = parse_months(page)
            target_month = next(((yy, mm, cy) for yy, mm, cy in months
                                 if (yy, mm) == (y, m)), None)
            if target_month is not None:
                xy = calendar_xy(target_month[2], y, m, d,
                                 width=_screen_w(dev))
                if xy is not None:
                    picked = xy
                    break
            # 只滚日历主体，避开顶部「仅看直飞」开关。
            # **坐标按屏幕比例算**：原来写死 (450,1400)→(450,600) 是
            # 900×1600 的标定值，在 1260×2800 上只滑到上半屏，滚不动日历。
            try:
                _w, _h = dev.window_size() or (900, 1600)
                _w, _h = int(_w), int(_h)
            except Exception:
                _w, _h = 900, 1600
            _cx = int(_w * 0.5)
            _y_hi, _y_lo = int(_h * 0.30), int(_h * 0.80)
            if cal_scroll_dir(months, y, m) == "back":
                dev.swipe(_cx, _y_hi, _cx, _y_lo, duration_ms=400)  # 回翻
            else:
                dev.swipe(_cx, _y_lo, _cx, _y_hi, duration_ms=400)  # 前翻
            time.sleep(1.5)
            page = dev.dump() or ""
            if not is_calendar(page):
                break
        if picked is None:
            self.path_note("app-date", "unsupported",
                           detail="日历滚动后仍找不到 %s" % target)
            return False
        if not dev.tap(*picked):
            return False
        page = _wait_for(dev, is_form, timeout=15)
        form = parse_form(page)
        want = "%d月%d日" % (m, d)
        ok = bool(form and want in (form.get("date") or ""))
        # r1063 T162：自校正重试——实测「要 16 号点到 23 号」正好差一整行。
        # 不猜常量：从表单读出**实际选到的日**，按差几周把 y 上移几行再点。
        if not ok:
            try:
                def _day_of(txt):
                    import re as _re
                    m = _re.search(r"(\d{1,2})月(\d{1,2})日", str(txt or ""))
                    return int(m.group(2)) if m else None

                def _row_step():
                    from crawlers.app_ctrip_parse import (
                        CAL_CALIB, CAL_CALIB_WIDTH, CAL_ROW_STEP)
                    try:
                        _w = float((dev.window_size() or (0, 0))[0] or 0)
                    except Exception:
                        _w = 0.0
                    if _w:
                        return float(CAL_CALIB[2]) * (_w / float(
                            CAL_CALIB_WIDTH))
                    return float(CAL_ROW_STEP)

                _got = _day_of((form or {}).get("date"))
                _weeks = ((_got - int(d)) // 7) if _got is not None else 0
                _step = _row_step()
                for _try in range(2):
                    if not _weeks:
                        break
                    if not dev.tap(*_center(slot)):
                        break
                    _wait_for(dev, is_calendar, timeout=12)
                    _months = parse_months(dev.dump() or "")
                    _tm = next(((yy, mm, cy) for yy, mm, cy in _months
                                if (yy, mm) == (y, m)), None)
                    if _tm is None:
                        break
                    _xy = calendar_xy(_tm[2], y, m, d, width=_screen_w(dev))
                    if _xy is None:
                        break
                    _xy2 = (_xy[0], int(round(_xy[1] - _weeks * _step)))
                    self.logger.info(
                        "[%s] 日期自校正：实际 %s 天，目标 %s 天 → y 上移 %d 行",
                        self.name, _got, d, _weeks)
                    if not dev.tap(*_xy2):
                        break
                    _page2 = _wait_for(dev, is_form, timeout=12)
                    _form2 = parse_form(_page2)
                    _want2 = "%d月%d日" % (m, d)
                    if _form2 and _want2 in (_form2.get("date") or ""):
                        ok = True
                        form = _form2
                        page = _page2
                        break
                    _got = _day_of((_form2 or {}).get("date"))
                    _weeks = ((_got - int(d)) // 7) if _got is not None else 0
            except Exception as _e:
                try:
                    self.logger.warning("[%s] 日期自校正异常：%s", self.name,
                                        str(_e)[:80])
                except Exception:
                    pass
        if not ok:
            # r1063 T161：先取证——把解析结果与页面快照落盘，才看得见到底
            # 是"坐标点歪"还是"还要点确定"。取证不改任何行为。
            try:
                import os as _os
                _d = _os.path.join(str(getattr(self, "user_data_root",
                                               "user_data")), self.name)
                _os.makedirs(_d, exist_ok=True)
                _p = _os.path.join(_d, "app_date_fail_%s.xml"
                                   % str(target).replace("/", "-"))
                with open(_p, "w", encoding="utf-8") as _f:
                    _f.write(page or "")
                self.logger.warning(
                    "[%s] 日期未生效：form.date=%r 目标=%s 坐标=%r 快照=%s",
                    self.name, (form or {}).get("date"), want, picked, _p)
            except Exception:
                pass
            self.path_note("app-date", "timeout",
                           detail="点日历后未回到表单/日期未变（目标 %s）"
                                  % target,
                           ms=int((time.time() - started) * 1000))
        return ok

    # ---------- 价格日历（OCR） ----------
    #
    # 日格是自绘 View，dump 读不到；但真机截图经 Windows OCR 能读到
    # 「2026年11月 / 12月 / 次年1月」和每格 ¥N（2026-11-02 17:47 真机
    # 截图实证）。纯解析在 `app_ctrip_calendar.py`，这里只负责打开
    # 日期弹层、截图、过滤请求窗口。
    def calendar(self, from_city: str, to_city: str,
                 days: int = 62) -> List[dict]:
        from core.android import ocr as _ocr
        if not _ocr.available():
            self.path_note("android-ocr", "unsupported",
                           detail="Windows OCR 不可用（日历价只能截图读）")
            return []
        days = max(1, min(int(days or 62), 62))
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
        # 链路闸门（r1063 T9）：价格日历是一个独立阶段，在拿设备锁之前问。
        if not self.path_gate("app-calendar", "calendar"):
            return []
        with rt.device_lock(owner=self.name):
            self.prepare_device(dev)
            form = self._ensure_form(dev)
            if form is None:
                return []
            if not self._set_route(dev, from_city, to_city):
                return []
            page = dev.dump() or ""
            slot = _find_desc(page, "depart date")
            if slot is None:
                self.path_note("app-date", "timeout",
                               detail="表单找不到日期位")
                return []
            started = time.time()
            dev.tap(*_center(slot))
            page = _wait_for(dev, is_calendar, timeout=15)
            if not is_calendar(page):
                self.path_note("app-calendar", "timeout",
                               detail="点日期位后 15s 未打开价格日历")
                return []
            # **把日历翻回"今天所在月"**（2026-11-06 修）。
            #
            # 日历按**表单当前日期所在月份**打开。生产跑过远期航线后
            # （实测残留 `2027年2月14日`），日历就开在 2027-02；而本方法
            # 只截一张图就读，读完按「今天起 N 天」过滤 → 一条都不剩，
            # 账本却记「OCR 未读到日历价」，把状态问题误记成 OCR 问题。
            # 时间窗口总是从今天起算，所以只要首屏月份晚于今天所在月，
            # 就向下滑回翻（实测下滑即可拉出更早的月份）。
            try:
                _w, _h = dev.window_size() or (900, 1600)
                _w, _h = int(_w), int(_h)
            except Exception:
                _w, _h = 900, 1600
            _today0 = _date.today()
            for _ in range(5):
                _months = parse_months(page)
                if not _months:
                    break
                _first = min((yy, mm) for yy, mm, _cy in _months)
                if _first <= (_today0.year, _today0.month):
                    break
                dev.swipe(int(_w * 0.5), int(_h * 0.30),
                          int(_w * 0.5), int(_h * 0.80), duration_ms=400)
                time.sleep(1.2)
                page = dev.dump() or ""
                if not is_calendar(page):
                    break
            png = dev.screencap()
            if not png:
                self.path_note("android-ocr", "error",
                               detail="日历截图失败")
                return []
            words = _ocr.ocr_words(png)
            if not words:
                self.path_note("android-ocr", "error",
                               detail="OCR 未返回词块（仅 Windows 支持）")
                return []
            from .app_ctrip_calendar import parse_calendar_words
            today = _date.today()
            rows = parse_calendar_words(words, today=today,
                                        width=_screen_w(dev))
            end = today + timedelta(days=days - 1)
            out = []
            for r in rows:
                try:
                    d = _date.fromisoformat(r["date"])
                except ValueError:
                    continue
                if today <= d <= end:
                    out.append(r)
            if not out:
                self.path_note(
                    "app-calendar", "empty",
                    detail="OCR 未读到 %s 起 %d 天的日历价"
                           "（广告遮挡/日期不可售/OCR 漏读）"
                           % (today.isoformat(), days),
                    ms=int((time.time() - started) * 1000))
                return []
            self.path_note("app-calendar", "ok", rows=len(out),
                           detail="携程 App 价格日历 OCR",
                           ms=int((time.time() - started) * 1000))
            self.logger.info("[%s] 日历 %s→%s %s..%s · %d 天有价",
                             self.name, from_city, to_city, out[0]["date"],
                             out[-1]["date"], len(out))
            try:
                dev.keyevent("BACK")
            except Exception:
                pass
            return out

    def low_fare(self, from_city: str, to_city: str,
                 days: int = 14, anchor_ymd: str = "") -> List[dict]:
        """特价雷达发现源：逐日最低价（OCR 日历与明细同一 App 弹层）。"""
        # 链路闸门（r1063 T9）：携程的「低价机票」就是价格日历，同一次设备
        # 交互算**一条路**——所以「低价」与「日历」两个闸门都要放行才跑：
        # 停「低价」只停特价发现源（日历采集照常），停「日历」则两个都停
        # （它真的没有另一条路可走）。每一次都记在各自的名字上，面板上
        # 看得出是哪一档把它停掉的。
        if not self.path_gate("low-fare", "low_fare"):
            return []
        return self.calendar(from_city, to_city, days=days)

    # ---------- 查询 / 解析 ----------
    def _one_date(self, dev, from_city: str, to_city: str, date: str):
        started = time.time()
        if not self._pick_date(dev, date):
            return None
        page = dev.dump() or ""
        btn = _find_text(page, _QUERY_TEXT)
        if btn is None:
            self.path_note("app-search", "timeout", detail="表单找不到查询按钮")
            return None
        if not dev.tap(*_center(btn)):
            self.path_note("app-search", "timeout", detail="点查询失败")
            return None
        page = ""
        deadline = time.time() + 70
        while time.time() < deadline:
            time.sleep(3)
            page = dev.dump() or ""
            if is_login_wall(page) and not parse_flight_cards(page):
                self.login_suspect = True
                self.note_date(date, [], "login",
                               ms=int((time.time() - started) * 1000))
                return None
            if is_list_page(page):
                break
        if not is_list_page(page):
            self.note_date(date, [], "列表页未打开",
                           ms=int((time.time() - started) * 1000))
            return None
        rows = self._collect_rows(dev, page)
        if not rows:
            # 再查一次登录墙（r1063 T85）：登录页常在列表壳之后才盖上来，
            # 竞态下会被上面的轮询漏掉。**记错状态比慢更糟**——
            # "无航班"会让人去改解析，"要登录"才有人去登。
            late = dev.dump() or page
            if is_login_wall(late):
                self.login_suspect = True
                self.note_date(date, [], "login",
                               ms=int((time.time() - started) * 1000))
                self.logger.info("[%s] 列表为空且命中登录墙：%s",
                                 self.name, date)
                return None
            self.note_date(date, [], "列表已打开但无可解析航班",
                           ms=int((time.time() - started) * 1000))
            return None
        best = min(rows, key=lambda r: r["price"])
        self.note_date(date, rows, "ok",
                       ms=int((time.time() - started) * 1000))
        self.logger.info("[%s] %s 明细 %d 条 · 最低 ￥%.0f",
                         self.name, date, len(rows), best["price"])
        return FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=date, price=float(best["price"]),
            airline=str(best.get("airline") or "")[:20],
            flight_no=str(best.get("flight_no") or ""),
            depart_time=str(best.get("dep_time") or ""),
            arrive_time=str(best.get("arr_time") or ""),
            extra=json.dumps(rows, ensure_ascii=False))

    def _collect_rows(self, dev, page: str):
        merged = {}
        for _ in range(4):
            for r in parse_flight_cards(page):
                key = (r["flight_no"], r["dep_time"], r["arr_time"],
                       r.get("airline", ""))
                old = merged.get(key)
                if old is None or r["price"] < old["price"]:
                    merged[key] = r
            before = len(merged)
            swipe_design(dev, 450, 1400, 450, 600, duration_ms=350)
            time.sleep(2.0)
            page = dev.dump() or ""
            if not is_list_page(page):
                break
            if len(parse_flight_cards(page)) == 0 and len(merged) >= before:
                break
        return sorted(merged.values(),
                      key=lambda r: (r["dep_time"], r["price"]))
