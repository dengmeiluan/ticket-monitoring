# -*- coding: utf-8 -*-
"""同程 App 渠道（com.tongcheng.android）。

2026-11-02 真机事实：
  * 机票表单是 Flutter 原生页（`TCELFlutterBoostActivity`），城市/日期/查询
    都在 `content-desc` 里；
  * 点「机票查询」后落 `WebViewActivity`：CLI `uiautomator dump` 因页面持续
    动画报 `could not get idle state`，但 uiautomator2 的 dump 能读到完整文本
    （SHA→PEK 2026-11-16 实测 5 行：MU5185 ¥336/¥373、KN5956 ¥362…）；
  * 结果页可能盖一层「出行提醒」公告（标题 + 底部「知道了」），由
    `app_blockers` 识别并点掉；关不掉时如实停下，不把遮挡记成 empty。

本渠道单程明细 + **国际往返**（2026-11-03 真机）：去程栏行价是
「含税总价」（与当前返程组合后的往返总价），返程栏 `+¥N` 是加价，
底部「已选 … · ¥Z」是整单总价——不把 `+¥N` 当票价、不与单程同比。
往返结果首访可能盖一层「去程 + 返程 = 往返总价」教学浮层，点下一步即可。
价格用 App 列表里的券后价（第二个 ¥ 数字），`extra` 同时保留列表价和
「可优惠约¥N」说明；含税口径 App 未标注，不冒充含税。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date as _date, timedelta
from typing import List

from core.models import FlightPrice

from .app_base import AppCrawler
from .app_tongcheng_parse import (is_calendar, is_form, is_login_wall,
                                  parse_calendar_days, parse_form,
                                  parse_result_rows, parse_round_trip,
                                  parse_round_trip_form)

_APP_PKG = "com.tongcheng.android"
#: 往返页返程栏异步渲染的等待上限（真机 10s 不够；见 _fetch_round_trip_locked）。
_RT_RET_WAIT_S = 30
#: App 日历的远期滚动/月份定位尚不稳定（2027-01 实测 23s 超时）；
#: 超过 60 天直接交浏览器 H5/PC，别让一轮采集空等。
MAX_AHEAD_DAYS = 60
_INITIAL = {
    "上海": "S", "北京": "B", "广州": "G", "深圳": "S", "成都": "C",
    "重庆": "C", "杭州": "H", "南京": "N", "武汉": "W", "西安": "X",
    "长沙": "C", "海口": "H", "三亚": "S", "昆明": "K", "乌鲁木齐": "W",
    "哈尔滨": "H", "青岛": "Q", "大连": "D", "厦门": "X", "福州": "F",
    "济南": "J", "天津": "T", "郑州": "Z", "贵阳": "G", "南宁": "N",
    "桂林": "G", "兰州": "L", "银川": "Y", "西宁": "X", "拉萨": "L",
    "呼和浩特": "H", "太原": "T", "沈阳": "S", "长春": "C", "宁波": "N",
    "温州": "W", "无锡": "W", "常州": "C", "徐州": "X", "合肥": "H",
    "南昌": "N", "珠海": "Z", "汕头": "S", "湛江": "Z", "石家庄": "S",
    "烟台": "Y", "威海": "W",
}
# 城市页字母索引：A-H 在 y=944，J-Z 在 y=1010（900×1600 实测）
_LETTER_XY = {
    "A": (70, 944), "B": (177, 944), "C": (284, 944), "D": (391, 944),
    "E": (498, 944), "F": (605, 944), "G": (712, 944), "H": (819, 944),
    "J": (70, 1010), "K": (177, 1010), "L": (284, 1010), "M": (391, 1010),
    "N": (498, 1010), "P": (605, 1010), "Q": (712, 1010), "R": (819, 1010),
    "S": (70, 1076), "T": (177, 1076), "W": (284, 1076), "X": (391, 1076),
    "Y": (498, 1076), "Z": (605, 1076),
}
# 热门城市格不再写死坐标：2026-11-02 冷启实测网格整体上移/换位，
# 旧表把「上海」点进「成都」，城市位始终不变。按当前页面文本精确匹配。
_DEP_CITY = (224, 466)
_ARR_CITY = (675, 466)
_DATE_SLOT = (244, 562)
# 国际档表单少一行（无国内促销/往返位），日期位坐标与国内不同；
# 2026-11-03 SHA→NRT 真机实测 (200, 576) 可打开价格日历。
_INTL_DATE_SLOT = (200, 576)
_QUERY = (450, 833)
_BACK_TEXTS = ("返回",)
_WEEK_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _weekday_label(d, today) -> str:
    delta = (d - today).days
    if delta in (0, 1, 2):
        return ("今天", "明天", "后天")[delta]
    return _WEEK_CN[d.weekday()]


def _dump(dev) -> str:
    """优先 u2（动画 WebView 的 CLI dump 会卡 idle），失败回 CLI。"""
    try:
        xml = dev.dump_u2()
        if xml:
            return xml
    except Exception:
        pass
    return dev.dump() or ""


def _find_text(xml, want):
    for n in _nodes(xml):
        if n["text"] == want:
            return n
    return None


def _city_hits(xml, city, min_y=620):
    """城市页里与目标城市**完全同名**的格；按出现顺序返回中心点。

    热门城市网格的顺序和行高会随版本/冷启变化（固定坐标曾把上海点成
    成都），所以每次从当前层级里取坐标；同名多格（热门/历史）都给，
    调用方逐个试。
    """
    out = []
    for n in _nodes(xml):
        if n["cy"] <= min_y or n["text"] != city:
            continue
        c = (n["cx"], n["cy"])
        if all(abs(c[0] - x) > 20 or abs(c[1] - y) > 20
               for x, y in out):
            out.append(c)
    return out


def _letter_xy(xml, letter):
    """左侧字母索引格的当前坐标（A/B/…），取不到返回 None。"""
    for n in _nodes(xml):
        if n["text"] == letter and n["cx"] < 140 and n["cy"] > 620:
            return (n["cx"], n["cy"])
    return None


def _find_city_hit(xml, city):
    """城市页里真正的可选城市：跳过顶部「猜你想去」推荐卡（y<600）。"""
    cands = [n for n in _nodes(xml) if n["text"] == city and n["cy"] > 600]
    if not cands:
        return None
    hot = [n for n in cands if 800 <= n["cy"] <= 1200]
    return min(hot or cands, key=lambda n: n["cy"])


def _form_slot(xml, kind, city=""):
    """表单城市/日期位的当前坐标（页面滚动后固定坐标会漂）。"""
    ns = _nodes(xml)
    if kind == "date":
        for n in ns:
            if n["cy"] < 1000 and re.search(r"\d+月\d+日", n["text"]):
                return (n["cx"], n["cy"])
        return None
    hits = [n for n in ns if n["text"] == city and n["cy"] < 1000]
    if not hits:
        return None
    side = [n for n in hits if (n["cx"] < 450 if kind == "dep"
                                else n["cx"] >= 450)]
    n = min(side or hits, key=lambda x: x["cy"])
    return (n["cx"], n["cy"])


def _nodes(xml):
    from .app_tongcheng_parse import nodes
    return nodes(xml)


def _center(n):
    return n["cx"], n["cy"]


def _wait(dev, pred, timeout=20, interval=1.2):
    deadline = time.time() + timeout
    page = ""
    while time.time() < deadline:
        page = _dump(dev)
        try:
            if page and pred(page):
                return page
        except Exception:
            pass
        time.sleep(interval)
    return page


class AppTongchengCrawler(AppCrawler):
    name = "app_tongcheng"
    MAX_AHEAD_DAYS = MAX_AHEAD_DAYS
    package = _APP_PKG
    supports_round_trip = True

    def login_url(self) -> str:
        return ("android://%s?login=phone —— 同程旅行 App 手机号/微信登录；"
                "登录后结果页才稳定出价" % _APP_PKG)

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        try:
            import uiautomator2  # noqa: F401
        except Exception:
            self.path_note(
                "android-u2", "unsupported",
                detail="同程结果页是 WebView；需要可选依赖 uiautomator2，"
                       "未安装时不发起采集")
            return []
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
            if ret_date:
                return self._fetch_round_trip_locked(
                    dev, from_city, to_city, dates, ret_date)
            if not self._set_one_way_mode(dev, from_city, to_city):
                return []
            if not self._set_route(dev, from_city, to_city):
                return []
            out = []
            for date in dates:
                # 单日隔离：一天抛异常不再拖垮整段
                got = self.date_guard(
                    date, self._one_date, dev, from_city, to_city, date)
                if got:
                    out.append(got)
            return out

    # ---------- 导航 ----------
    def _save_scene(self, dev, tag: str):
        """城市页打不开时留现场（dump+截图），下次定位不靠猜。"""
        try:
            import os
            os.makedirs("debug", exist_ok=True)
            xml = _dump(dev)
            with open("debug/tc_scene_%s.xml" % tag, "w",
                      encoding="utf-8", newline="") as f:
                f.write(xml)
            png = dev.screencap()
            if png:
                with open("debug/tc_scene_%s.png" % tag, "wb") as f:
                    f.write(png)
        except Exception:
            pass

    def _ensure_form(self, dev):
        page = _dump(dev)
        if is_form(page):
            return page
        if is_login_wall(page):
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="同程要求登录（页面出现登录表单）")
            return None
        # 上一轮可能停在结果 WebView / 日历 / 出境页；固定坐标会漂。
        # 先冷启一次，拿确定的首页作为起点（登录态在数据目录，不会丢）。
        try:
            dev.app_stop(self.package)
            time.sleep(1.0)
            dev.app_start(self.package)
        except Exception:
            pass
        page = _wait(dev, lambda x: x and ("机票" in x or is_form(x)),
                     timeout=20)
        if is_form(page):
            return page
        if is_login_wall(page):
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="同程要求登录（冷启后出现登录表单）")
            return None
        tile = _find_text(page, "机票")
        if tile is not None:
            dev.tap(*_center(tile))
            page = _wait(dev, is_form, timeout=15)
            if is_form(page):
                return page
        # 从结果 WebView / 其它页退到表单；最多 3 次。
        for _ in range(3):
            if "com.tongcheng.android.module.webapp.WebViewActivity" in \
                    (dev.current_activity() or ""):
                dev.keyevent("BACK")
                time.sleep(2)
                page = _wait(dev, lambda x: is_form(x) or "机票查询" in x,
                             timeout=8)
                if is_form(page):
                    return page
                continue
            # 首页 → 点机票宫格
            tile = _find_text(page, "机票")
            if tile is not None:
                dev.tap(*_center(tile))
                page = _wait(dev, is_form, timeout=15)
                if is_form(page):
                    return page
                break
            dev.app_start(self.package)
            page = _wait(dev, lambda x: is_form(x) or "机票查询" in x,
                         timeout=20)
            if is_form(page):
                return page
        if is_login_wall(page):
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="同程要求登录（页面出现登录表单）")
            return None
        self.path_note("app-form", "timeout",
                       detail="20s 内未到同程机票表单")
        try:
            dev.app_stop(self.package)
        except Exception:
            pass
        return None

    def read_route(self, dev):
        form = parse_form(_dump(dev))
        if not form or not form.get("dep") or not form.get("arr"):
            return None
        return (form["dep"], form["arr"])

    def _set_route(self, dev, from_city: str, to_city: str) -> bool:
        dep = self._city_name(from_city)
        arr = self._city_name(to_city)
        # 表单刚渲染完时点击会被转场/动效吞掉；给一拍再定位。
        time.sleep(1.2)
        page = _dump(dev)
        dep_xy = _form_slot(page, "dep", dep) or _DEP_CITY
        arr_xy = _form_slot(page, "arr", arr) or _ARR_CITY
        if not self._set_city(dev, dep, dep_xy, "dep"):
            return False
        if not self._set_city(dev, arr, arr_xy, "arr"):
            return False
        form = parse_form(_dump(dev))
        if not form or form.get("dep") != dep or form.get("arr") != arr:
            self.path_note("app-route", "timeout",
                           detail="设完城市后表单未变（目标 %s→%s）"
                                  % (dep, arr))
            return False
        self.logger.info("[%s] 航线已设：%s→%s", self.name, dep, arr)
        return True

    def _set_city(self, dev, city: str, xy, side: str) -> bool:
        started = time.time()
        field = "dep" if side == "dep" else "arr"
        for attempt in range(2):
            form = parse_form(_dump(dev))
            if form and city in (form.get(field) or ""):
                return True
            if attempt and not is_form(_dump(dev)):
                # 上一次停在城市页/结果页：先退回表单再试
                dev.keyevent("BACK")
                time.sleep(1.5)
            if not dev.tap(*xy):
                return False
            page = _wait(dev, lambda x: "热门城市" in x or "猜你想去" in x,
                         timeout=12)
            if "热门城市" not in page and "猜你想去" not in page:
                # 动态节点坐标偶尔点在城市位边缘；用默认表单坐标兜底一次。
                alt = _DEP_CITY if side == "dep" else _ARR_CITY
                if alt != xy:
                    dev.tap(*alt)
                    page = _wait(
                        dev, lambda x: "热门城市" in x or "猜你想去" in x,
                        timeout=12)
            if "热门城市" not in page and "猜你想去" not in page:
                self._save_scene(dev, "city-%s-open" % side)
                self.path_note("app-city", "timeout",
                               detail="点城市位后未打开城市页")
                return False
            # 热门城市格按当前页面文本取坐标：网格顺序/行高会变，
            # 旧固定表曾把「上海」点到「成都」。
            time.sleep(0.6)
            page = _dump(dev)
            targets = _city_hits(page, city)
            if not targets:
                # 城市页顶部搜索框是 Flutter 输入框（u2 不暴露 hint），
                # 按默认弹层坐标点它，直接搜中文城市；比字母索引可靠。
                dev.tap(450, 420)
                time.sleep(1)
                dev.input_text(city)
                time.sleep(2)
                page = _dump(dev)
                hits = [n for n in _nodes(page)
                        if city in n["text"] and n["cy"] > 440
                        and ("机场" in n["text"]
                             or re.search(r"[A-Z]{3}", n["text"]))]
                if hits:
                    hit = min(hits, key=lambda n: n["cy"])
                    targets = [(hit["cx"], hit["cy"])]
            if not targets:
                hit = _find_city_hit(page, city)
                if hit is None:
                    letter = _INITIAL.get(city, "")
                    lxy = _letter_xy(page, letter) if letter else None
                    if lxy or (letter and letter in _LETTER_XY):
                        dev.tap(*(lxy or _LETTER_XY[letter]))
                        time.sleep(1.2)
                        page = _dump(dev)
                        hit = _find_city_hit(page, city)
                if hit is None:
                    self.path_note("app-city", "empty",
                                   detail="城市页未找到 %s（热门/字母索引）"
                                          % city)
                    return False
                targets = [(hit["cx"], hit["cy"])]
            for target in targets:
                dev.tap(*target)
                page = _wait(dev, is_form, timeout=15)
                form = parse_form(page)
                if form and city in (form.get(field) or ""):
                    return True
                # 城市页还开着：换下一个同名候选；已回表单（城市没变）
                # 就停止，避免拿旧城市页坐标往表单上点。
                if is_form(page):
                    break
                page = _dump(dev)
            self.logger.info("[%s] 选城市未生效（%s，第 %d 次）：表单 %s",
                             self.name, city, attempt + 1, form)
        self.path_note("app-city", "timeout",
                       detail="选完城市未回表单/城市位未变（%s）" % city,
                       ms=int((time.time() - started) * 1000))
        return False

    # ---------- 往返 ----------
    @staticmethod
    def _is_domestic(from_city: str, to_city: str) -> bool:
        try:
            from core.citydata import CODE_NAME
            from core.intl import airport_city_code
            return all((airport_city_code(c.upper()) or c.upper())
                       in CODE_NAME for c in (from_city, to_city))
        except Exception:
            return True

    def _tap_form_tab(self, dev, label: str):
        page = _dump(dev)
        for n in _nodes(page):
            if n["text"] == label and n["cy"] < 400:
                dev.tap(n["cx"], n["cy"])
                time.sleep(1.5)
                return _dump(dev)
        return page

    def _set_one_way_mode(self, dev, from_city: str, to_city: str) -> bool:
        """单程请求先清掉上轮往返的返程日：带返程位查询会落双栏往返页。"""
        page = _dump(dev)
        form = parse_round_trip_form(page)
        if not (form and form.get("ret_date")):
            return True
        label = "国内" if self._is_domestic(from_city, to_city) else "国际"
        page = self._tap_form_tab(dev, label)
        form = parse_round_trip_form(page)
        if not (form and not form.get("ret_date")):
            self.path_note("app-form", "timeout",
                           detail="切回%s单程档失败（返程日期仍在）" % label)
            return False
        return True

    def _set_round_trip_mode(self, dev, from_city: str, to_city: str) -> bool:
        """国内走「国内」档（返程位可留空后选），国际走「往返」档。"""
        label = "国内" if self._is_domestic(from_city, to_city) else "往返"
        page = _dump(dev)
        for n in _nodes(page):
            if n["text"] == label and n["cy"] < 400:
                dev.tap(n["cx"], n["cy"])
                time.sleep(1.5)
                page = _dump(dev)
                break
        form = parse_round_trip_form(page)
        if not form:
            self.path_note("app-roundtrip", "timeout",
                           detail="切「%s」档后未回表单" % label)
            return False
        if label == "往返" and not form.get("ret_date"):
            self.path_note("app-roundtrip", "timeout",
                           detail="往返档表单未出现返程日期")
            return False
        self.logger.info("[%s] 往返档：%s", self.name, label)
        return True

    def _range_day_cell(self, page, year: int, month: int, day: int):
        """往返范围日历里目标月的日格；同号日可能带「去程/返程/会员日」前缀。"""
        ns = _nodes(page)
        heads = []
        for n in ns:
            m = re.match(r"^(\d{4})年(\d{1,2})月$", n["text"])
            if m:
                heads.append((int(m.group(1)), int(m.group(2)), n["cy"]))
        heads.sort(key=lambda x: x[2])
        band = None
        for i, (y, mo, cy) in enumerate(heads):
            if (y, mo) == (year, month):
                hi = heads[i + 1][2] if i + 1 < len(heads) else 10 ** 9
                band = (cy, hi)
                break
        if band is None:
            return None
        hits = []
        for n in ns:
            if not (band[0] < n["cy"] < band[1]):
                continue
            parts = [p.strip() for p in re.split(r"[\n ]+", n["text"])
                     if p.strip()]
            if str(day) not in parts:
                continue
            hits.append(n)
        if not hits:
            return None
        priced = [n for n in hits if "¥" in n["text"]]
        n = (priced or hits)[0]
        return (n["cx"], n["cy"])

    def _tap_range_day(self, dev, y, m, d) -> bool:
        page = _dump(dev)
        for _ in range(14):
            cell = self._range_day_cell(page, y, m, d)
            if cell is not None:
                dev.tap(*cell)
                time.sleep(0.9)
                return True
            dev.swipe(450, 1200, 450, 900, duration_ms=320)
            time.sleep(1.0)
            page = _dump(dev)
            if not is_calendar(page):
                return False
        return False

    @staticmethod
    def _rt_footer(page):
        """范围日历页脚：点去程后返程会变「未选择」，返程位允许为空。"""
        for n in _nodes(page):
            if "去程:" not in n["text"] or "返程:" not in n["text"]:
                continue
            m = re.search(r"去程:\s*(\d{1,2})-(\d{1,2})", n["text"])
            if not m:
                continue
            r = re.search(r"返程:\s*(\d{1,2})-(\d{1,2})", n["text"])
            return (int(m.group(1)), int(m.group(2)),
                    int(r.group(1)) if r else None,
                    int(r.group(2)) if r else None)
        return None

    def _pick_round_trip_dates(self, dev, dep_date: str,
                               ret_date: str) -> bool:
        started = time.time()
        try:
            dy, dm, dd = map(int, dep_date.split("-"))
            ry, rm, rd = map(int, ret_date.split("-"))
        except ValueError:
            self.path_note("app-date", "unsupported",
                           detail="日期格式不是 YYYY-MM-DD：%s/%s"
                                  % (dep_date, ret_date))
            return False
        if _date(ry, rm, rd) < _date(dy, dm, dd):
            self.path_note("app-date", "unsupported",
                           detail="返程日早于去程日：%s/%s"
                                  % (dep_date, ret_date))
            return False
        ahead = (_date(dy, dm, dd) - _date.today()).days
        if ahead > MAX_AHEAD_DAYS:
            self.path_note("app-date", "unsupported",
                           detail="距今天 >%d 天的 App 日历定位未稳定，"
                                  "交浏览器 H5/PC" % MAX_AHEAD_DAYS)
            return False
        page = _dump(dev)
        if not is_form(page):
            for _ in range(2):
                dev.keyevent("BACK")
                page = _wait(dev, is_form, timeout=8)
                if is_form(page):
                    break
        if not is_form(page):
            self.path_note("app-date", "timeout",
                           detail="未停在往返表单，无法选日期")
            return False
        slot = next((n for n in _nodes(page)
                     if re.search(r"\d+月\d+日", n["text"])
                     and n["cy"] < 1000 and n["cx"] < 450), None)
        if slot is None:
            self.path_note("app-date", "timeout",
                           detail="往返表单找不到去程日期位")
            return False
        dev.tap(slot["cx"], slot["cy"])
        page = _wait(dev, is_calendar, timeout=15)
        if not is_calendar(page):
            self.path_note("app-date", "timeout", detail="往返日历未打开")
            return False
        if not self._tap_range_day(dev, dy, dm, dd):
            self.path_note("app-date", "timeout",
                           detail="往返日历里找不到去程 %s" % dep_date)
            return False
        foot = self._rt_footer(_dump(dev))
        if not foot or (foot[0], foot[1]) != (dm, dd):
            self.path_note("app-date", "timeout",
                           detail="点去程后页脚未更新（%s）" % (foot,))
            return False
        if not self._tap_range_day(dev, ry, rm, rd):
            self.path_note("app-date", "timeout",
                           detail="往返日历里找不到返程 %s" % ret_date)
            return False
        foot = self._rt_footer(_dump(dev))
        if not foot or (foot[2], foot[3]) != (rm, rd):
            self.path_note("app-date", "timeout",
                           detail="点返程后页脚未更新（%s）" % (foot,))
            return False
        page = _dump(dev)
        btn = next((n for n in _nodes(page)
                    if re.fullmatch(r"确\s*定", n["text"])), None)
        if btn is None or not dev.tap(btn["cx"], btn["cy"]):
            self.path_note("app-date", "timeout", detail="往返日历找不到确定")
            return False
        page = _wait(dev, is_form, timeout=15)
        form = parse_round_trip_form(page)
        want_dep = "%d月%d日" % (dm, dd)
        want_ret = "%d月%d日" % (rm, rd)
        ok = bool(form and want_dep in (form.get("dep_date") or "")
                  and want_ret in (form.get("ret_date") or ""))
        if not ok:
            self.path_note("app-date", "timeout",
                           detail="确认后表单日期未变（%s/%s，目标 %s/%s）"
                                  % ((form or {}).get("dep_date"),
                                     (form or {}).get("ret_date"),
                                     dep_date, ret_date),
                           ms=int((time.time() - started) * 1000))
        return ok

    def _fetch_round_trip_locked(self, dev, from_city, to_city, dates,
                                 ret_date):
        """往返：切档 → 航线/双日期 → 查询 → 解析去程总价 + 返程加价。"""
        started = time.time()
        dep_date = (dates or [""])[0]
        if not dep_date or not ret_date:
            self.path_note("往返", "unsupported",
                           detail="往返需要去程日与返程日各一个")
            return []
        if not self._set_round_trip_mode(dev, from_city, to_city):
            return []
        if not self._set_route(dev, from_city, to_city):
            return []
        if not self._pick_round_trip_dates(dev, dep_date, ret_date):
            return []
        page = _dump(dev)
        btn = _find_text(page, "机票查询")
        if btn is None:
            self.path_note("app-search", "timeout",
                           detail="往返表单找不到查询按钮")
            return []
        dev.tap(*_center(btn))
        parsed = None
        page = ""
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(2)
            page = _dump(dev)
            if is_login_wall(page) and not parse_result_rows(page):
                self.login_suspect = True
                self.note_date(dep_date, [], "login",
                               ms=int((time.time() - started) * 1000))
                return []
            parsed = parse_round_trip(page)
            if parsed:
                break
            # 首访教学浮层「去程 + 返程 = 往返总价」：点它的下一步。
            if "往返总价" in page and ("下一步" in page):
                nxt = next((n for n in _nodes(page)
                            if n["text"].startswith("下一步")), None)
                if nxt is not None:
                    self.logger.info("[%s] 关闭往返教学浮层", self.name)
                    dev.tap(nxt["cx"], nxt["cy"])
                    time.sleep(2)
                    continue
            try:
                from .app_blockers import detect_block
                blk = detect_block(page)
                if blk.kind == "ad" and blk.close_xy:
                    dev.tap(*blk.close_xy)
                    time.sleep(1.5)
            except Exception:
                pass
        if not parsed:
            self.note_date(dep_date, [], "往返结果页未解析出组合",
                           ms=int((time.time() - started) * 1000))
            return []
        # 返程栏比去程行晚很多：真机 21s 的轮次里 10s 还没渲染完，
        # 少了返程就无法标「已选返程/加价」。等去程+页脚+返程都齐（最多 30s），
        # 等不到仍按页面去程行总价落账，但行级写 retLoaded=false。
        until = time.time() + _RT_RET_WAIT_S
        while time.time() < until:
            if parsed.get("returns") and parsed.get("selected_return"):
                break
            time.sleep(1.5)
            page = _dump(dev)
            nxt = parse_round_trip(page)
            if nxt:
                parsed = nxt
        ret_loaded = bool(parsed.get("returns")
                          and parsed.get("selected_return"))
        if not ret_loaded:
            self.logger.warning(
                "[%s] 往返页返程栏未加载完，按去程行总价落账（retLoaded=false）",
                self.name)
        sel_ret = parsed.get("selected_return") or {}
        combos = []
        for ob in parsed["outbounds"]:
            combos.append({
                "tripType": "RT", "backDate": ret_date,
                "flight_no": ob["flight_no"], "airline": ob["airline"],
                "dep_time": ob["dep_time"], "arr_time": ob["arr_time"],
                "arrDate": ob.get("arr_date") or "",
                "dep_airport": ob["dep_airport"],
                "arr_airport": ob["arr_airport"],
                "duration": ob["duration"], "seats": ob.get("seats") or "",
                "price": ob["price"],
                "totalBasis": "page_roundtrip_total",
                "retLoaded": ret_loaded,
                "return_flight": sel_ret.get("flight_no") or "",
                "return_dep": sel_ret.get("dep_time") or "",
                "return_surcharge": sel_ret.get("surcharge"),
            })
        best = min(combos, key=lambda c: c["price"])
        footer = parsed.get("total")
        url = "android://%s?view=roundtrip" % _APP_PKG
        price = FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=dep_date, price=float(best["price"]),
            airline=str(best.get("airline") or "")[:20],
            flight_no=str(best.get("flight_no") or ""),
            depart_time=str(best.get("dep_time") or ""),
            arrive_time=str(best.get("arr_time") or ""),
            extra=json.dumps(combos, ensure_ascii=False),
            prov="app:%s:roundtrip" % _APP_PKG)
        ms = int((time.time() - started) * 1000)
        if ret_loaded:
            tail = "返程 %s 加价 ¥%.0f；%d 条去程 × 当前返程，不与单程同比" % (
                sel_ret.get("flight_no") or "?",
                float(sel_ret.get("surcharge") or 0), len(combos))
        else:
            tail = ("返程栏 30s 未加载完（retLoaded=false），仅按去程行"
                    "「含税总价」落账；%d 条去程，不与单程同比" % len(combos))
        self.path_note(
            "往返", "ok", rows=len(combos), date=dep_date,
            detail="去程行=含税总价（页面往返总价 ¥%s）；%s"
                   % (("%.0f" % footer) if footer else "?", tail),
            ms=ms, url=url)
        self.note_date(dep_date, [price], "ok", ms=ms, url=url)
        self.logger.info("[%s] 往返 %s→%s %s/%s %d 条 · 最低 ￥%.0f",
                         self.name, from_city, to_city, dep_date, ret_date,
                         len(combos), best["price"])
        return [price]

    def _pick_date(self, dev, target: str) -> bool:
        try:
            y, m, d = map(int, target.split("-"))
            _ahead = (_date(y, m, d) - _date.today()).days
        except ValueError:
            self.path_note("app-date", "unsupported",
                           detail="日期格式不是 YYYY-MM-DD：%s" % target)
            return False
        if _ahead > MAX_AHEAD_DAYS:
            self.path_note(
                "app-date", "unsupported",
                detail="距今天 >%d 天的 App 日历定位未稳定，交浏览器 H5/PC"
                       % MAX_AHEAD_DAYS)
            return False
        started = time.time()
        page = _dump(dev)
        if not is_form(page):
            # 同日多日期：上一日查完停在结果 WebView，直接按日期位会点在
            # 结果页上。先返回表单；返回键无效再报错，不拿旧页面硬点。
            for _ in range(2):
                dev.keyevent("BACK")
                page = _wait(dev, is_form, timeout=8)
                if is_form(page):
                    break
        if not is_form(page):
            self.path_note("app-date", "timeout",
                           detail="结果页未退回表单，无法选中下一日期")
            return False
        dev.tap(*(_form_slot(page, "date") or _DATE_SLOT))
        page = _wait(dev, is_calendar, timeout=15)
        if not is_calendar(page):
            self.path_note("app-date", "timeout", detail="日历未打开")
            return False
        # 日历骨架先到、日格文案异步渲染；按目标格轮询，不能只判 is_calendar。
        # 目标月不在首屏（远期日期）时向上滚动日历，再找。
        cell = None
        for _ in range(14):
            for _ in range(4):
                cell = self._day_cell(page, y, m, d)
                if cell is not None:
                    break
                time.sleep(0.8)
                page = _dump(dev)
            if cell is not None:
                break
            # 小步滚动：800px 一次会从 2026-11 直接跳到 2027-11。
            dev.swipe(450, 1200, 450, 900, duration_ms=320)
            time.sleep(1.0)
            page = _dump(dev)
            if not is_calendar(page):
                break
        if cell is None:
            self.path_note("app-date", "unsupported",
                           detail="日历里找不到 %s" % target)
            return False
        dev.tap(*cell)
        page = _wait(dev, is_form, timeout=15)
        form = parse_form(page)
        want = "%d月%d日" % (m, d)
        ok = bool(form and want in (form.get("date") or ""))
        if not ok:
            self.path_note("app-date", "timeout",
                           detail="点日历后未回表单/日期未变（%s）" % target,
                           ms=int((time.time() - started) * 1000))
        return ok

    def _day_cell(self, xml, year: int, month: int, day: int):
        """在「目标月份」的日格范围内找 day；避免跨月同号误点。"""
        ns = _nodes(xml)
        header = None
        nxt = None
        for n in ns:
            m = re.match(r"^(\d{4})年(\d{1,2})月$", n["text"])
            if not m:
                continue
            if (int(m.group(1)), int(m.group(2))) == (year, month):
                header = n
            elif header is not None and n["cy"] > header["cy"]:
                nxt = n
                break
        if header is None:
            return None
        lo = header["cy"]
        hi = nxt["cy"] if nxt is not None else 10 ** 9
        for n in ns:
            if not (lo < n["cy"] < hi):
                continue
            parts = [p.strip() for p in re.split(r"[\n ]+", n["text"])
                     if p.strip()]
            if str(day) in parts and "¥" in n["text"]:
                return (n["cx"], n["cy"])
        return None

    # ---------- 低价日历（calendar / low_fare） ----------
    #
    # 同程 App 的日期弹层是原生「价格日历」：一次渲染 2–3 个月，
    # 每个日格的 content-desc 就是「5\n¥360」。它既能用于选日，也能直接
    # 当作该航线的逐日最低价发现源（与浏览器同程 H5 日历、去哪儿 App
    # 「低价机票」同一契约）。价格口径页面未标注，radar 行标「口径未标注」。
    def _open_calendar(self, dev):
        """点日期位打开价格日历；调用前已确认停在表单，转场期点击会重试。

        国内/国际表单的日期位 y 不同（国际少一行），`_form_slot` 在
        Flutter 树里也可能给出偏移坐标；按候选坐标逐个试，别一次失败就
        退回、把表单关掉。
        """
        page = _dump(dev)
        cands = [_form_slot(page, "date"), _DATE_SLOT, _INTL_DATE_SLOT]
        seen = set()
        for xy in cands:
            if not xy or tuple(xy) in seen:
                continue
            seen.add(tuple(xy))
            dev.tap(*xy)
            page = _wait(dev, is_calendar, timeout=8)
            if is_calendar(page):
                return page
            if not is_form(page):
                dev.keyevent("BACK")
                page = _wait(dev, is_form, timeout=6)
                if not is_form(page):
                    return None
        return None

    def _calendar_window(self, dev, page, anchor, days):
        """读锚点起 days 天内每天的价格；目标月不在首屏时向下滚动。"""
        from .app_tongcheng_parse import parse_calendar_days
        today = _date.today()
        # 日的相对语义以调用方锚点为准（测试/雷达可指定 anchor；生产
        # calendar() 的 anchor 就是今天）。可售窗口上限仍按机器今天算，
        # 避免旧锚点把上限放宽。
        logical_today = anchor
        end = min(anchor + timedelta(days=max(0, int(days) - 1)),
                  today + timedelta(days=MAX_AHEAD_DAYS))
        out, seen = [], set()
        y, m = anchor.year, anchor.month
        while (y, m) <= (end.year, end.month):
            got = parse_calendar_days(page, y, m, today=logical_today)
            tries = 0
            while not got and tries < 3:
                dev.swipe(450, 1200, 450, 900, duration_ms=320)
                time.sleep(1.0)
                page = _dump(dev)
                if not is_calendar(page):
                    break
                got = parse_calendar_days(page, y, m, today=logical_today)
                tries += 1
            for day, price in (got or {}).items():
                dt = _date(y, m, day)
                if anchor <= dt <= end and dt not in seen:
                    seen.add(dt)
                    out.append({"date": dt.isoformat(),
                                "weekday": _weekday_label(dt, logical_today),
                                "price": float(price)})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return sorted(out, key=lambda r: r["date"])

    def calendar(self, from_city: str, to_city: str,
                 days: int = 62, anchor_ymd: str = "") -> List[dict]:
        """该航线逐日最低价（今天起 days 天，封顶 MAX_AHEAD_DAYS）。"""
        try:
            anchor = (_date.fromisoformat(anchor_ymd[:10])
                      if anchor_ymd else _date.today())
        except ValueError:
            anchor = _date.today()
        days = max(1, min(int(days or 14), MAX_AHEAD_DAYS))
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
            time.sleep(1.2)
            started = time.time()
            page = self._open_calendar(dev)
            if page is None:
                if is_login_wall(_dump(dev)):
                    self.login_suspect = True
                    self.path_note("app-login", "login",
                                   detail="同程日历要求登录")
                else:
                    self.path_note("app-calendar", "timeout",
                                   detail="点日期位后未打开价格日历")
                return []
            rows = self._calendar_window(dev, page, anchor, days)
            if not rows:
                self.path_note(
                    "app-calendar", "empty",
                    detail="日历无 %s 起 %d 天的价格（可能超出可售窗口）"
                           % (anchor.isoformat(), days))
                return []
            self.path_note("app-calendar", "ok", rows=len(rows),
                           detail="同程 App 原生价格日历",
                           ms=int((time.time() - started) * 1000))
            self.logger.info("[%s] 日历 %s→%s %s..%s · %d 天有价",
                             self.name, from_city, to_city, rows[0]["date"],
                             rows[-1]["date"], len(rows))
            try:
                dev.keyevent("BACK")
                time.sleep(0.6)
            except Exception:
                pass
            return rows

    def low_fare(self, from_city: str, to_city: str,
                 days: int = 14, anchor_ymd: str = "") -> List[dict]:
        """特价雷达发现源：逐日最低价（与 calendar 同一数据面）。"""
        return self.calendar(from_city, to_city, days=days,
                             anchor_ymd=anchor_ymd)

    # ---------- 查询 / 解析 ----------
    def _one_date(self, dev, from_city: str, to_city: str, date: str):
        started = time.time()
        if not self._pick_date(dev, date):
            return None
        page = _dump(dev)
        btn = _find_text(page, "机票查询")
        if btn is None:
            self.path_note("app-search", "timeout", detail="找不到查询按钮")
            return None
        dev.tap(*_center(btn))
        page = ""
        deadline = time.time() + 50
        while time.time() < deadline:
            time.sleep(2)
            page = _dump(dev)
            if is_login_wall(page) and not parse_result_rows(page):
                self.login_suspect = True
                self.note_date(date, [], "login",
                               ms=int((time.time() - started) * 1000))
                return None
            rows = parse_result_rows(page)
            if rows:
                break
            # 弹层：出行提醒/广告，能关就关
            try:
                from .app_blockers import detect_block
                blk = detect_block(page)
                if blk.kind == "ad" and blk.close_xy:
                    self.logger.info("[%s] 关闭弹层：%s", self.name,
                                     blk.detail)
                    dev.tap(*blk.close_xy)
                    time.sleep(1.5)
            except Exception:
                pass
        rows = parse_result_rows(page)
        if not rows:
            # 再滚一次，部分行在首屏下方
            dev.swipe(450, 1400, 450, 600, duration_ms=350)
            time.sleep(1.5)
            page = _dump(dev)
            rows = parse_result_rows(page)
        if not rows:
            self.note_date(date, [], "结果页未解析出带价航班",
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
