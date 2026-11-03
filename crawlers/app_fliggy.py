# -*- coding: utf-8 -*-
"""飞猪 App 渠道（com.taobao.trip）。

2026-11-02 真机（MuMu / 900×1600 竖屏）验证：
  * 首页点「机票」→ `TripFlutterActivity` 原生表单；
  * 城市页、日期弹层都是 Flutter 画布：uiautomator/u2 读不到文本，
    但 Windows 自带 zh-Hans-CN OCR 能定位城市/日期/结果；
  * 结果页 OCR 可读出支付价、时刻、机场、航班号（北京→上海 11-16
    实测 07:20 MU5138 ¥370 / 20:45 KN5977 ¥370 / 21:35 FM9102 ¥390）。

边界：只做国内单程；日期只验证到**当月/次月**（更远日期显式
unsupported 交浏览器）；登录/验证码/关不掉的弹层如实停下，不 OCR 猜。
"""
from __future__ import annotations

import calendar
import json
import re
import time
from datetime import date as _date
from typing import List

from core.models import FlightPrice

from .app_base import AppCrawler
from .app_fliggy_parse import parse_form_words, parse_words, pick_best

# 城市页同一个城市常出现两处（热门/历史）；第一个点不中时逐个重试。


_APP_PKG = "com.taobao.trip"
#: 飞猪日历 7 列（周日→周六）在 900×1600 竖屏的列中心
_COLS = (79, 205, 333, 459, 586, 712, 839)
#: 第一个月/第二个月的首行日期中心 y；行距 144
_ROW0 = 551
_ROW_STEP = 144
_MONTH2_ROW0 = 1360
#: 首页「机票」宫格（OCR 找不到时的兜底）
_HOME_FLIGHT = (274, 480)


def _center(box):
    return (box["x"] + box["w"] // 2, box["y"] + box["h"] // 2)


def _phrase_hits(words, phrase, min_y=0):
    """OCR 里所有同名短语的中心点（热门/历史可能各有一条）。"""
    if not phrase:
        return []
    first = phrase[0]
    out = []
    for w in words:
        if w["t"] != first or w["y"] < min_y:
            continue
        got = [w]
        x2 = w["x"] + w["w"]
        y = w["y"]
        for ch in phrase[1:]:
            nxt = None
            for v in words:
                if (v["t"] == ch and abs(v["y"] - y) <= 12
                        and 0 <= v["x"] - x2 <= 55):
                    nxt = v
                    break
            if nxt is None:
                got = []
                break
            got.append(nxt)
            x2 = nxt["x"] + nxt["w"]
        if not got:
            continue
        x1 = min(g["x"] for g in got)
        y1 = min(g["y"] for g in got)
        y2 = max(g["y"] + g["h"] for g in got)
        c = ((x1 + x2) // 2, (y1 + y2) // 2)
        if all(abs(c[0] - o[0]) > 30 or abs(c[1] - o[1]) > 30
               for o in out):
            out.append(c)
    return out


def _find_phrase(words, phrase, min_y=0):
    hits = _phrase_hits(words, phrase, min_y=min_y)
    return hits[0] if hits else None


def _target_xy(year, month, day, month_section):
    """目标日期在日历网格里的坐标；月外/越界返回 None。"""
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    for wi, week in enumerate(weeks):
        for di, val in enumerate(week):
            if val != day:
                continue
            row0 = _ROW0 if month_section == 0 else _MONTH2_ROW0
            y = row0 + wi * _ROW_STEP
            if y > 1560:
                return None
            return (_COLS[di], y)
    return None


class AppFliggyCrawler(AppCrawler):
    name = "app_fliggy"
    package = _APP_PKG
    supports_round_trip = False

    def login_url(self) -> str:
        return ("android://%s?login=phone —— 飞猪 App 手机号登录；"
                "未登录时结果页会要求登录" % _APP_PKG)

    # ---------- OCR ----------
    def _ocr(self, dev):
        from core.android.ocr import ocr_words
        return ocr_words(dev.screencap() or b"")

    def _form(self, dev):
        return parse_form_words(self._ocr(dev))

    def _stable_ocr(self, dev, tries=3):
        """连续两次词块位置一致才返回，避开城市页开启动画/自动滚动。"""
        prev = None
        words = []
        for _ in range(tries):
            words = self._ocr(dev)
            sig = tuple((w["t"], w["x"], w["y"]) for w in words)
            if prev is not None and sig == prev:
                return words
            prev = sig
            time.sleep(1.0)
        return words

    def _wait_form(self, dev, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            page = self._form(dev)
            if page.get("dep") and page.get("arr"):
                return page
            time.sleep(1.5)
        return {}

    # ---------- 入口 ----------
    def _denied(self, dev, act=""):
        """飞猪安全容器/访问拒绝页：不绕过，显式 blocked 后停手。"""
        if not act:
            try:
                act = str(dev.current_activity() or "")
            except Exception:
                act = ""
        if "ContainerActivity" not in act:
            return False
        txt = "".join(w["t"] for w in self._ocr(dev))
        if "访问被拒绝" in txt or "反馈" in txt or not txt:
            self.path_note(
                "app-block", "blocked",
                detail="飞猪返回「访问被拒绝」安全页；需人工打开 App 处理后再采集")
            return True
        return False

    def _ensure_form(self, dev):
        try:
            act = str(dev.current_activity() or "")
        except Exception:
            act = ""
        if self._denied(dev, act):
            return None
        if "TripFlutterActivity" in act:
            form = self._wait_form(dev, timeout=6)
            if form:
                return form
            # 停在结果页：先按返回回表单，避免白冷启一次。
            for _ in range(2):
                dev.keyevent("BACK")
                form = self._wait_form(dev, timeout=8)
                if form:
                    return form
        dev.app_stop(self.package)
        time.sleep(1.0)
        # 飞猪的 HomeActivity 不能显式 am start（实测不落前台），必须走
        # launcher；启动页/广告时长不定，等到 Home 或上次的任务页出现。
        dev.app_start(self.package)
        home_deadline = time.time() + 24
        while time.time() < home_deadline:
            try:
                act = str(dev.current_activity() or "")
            except Exception:
                act = ""
            if "HomeActivity" in act or "TripFlutterActivity" in act:
                break
            if self._denied(dev, act):
                return None
            low = act.lower()
            if "webview" in low or "adactivity" in low or "splash" in low:
                # 启动广告/营销 WebView：返回首页，别让坐标点在广告上。
                dev.keyevent("BACK")
                time.sleep(2)
                continue
            time.sleep(1.5)
        if "TripFlutterActivity" in act:
            form = self._wait_form(dev, timeout=6)
            if form:
                return form
            for _ in range(2):
                dev.keyevent("BACK")
                form = self._wait_form(dev, timeout=8)
                if form:
                    return form
        time.sleep(3)
        xy = None
        for _ in range(2):
            words = self._ocr(dev)
            # 首页里「机票」先出现在营销 banner（y≈150），宫格在 y≈460；
            # 只认下半屏的宫格，避免点到「50元机票红包」。
            xy = _find_phrase(words, "机票", min_y=280)
            if xy:
                break
            time.sleep(3)
        dev.tap(*(xy or _HOME_FLIGHT))
        deadline = time.time() + 25
        retried = False
        while time.time() < deadline:
            try:
                act = str(dev.current_activity() or "")
            except Exception:
                act = ""
            if "TripFlutterActivity" in act:
                form = self._wait_form(dev, timeout=12)
                if form:
                    return form
                break
            if "webview" in act.lower():
                dev.keyevent("BACK")
                time.sleep(2)
                continue
            if "HomeActivity" in act and not retried and \
                    time.time() > deadline - 16:
                dev.tap(*_HOME_FLIGHT)
                retried = True
            time.sleep(2)
        self.path_note("app-form", "timeout",
                       detail="首页点机票后未到 Flutter 表单")
        try:
            dev.app_stop(self.package)
        except Exception:
            pass
        return None

    # ---------- 城市 ----------
    def _set_city(self, dev, city, side):
        form = self._form(dev)
        field = "dep" if side == "dep" else "arr"
        if form.get(field) == city:
            return True
        xy = form.get(field + "_xy")
        if not xy:
            self.path_note("app-city", "timeout",
                           detail="表单未找到%s城市位" % ("出发" if side == "dep" else "到达"))
            return False
        dev.tap(*xy)
        time.sleep(3.5)
        words = self._stable_ocr(dev)
        hits = _phrase_hits(words, city)
        if not hits:
            # 城市页搜索框：OCR 文案「搜索机场/城市/国家 中英文或拼音」
            box = _find_phrase(words, "搜索机场") or _find_phrase(words, "搜索")
            if box is None:
                self.path_note("app-city", "timeout",
                               detail="点城市位后未打开城市页/找不到搜索框")
                return False
            dev.tap(*box)
            time.sleep(1)
            dev.input_text(city)
            time.sleep(2)
            words = self._ocr(dev)
            hits = _phrase_hits(words, city)
        if not hits:
            self.path_note("app-city", "empty",
                           detail="城市页 OCR 未找到 %s" % city)
            return False
        # 只点一次：多点会把表单上的日期/最近搜索一起改掉。点错就如实失败，
        # 下一轮重新打开城市页，避免在一次失败里把状态越改越乱。
        dev.tap(*hits[0])
        time.sleep(3)
        form = self._wait_form(dev, timeout=10)
        if form.get(field) == city:
            return True
        self.path_note("app-city", "timeout",
                       detail="选完城市未回表单/城市位未变（%s，实际 %s）"
                              % (city, form.get(field) or "未回表单"))
        return False

    # ---------- 日期 ----------
    def _pick_date(self, dev, target):
        form = self._form(dev)
        try:
            y, m, d = map(int, target.split("-"))
        except ValueError:
            self.path_note("app-date", "unsupported",
                           detail="日期格式不是 YYYY-MM-DD：%s" % target)
            return False
        want = "%d月%d日" % (m, d)
        if want in (form.get("date_text") or ""):
            return True
        if not form.get("date_xy"):
            self.path_note("app-date", "timeout", detail="表单未找到日期位")
            return False
        today = _date.today()
        months = [(today.year, today.month)]
        ny, nm = (today.year + (today.month // 12),
                  today.month % 12 + 1)
        months.append((ny, nm))
        if (y, m) not in months:
            self.path_note(
                "app-date", "unsupported",
                detail="App 日历只验证到当月/次月，%s 交浏览器" % target)
            return False
        section = months.index((y, m))
        if section != 0:
            # 次月/更远：首屏点选未复验成功（会点到别的日期），
            # 不拿未验证路径冒充支持，直接交浏览器。
            self.path_note(
                "app-date", "unsupported",
                detail="App 日历只验证当月，%s 交浏览器" % target)
            return False
        xy = _target_xy(y, m, d, section)
        if xy is None:
            self.path_note("app-date", "unsupported",
                           detail="日历格不在首屏（%s）" % target)
            return False
        dev.tap(*form["date_xy"])
        time.sleep(2.5)
        dev.tap(*xy)
        time.sleep(3)
        form = self._wait_form(dev, timeout=10)
        if want in (form.get("date_text") or ""):
            return True
        self.path_note("app-date", "timeout",
                       detail="点日历后日期未变（%s）" % target)
        return False

    # ---------- 查询 / 解析 ----------
    def _one_date(self, dev, from_city, to_city, target):
        started = time.time()
        if not self._pick_date(dev, target):
            return None
        form = self._form(dev)
        if not form.get("search_xy"):
            self.path_note("app-search", "timeout", detail="找不到搜索按钮")
            return None
        dev.tap(*form["search_xy"])
        deadline = time.time() + 45
        rows = []
        words = []
        while time.time() < deadline:
            time.sleep(3)
            words = self._ocr(dev)
            txt = "".join(w["t"] for w in words)
            rows = parse_words(words, from_city, to_city, target)
            if rows:
                break
            if "访问被拒绝" in txt:
                self.path_note(
                    "app-block", "blocked",
                    detail="飞猪返回「访问被拒绝」安全页；需人工处理后再采集")
                return None
            if "登录" in txt or "验证码" in txt:
                self.login_suspect = True
                self.note_date(target, [], "login",
                               ms=int((time.time() - started) * 1000))
                return None
        if not rows:
            self.note_date(target, [], "结果页 OCR 未解析出航班",
                           ms=int((time.time() - started) * 1000))
            return None
        best = pick_best(rows)
        self.note_date(target, rows, "ok",
                       ms=int((time.time() - started) * 1000))
        self.logger.info("[%s] %s 明细 %d 条 · 最低 ￥%.0f",
                         self.name, target, len(rows), best["price"])
        return FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=target, price=float(best["price"]),
            airline=str(best.get("airline") or "")[:20],
            flight_no=str(best.get("flight_no") or ""),
            depart_time=str(best.get("dep_time") or ""),
            arrive_time=str(best.get("arr_time") or ""),
            extra=json.dumps(rows, ensure_ascii=False))

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        if ret_date:
            self.path_note("TRIP", "unsupported",
                           detail="飞猪 App 往返尚未验证；走 PC/H5")
            return []
        from core.android.ocr import available as _ocr_ready
        if not _ocr_ready():
            self.path_note(
                "android-ocr", "unsupported",
                detail="Windows OCR 不可用（需 PowerShell + zh-Hans-CN）")
            return []
        rt = self.runtime()
        ok, why = rt.ensure_ready()
        if not ok:
            self.path_note("android-runtime", "unsupported",
                           detail="runtime not ready: %s" % why)
            return []
        dev = rt.device()
        if dev is None:
            self.path_note("android-device", "unsupported",
                           detail="device unavailable")
            return []
        with rt.device_lock():
            self.prepare_device(dev)
            if self._ensure_form(dev) is None:
                return []
            if not self._set_city(dev, self._city_name(from_city), "dep"):
                return []
            if not self._set_city(dev, self._city_name(to_city), "arr"):
                return []
            out = []
            for target in dates:
                # 单日隔离：一天抛异常不再拖垮整段
                got = self.date_guard(
                    target, self._one_date, dev, from_city, to_city, target)
                if got:
                    out.append(got)
                # 回表单，供下一个日期继续
                try:
                    dev.keyevent("BACK")
                    time.sleep(2)
                except Exception:
                    pass
            return out
