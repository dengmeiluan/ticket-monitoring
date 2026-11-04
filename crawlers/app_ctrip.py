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
from .app_ctrip_parse import (calendar_xy, is_calendar, is_city_page,
                              is_form, is_list_page, is_login_wall,
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
        # 冷启动后显式 Activity 可能被系统落到首页：点顶部「机票」宫格。
        tile = _find_flight_tile(page)
        if tile is not None:
            self.logger.info("[%s] 首页点「机票」入口", self.name)
            if dev.tap(*_center(tile)):
                page = _wait_for(dev, is_form, timeout=20)
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
            for yy, mm, cy in parse_months(page):
                if (yy, mm) == (y, m):
                    xy = calendar_xy(cy, y, m, d)
                    if xy is None:
                        return False
                    return bool(dev.tap(*xy))
            dev.swipe(450, 1250, 450, 700, duration_ms=400)
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
        # 目标月不在屏内就上滑；最多 6 次，避免无限滚。
        picked = None
        for _ in range(7):
            months = parse_months(page)
            target_month = next(((yy, mm, cy) for yy, mm, cy in months
                                 if (yy, mm) == (y, m)), None)
            if target_month is not None:
                xy = calendar_xy(target_month[2], y, m, d)
                if xy is not None:
                    picked = xy
                    break
            # 只滚日历主体，避开顶部「仅看直飞」开关。
            dev.swipe(450, 1400, 450, 600, duration_ms=400)
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
        if not ok:
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
            rows = parse_calendar_words(words, today=today)
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
            dev.swipe(450, 1400, 450, 600, duration_ms=350)
            time.sleep(2.0)
            page = dev.dump() or ""
            if not is_list_page(page):
                break
            if len(parse_flight_cards(page)) == 0 and len(merged) >= before:
                break
        return sorted(merged.values(),
                      key=lambda r: (r["dep_time"], r["price"]))
