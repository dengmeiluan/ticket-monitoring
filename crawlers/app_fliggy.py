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
from datetime import date as _date, timedelta
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

# **1260×2800 实测标定**（2026-11-05，从日历页 OCR 词块量出）：
#   列中心 83 / 255 / 426 / 597 / 769 / 940 / 1112 → 起点 83、列距 171
#   行 1457 → 1658                                 → 行距 201
#   反推首行 = 1457 - 3*201 = 854
#   第二个月表头 1826 与首月表头 697 差 1129 → 第二段首行 ≈ 1983
#
# 为什么不能按 900 等比缩放：横向 128.6×1.4=180 但实测 171；
# 纵向 144×1.75=252 但实测 201 —— 缩放会让点落进相邻日期/月份。
_CAL_TABLE = {
    (1260, 2800): {
        # 列中心实测（日一二三四五六，周日在前）：
        #   12 月首行日号 1..5 落在 446/615/786/957/1130 → 步长 171，
        #   向左外推两列得 104/275；与「2026-12-01 是周二、落在第 3 列」
        #   互相印证（两处独立来源一致）。
        "cols": (104, 275, 446, 617, 788, 959, 1130),
        "row0": 854,
        "row_step": 201,
        "month2_row0": 1983,
        # 表头 y → 首行 y 的差：实测表头 697、首行 854 → 157。
        # **滚动之后表头位置会变**，所以要按实际表头 y 重算首行，
        # 不能用固定的 854（那只是"未滚动时"的位置）。
        "header_to_row0": 157,
    },
}


def _cal_geo(screen):
    """当前屏幕的日历栅格几何；未知尺寸按 900 基准等比缩放。"""
    try:
        key = (int(screen[0]), int(screen[1])) if screen else None
    except (TypeError, ValueError, IndexError):
        key = None
    if key in _CAL_TABLE:
        g = _CAL_TABLE[key]
        return (list(g["cols"]), g["row0"], g["row_step"], g["month2_row0"])
    if not key:
        return (list(_COLS), _ROW0, _ROW_STEP, _MONTH2_ROW0)
    kx, ky = key[0] / 900.0, key[1] / 1600.0
    return ([c * kx for c in _COLS], _ROW0 * ky, _ROW_STEP * ky,
            _MONTH2_ROW0 * ky)

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


def _home_flight_xy(xml):
    """首页「机票」宫格坐标：**先读 UI 树**，取不到才交给 OCR。

    为什么（2026-11-05）：原实现只走 OCR（`_ocr` + `_find_phrase`），
    失败后回落到写死的 `_HOME_FLIGHT=(274,480)`——那是 900×1600 的标定值。
    设备换成 1260×2800 后真机票宫格在 **(382,785)**，死坐标点偏，
    于是"首页点机票后未到 Flutter 表单"，整条渠道 0 条。

    实测飞猪首页在 UI 树里**是暴露**「机票」的（298 个节点，
    text/content-desc 都有），所以优先用它——比 OCR 快且稳。
    """
    best = None
    for m in re.finditer(r"<node[^>]*>", xml or ""):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        ds = re.search(r'content-desc="([^"]*)"', tag)
        s = ((t.group(1) if t else "") or (ds.group(1) if ds else "")).strip()
        if s != "机票":
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        y1 = int(b.group(2))
        # 只要下半屏的宫格，避免点到顶部营销 banner（"50元机票红包"）
        if y1 < 300:
            continue
        cx = (int(b.group(1)) + int(b.group(3))) // 2
        cy = (y1 + int(b.group(4))) // 2
        if best is None or cy < best[1]:
            best = (cx, cy)
    return best


def round_trip_footer_matches(footer, dep_ymd, ret_ymd):
    """底栏读到的两个日期是否与期望一致 → ``(ok, 说明)``。

    这是往返流程**唯一的事实关卡**（2026-11-06）：点完两个日期后，
    只有底栏写着「去程：12月14日 / 返程：12月19日」，才能相信自己点对了。
    底栏不写年份，所以这里只比 (月, 日)。

    抽成纯函数是为了能被单测钉住——这条判断出错会产出「日期对不上但价格
    看起来合理」的错数据，属于最难发现的那类。
    """
    def _md(ymd):
        try:
            _y, m, d = map(int, str(ymd).split("-"))
            return (m, d)
        except (TypeError, ValueError):
            return None

    want_dep, want_ret = _md(dep_ymd), _md(ret_ymd)
    if want_dep is None or want_ret is None:
        return False, "日期格式不是 YYYY-MM-DD：%s/%s" % (dep_ymd, ret_ymd)
    got_dep = (footer or {}).get("dep")
    got_ret = (footer or {}).get("ret")
    def _fmt(v):
        return ("%02d-%02d" % v) if isinstance(v, tuple) and len(v) == 2 \
            else "未选择"

    if got_dep != want_dep or got_ret != want_ret:
        return False, ("往返日历落点不符：期望 %02d-%02d/%02d-%02d，实际 %s/%s"
                       % (want_dep[0], want_dep[1], want_ret[0], want_ret[1],
                          _fmt(got_dep), _fmt(got_ret)))
    return True, "底栏校验通过"


def _mode_tap_xy(words, label):
    """表单**档位行**里 `label`（单程/往返/多程）的中心坐标；没有返回 None。

    纯函数，便于离线单测（坐标来自 2026-11-05 真机实测：
    同一行 y≈576，`单`x=189 `程`x=238 `往`x=581 `返`x=631 `多`x=976 `程`x=1024）。

    OCR 把每个字拆成独立词块，所以先按 y 聚成行、按 x 排序拼回整行，
    再在整行里找 label 的**字符区间**，映射回对应的词块算中心 ——
    这样「单程」和「多程」共用的那个「程」字不会被认错档位。
    """
    rows = {}
    for w in words or []:
        t = str(w.get("t") or w.get("text") or "").strip()
        if not t or not any(ch in t for ch in "单程往返多"):
            continue
        try:
            y = float(w.get("y") or 0)
            x = float(w.get("x") or 0)
            ww = float(w.get("w") or 0)
            hh = float(w.get("h") or 0)
        except (TypeError, ValueError):
            continue
        if not (400 <= y <= 800):        # 档位行在表单上部
            continue
        key = None
        for k in rows:
            if abs(k - y) <= 20:
                key = k
                break
        rows.setdefault(key if key is not None else y,
                        []).append((x, ww, hh, t))
    for _y, items in sorted(rows.items()):
        xs = sorted(items, key=lambda v: v[0])
        line = "".join(t for _x, _w, _h, t in xs)
        idx = line.find(label)
        if idx < 0:
            continue
        want_end = idx + len(label)
        pos = 0
        seg = []
        for x, ww, hh, t in xs:
            start, end = pos, pos + len(t)
            pos = end
            if end <= idx or start >= want_end:
                continue
            seg.append((x, ww, hh))
        if not seg:
            continue
        x0 = min(s[0] for s in seg)
        x1 = max(s[0] + s[1] for s in seg)
        # OCR 的 y 是**框顶**，中心要加半个字高（加整个会把点压低一个字）
        cy = int(_y + sum(s[2] for s in seg) / len(seg) / 2.0)
        return (int((x0 + x1) / 2), cy)
    return None


def _find_phrase(words, phrase, min_y=0):
    hits = _phrase_hits(words, phrase, min_y=min_y)
    return hits[0] if hits else None


def _cal_day_xy_by_ocr(dev, ocr, year, month, day, months):
    """**直接从 OCR 日号**找出目标日期的中心点（不依赖栅格几何）。

    为什么（2026-11-05）：几何推算法两处交叉验证都对
    （`22..28 @ y=1458`、`29,30 @ y=1660` → 行距 202、首行 852），
    但按它算出的 (255,1256) 点下去日期不变。与其继续猜栅格，
    不如直接用"日号本身"的 OCR 框——日号是能被 OCR 读出来的
    （实测 `22 x=83 y=1458`），这条路与分辨率、滚动位置都无关。

    难点是**把日号与价格区分开**：实测同一行的日号在 y≈1458，
    而价格（`820`/`¥380`）在 y≈1528 —— 二者在不同 y 线上。
    所以按 y 聚类后，**含 ≥4 个小数字（1..31、≤2 位）的行**才是日号行；
    价格行元素少且多为 3 位数，自然被排除。
    """
    if not months:
        return None
    band_lo = None
    band_hi = None
    for i, m in enumerate(months):
        if m[:2] != (year, month):
            continue
        band_lo = m[2]
        band_hi = months[i + 1][2] if i + 1 < len(months) else band_lo + 1400
        break
    if band_lo is None:
        return None

    cands = []
    for w in ocr:
        t = str(w.get("t") or w.get("text") or "").strip()
        if not t.isdigit() or len(t) > 2:
            continue
        try:
            n = int(t)
            x = float(w.get("x") or 0)
            y = float(w.get("y") or 0)
            ww = float(w.get("w") or 0)
            hh = float(w.get("h") or 0)
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= 31):
            continue
        if not (band_lo < y < band_hi):
            continue
        cands.append((n, x + ww / 2.0, y + hh / 2.0))
    if not cands:
        return None

    # 按 y 聚类成行，只保留"日号行"（≥4 个 1..31 的小数字）
    rows = {}
    for n, cx, cy in cands:
        key = None
        for k in rows:
            if abs(k - cy) <= 25:
                key = k
                break
        rows.setdefault(key if key is not None else cy, []).append((n, cx, cy))
    day_rows = [v for v in rows.values() if len(v) >= 4]
    if day_rows:
        # **月份最后一行常常不足 4 个日号**（11 月只有 29、30 两个），
        # 会被上面的规则误剔除。补一行：只向下补（日历行是往下排的），
        # 且距离不超过一个行距的量级——这样不会把上方的**价格行**
        # （实测日号行 1458、价格行 1528，二者 y 相近）误当成日号行。
        max_y = max(min(c[2] for c in g) for g in day_rows)
        for _k, g in rows.items():
            if g in day_rows:
                continue
            y0 = min(c[2] for c in g)
            if 0 < (y0 - max_y) <= 300:
                day_rows.append(g)
    else:
        day_rows = list(rows.values())
    for group in sorted(day_rows, key=lambda g: min(c[2] for c in g)):
        for n, cx, cy in sorted(group, key=lambda c: c[1]):
            if n == day:
                return (int(round(cx)), int(round(cy)))
    return None


def _target_xy(year, month, day, month_section, screen=None, header_y=None):
    """目标日期在日历网格里的坐标；月外/越界返回 None。

    ``screen`` 传 ``(w, h)`` 时按 `_cal_geo` 取该屏幕的栅格几何。

    ``header_y`` 传该月的**表头实际 y** 时，首行按「表头 + 常量偏移」重算。
    这是必须的（2026-11-05 实测）：日历**滚动后**表头的绝对 y 会变，
    而 `row0` 是"未滚动时"量出来的绝对值；不重算就会点到别的行。
    """
    cols, row0, step, month2 = _cal_geo(screen)
    if header_y is not None:
        off = None
        try:
            key = (int(screen[0]), int(screen[1])) if screen else None
        except (TypeError, ValueError, IndexError):
            key = None
        if key in _CAL_TABLE:
            off = _CAL_TABLE[key].get("header_to_row0")
        if off is not None:
            row0 = float(header_y) + off
    elif month_section:
        row0 = month2
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    for wi, week in enumerate(weeks):
        for di, val in enumerate(week):
            if val != day:
                continue
            return (int(round(cols[di])), int(round(row0 + wi * step)))
    return None


class AppFliggyCrawler(AppCrawler):
    name = "app_fliggy"
    package = _APP_PKG
    #: 往返已真机验证（2026-11-06）：SHA→PEK 11-16/11-19 总价 ¥747，
    #: 去程起价 ¥682，与截图逐项一致；landed `航班明细/ok/rows=1/25.2s`。
    supports_round_trip = True

    def login_url(self) -> str:
        return ("android://%s?login=phone —— 飞猪 App 手机号登录；"
                "未登录时结果页会要求登录" % _APP_PKG)

    # ---------- OCR ----------
    def _ocr(self, dev):
        from core.android.ocr import ocr_words
        return ocr_words(dev.screencap() or b"")

    def _form(self, dev):
        try:
            _scr = dev.window_size()
        except Exception:
            _scr = None
        return parse_form_words(self._ocr(dev), screen=_scr)

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
        """飞猪安全容器/访问拒绝页：显式记 blocked 并停手（连续重试会加重风控）。"""
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

    def _blocked_reason(self, dev):
        """页面是不是被**阿里风控**拦了？拦了就返回一句话，否则空串。

        为什么单独成方法（2026-11-05）：风控页和"没进表单"外观一致，
        原来统一记 `app-form timeout`，把人引去查坐标/解析；
        而真实原因是"被拦了、要人工过安全页"。两种处置完全不同，
        所以判定要可单测（`tests/test_r1043_fliggy_blocked_reason.py`）。
        """
        try:
            act = str(dev.current_activity() or "")
        except Exception:
            act = ""
        # 先看页面里是不是**可见的滑块挑战**：这种用户手动拖一下就能过，
        # 提示措辞应与"白屏容器"区分开（前者可人工，后者只能等/清数据）。
        try:
            _x = str(dev.dump() or "")
        except Exception:
            _x = ""
        if _x and ("拖动下方滑块" in _x or "拖动滑块" in _x
                   or "向右滑动验证" in _x or "滑动验证" in _x):
            return ("安全验证滑块（阿里 Baxia）——需人工拖动一次；"
                    "本项目按纪律不解强人机")
        if "ContainerActivity" in act or "wireless.security" in act:
            return "阿里安全容器 %s" % act.split("/")[-1][:36]
        try:
            joined = "".join(str(w.get("t") or w.get("text") or "")
                             for w in self._ocr(dev))
        except Exception:
            return ""
        for mark in ("访问被拒绝", "安全验证", "环境异常", "操作过于频繁"):
            if mark in joined:
                return "页面出现「%s」" % mark
        return ""

    def _ensure_form(self, dev):
        try:
            act = str(dev.current_activity() or "")
        except Exception:
            act = ""
        # **登录页必须记 `login`，不能记 `app-form timeout`**（2026-11-05）。
        #
        # 实测：飞猪登录态失效后会直接停在
        # `com.taobao.trip/.login.v2.CustomUserLoginActivity`。
        # 原实现只认 `ContainerActivity`（安全容器），于是这张登录页被当成
        # "首页 → 点机票没进表单"，账本记 `app-form timeout` —— 而
        # `timeout` 会让人去查坐标/解析，真实原因却是"要重新登录"。
        # 判据纪律：页面明确要求登录就记 `login`，不记超时。
        if "login" in act.lower():
            self.login_suspect = True
            self.path_note("app-login", "login",
                           detail="飞猪要求登录（%s）——请到「渠道登录」重登飞猪"
                                  % act.split("/")[-1][:40])
            return None
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
            # 冷启动后直接落在登录页（会话失效的典型形态）：
            # 立刻记 login 停手，不要在这个循环里空转到 24 秒再报 timeout。
            if "login" in act.lower():
                self.login_suspect = True
                self.path_note("app-login", "login",
                               detail="飞猪要求登录（%s）——请到「渠道登录」"
                                      "重登飞猪" % act.split("/")[-1][:40])
                return None
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
        # **透明日历层**（`TripTransparentFlutterActivity`）会盖在表单上，
        # 而且飞猪会把"上次停在日历"这个状态带到冷启动里（2026-11-05 实测）：
        # 此时 `TripFlutterActivity` 仍存在但 `_form` 读到的是日历页，
        # 于是被判「未到 Flutter 表单」。先按键返回把它收掉再重判。
        for _ in range(3):
            try:
                act2 = str(dev.current_activity() or "")
            except Exception:
                act2 = ""
            if "TransparentFlutterActivity" not in act2:
                break
            dev.keyevent("BACK")
            time.sleep(1.5)
            form = self._wait_form(dev, timeout=5)
            if form:
                return form
        time.sleep(3)
        xy = _home_flight_xy(dev.dump() or "")
        for _ in range(2 if xy is None else 0):
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
                # 重试点也用 UI 树坐标（拿不到才退回写死值）
                dev.tap(*(_home_flight_xy(dev.dump() or "") or _HOME_FLIGHT))
                retried = True
            time.sleep(2)
        # **失败前先分辨"是不是被安全容器拦了"**（2026-11-05）。
        # 阿里风控页出现时，页面结构和"没进表单"一模一样，原来统一记
        # `app-form timeout` —— 而 timeout 会把人引去查坐标/解析，
        # 真实原因却是"风控拦了，需要人工过安全页"。这是两种完全不同的处置。
        _blk = self._blocked_reason(dev)
        if _blk:
            self.path_note("app-block", "blocked",
                           detail="飞猪被风控拦截：%s；请人工打开 App "
                                  "过掉安全页后再采集" % _blk)
        else:
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
    def _visible_months(self, dev):
        """读出日历页上**实际可见**的月份列表 ``[(year, month), ...]``。

        为什么必须有这一步（2026-11-05 实测）：飞猪日历是按**表单当前日期
        所在月份**打开的，而不是"当月"。表单停在哪个月，首屏就是哪个月。
        而 `_pick_date` 原来假设「首屏 = 目标月（section 0）」，
        于是目标 11-16 而首屏是 12 月时，它会拿 11 月的栅格坐标去点
        12 月的日历 → 点中别的日期 → 报「点日历后日期未改变」。

        OCR 会把表头拆成散字（实测 `'2026' x=467`、`'1' x=669`、
        `'2' x=701`、`'月' x=735`），所以按 y 分组成行、按 x 排序后再拼。
        """
        out = []
        try:
            words = self._ocr(dev)
        except Exception:
            return out
        # 按 y 聚行（20px 容差）
        rows = {}
        for w in words:
            try:
                y = float(w.get("y") or 0)
                x = float(w.get("x") or 0)
            except (TypeError, ValueError):
                continue
            t = str(w.get("t") or w.get("text") or "")
            if not t or "月" not in t and not t.isdigit():
                continue
            key = None
            for k in rows:
                if abs(k - y) <= 20:
                    key = k
                    break
            rows.setdefault(key if key is not None else y, []).append((x, t))
        for _y, items in sorted(rows.items()):
            line = "".join(t for _x, t in sorted(items))
            m = re.search(r"(\d{4})\D{0,2}?(\d{1,2})\D{0,2}?月", line)
            if m:
                try:
                    ym = (int(m.group(1)), int(m.group(2)), float(_y))
                except ValueError:
                    continue
                if 1 <= ym[1] <= 12 and ym[:2] not in [x[:2] for x in out]:
                    out.append(ym)
        return out

    def _ensure_mode(self, dev, label: str = "单程"):
        """把表单切到指定档位（单程 / 往返 / 多程）。

        为什么必须切（2026-11-05 截图实证）：飞猪表单会保留上次的**往返**档，
        这时打开的是**往返日历**——底部写着「去程：12月14日 | 返程：未选择 |
        往返总价 ¥---」，并提示「请选择返程日期」。
        在这种状态下**只点一个日期是不落定的**：它只设了去程、还在等返程，
        表单日期永远不变 —— 现象就是「点日历后日期未变」，
        而根因根本不是坐标/几何（几何用两条独立来源验过是对的）。

        档位 OCR 会把字拆开（实测同一行 y≈576：
        `单`x=189 `程`x=238 `往`x=581 `返`x=631 `多`x=976 `程`x=1024），
        所以按 y 聚行、按 x 排序拼回整行再定位子串。
        坐标计算抽成纯函数 `_mode_tap_xy`，便于离线单测。
        """
        try:
            words = self._ocr(dev)
        except Exception:
            return False
        xy = _mode_tap_xy(words, label)
        if xy is None:
            return False
        self.logger.info("[%s] 切「%s」档：%s", self.name, label, xy)
        dev.tap(*xy)
        time.sleep(2)
        return True

    def _ensure_one_way(self, dev):
        """切「单程」档（本渠道 `supports_round_trip=False` 时的默认档）。"""
        return self._ensure_mode(dev, "单程")

    def _tap_cal_day(self, dev, ymd: str):
        """在**已打开的日历**里点出某一天（必要时向后翻屏）。成功返回 True。

        与单程的 `_pick_date` 区别：这里不负责开关日历、不负责"确认"，
        专供往返复用（一次打开日历要连点两个日期）。
        定位优先用 OCR 日号（`_cal_day_xy_by_ocr`），取不到才退回几何栅格。
        """
        try:
            y, m, d = map(int, str(ymd).split("-"))
        except (TypeError, ValueError):
            return False
        try:
            scr = dev.window_size() or (900, 1600)
            w, h = int(scr[0]), int(scr[1])
        except Exception:
            w, h = 900, 1600
        for _ in range(4):
            months = self._visible_months(dev)
            if not months:
                return False
            xy = _cal_day_xy_by_ocr(dev, self._ocr(dev), y, m, d, months)
            if xy is None:
                hit = [m0 for m0 in months if m0[:2] == (y, m)]
                if hit:
                    xy = _target_xy(y, m, d, months.index(hit[0]),
                                    screen=(w, h), header_y=hit[0][2])
            if xy is not None:
                dev.tap(*xy)
                time.sleep(1.5)
                return True
            # 目标月份在后面：向上滑把更晚的月份拉上来
            if (y, m) > months[-1][:2]:
                dev.swipe(int(w * 0.5), int(h * 0.80),
                          int(w * 0.5), int(h * 0.35), duration_ms=400)
                time.sleep(2.5)
                continue
            # 目标月份**在前面**：向下滑把更早的月份拉回来
            # （日历按"表单当前日期所在月份"打开，目标可能比它早，
            #   2026-11-05 实测：表单停在 12 月，目标 11 月 → 之前直接返回 False）
            if (y, m) < months[0][:2]:
                dev.swipe(int(w * 0.5), int(h * 0.35),
                          int(w * 0.5), int(h * 0.80), duration_ms=400)
                time.sleep(2.5)
                continue
            return False
        return False

    def _pick_round_trip_dates(self, dev, dep_ymd: str, ret_ymd: str) -> bool:
        """往返：打开日历 → 点去程 → 点返程 → **用底栏校验** → 点确定。

        校验这一步不能省（2026-11-05 截图实证）：飞猪底栏会写
        「去程：12月14日 | 返程：未选择 | 往返总价 ¥---」，只有底栏两个
        日期都对上才能相信点对了；否则会拿错日期去搜，产出错误价格。

        注意：本函数**尚未真机验证**，暂不接入 `fetch`。
        """
        from .app_fliggy_parse import parse_round_trip_footer
        form = self._form(dev)
        xy = form.get("date_xy")
        if not xy:
            self.path_note("app-date", "timeout",
                           detail="往返表单未找到日期位")
            return False
        dev.tap(*xy)
        time.sleep(3)
        if not self._tap_cal_day(dev, dep_ymd):
            self.path_note("app-date", "timeout",
                           detail="往返日历点不到去程 %s" % dep_ymd)
            return False
        if not self._tap_cal_day(dev, ret_ymd):
            self.path_note("app-date", "timeout",
                           detail="往返日历点不到返程 %s" % ret_ymd)
            return False
        foot = parse_round_trip_footer(self._ocr(dev))
        ok_f, why = round_trip_footer_matches(foot, dep_ymd, ret_ymd)
        if not ok_f:
            self.path_note("app-date", "timeout", detail=why)
            return False
        self._tap_calendar_confirm(dev)
        time.sleep(2)
        return True

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
        # **前置闸门：只承诺"当月"**（不碰设备）。
        #
        # 次月/更远一律 unsupported 交浏览器 —— 这是仓库既有的契约：
        # 次月格的首屏点选**没有被真机复验过**，拿未验证的路径冒充支持，
        # 只会把"点到别的日期"变成静默错数据。
        # 真正要修的是另一件事：**日历会按表单当前日期所在月份打开**，
        # 于是目标明明是当月，首屏却可能是次月 —— 那种情况下面用
        # `_visible_months` 读出来、回翻之后再点。
        _today = _date.today()
        if (y, m) != (_today.year, _today.month):
            self.path_note(
                "app-date", "unsupported",
                detail="App 日历只验证当月，%s 交浏览器" % target)
            return False
        try:
            _scr = dev.window_size()
        except Exception:
            _scr = None

        # **先确保是单程档**（2026-11-05）：往返档下打开的是**往返日历**
        # （底部「去程… | 返程：未选择 | 往返总价」），只点一个日期不会落定，
        # 要等返程 —— 表现就是"点日历后日期未变"，与坐标无关。
        if self._ensure_one_way(dev):
            form = self._form(dev)
            if not form.get("date_xy"):
                self.path_note("app-date", "timeout",
                               detail="切单程后表单未找到日期位")
                return False

        dev.tap(*form["date_xy"])
        time.sleep(2.5)

        # **按日历实际可见的月份定位 section**（不再假设首屏就是目标月）
        months = self._visible_months(dev)
        ym_list = [m[:2] for m in months]
        section = ym_list.index((y, m)) if (y, m) in ym_list else None
        if section is None:
            # 不在可见范围：**向下滑回翻**（飞猪日历是纵向堆叠的月份）。
            # 2026-11-05 实测：左右滑无效（那是横向切换手势，日历不响应），
            # 向下滑才会把更早的月份拉上来。
            for _ in range(3):
                try:
                    w, h = (int(_scr[0]), int(_scr[1])) if _scr else (900, 1600)
                except (TypeError, ValueError):
                    w, h = 900, 1600
                dev.swipe(int(w * 0.5), int(h * 0.35),
                          int(w * 0.5), int(h * 0.80), duration_ms=400)
                time.sleep(2)
                months = self._visible_months(dev)
                ym_list = [m[:2] for m in months]
                if (y, m) in ym_list:
                    section = ym_list.index((y, m))
                    break
        if section is None:
            self.path_note(
                "app-date", "unsupported",
                detail="日历可见月份 %s 不含 %d-%02d，交浏览器"
                       % ([m[:2] for m in months] or "未识别", y, m))
            return False
        # 该月的**实际表头 y**：滚动后表头位置会变，按它重算首行，
        # 不能用"未滚动时"量出来的绝对值。
        header_y = months[section][2]
        # **优先用 OCR 日号直接定位**（更稳，不受几何/滚动影响）；
        # 取不到才退回几何推算。
        _ocr_words = []
        try:
            _ocr_words = self._ocr(dev)
        except Exception:
            _ocr_words = []
        xy = _cal_day_xy_by_ocr(dev, _ocr_words, y, m, d, months)
        if xy is not None:
            self.logger.info("[%s] 日历日号 OCR 定位 %d-%02d-%02d -> %s",
                             self.name, y, m, d, xy)
        else:
            xy = _target_xy(y, m, d, section, screen=_scr, header_y=header_y)
        if xy is None:
            self.path_note("app-date", "unsupported",
                           detail="日历格不在首屏（%s）" % target)
            return False
        dev.tap(*xy)
        time.sleep(2.5)
        # **飞猪日历选完还要点「确定」**（2026-11-05 实测）。
        # 携程的日历点日期即生效，飞猪的不是：点完日历仍然开着，
        # Activity 停在 `TripTransparentFlutterActivity`，表单日期不变 ——
        # 账本只记「点日历后日期未变」，看着像坐标算错，其实是少点一次确认。
        # OCR 里按钮是散字（`确` x=578 / `定` x=632，y=2678，在屏底）。
        self._tap_calendar_confirm(dev)
        time.sleep(2)
        form = self._wait_form(dev, timeout=10)
        if want in (form.get("date_text") or ""):
            return True
        self.path_note("app-date", "timeout",
                       detail="点日历后日期未变（%s，可见月份 %s，section=%s）"
                              % (target, [m[:2] for m in months], section))
        return False

    def _tap_calendar_confirm(self, dev):
        """点日历底部的「确定/完成/确认」（OCR 会把两个字拆开，按行合并）。"""
        try:
            words = self._ocr(dev)
        except Exception:
            return False
        rows = {}
        for w in words:
            t = str(w.get("t") or w.get("text") or "").strip()
            if not t:
                continue
            if not any(ch in t for ch in "确定完成认"):
                continue
            try:
                y = float(w.get("y") or 0)
                x = float(w.get("x") or 0)
                ww = float(w.get("w") or 0)
            except (TypeError, ValueError):
                continue
            key = None
            for k in rows:
                if abs(k - y) <= 12:
                    key = k
                    break
            rows.setdefault(key if key is not None else y,
                            []).append((x, ww, t))
        for _y, items in sorted(rows.items(), reverse=True):   # 屏底优先
            line = "".join(t for _x, _w, t in sorted(items))
            if not any(k in line for k in ("确定", "完成", "确认")):
                continue
            xs = [x for x, _w, _t in items]
            ws = [w for _x, w, _t in items]
            cx = int((min(xs) + max(xs) + max(ws)) / 2)
            dev.tap(cx, int(_y + 8))
            return True
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

    def low_fare(self, from_city: str, to_city: str,
                 days: int = 14, anchor_ymd: str = "") -> List[dict]:
        """**特价雷达发现源**：逐日最低价。

        调度真正调用的就是这个方法（携程/同程同款约定：`low_fare()` 转
        `calendar()`）。飞猪的日历页本身就把每天的最低价印在格子里，
        所以直接复用 `calendar()`，不需要另走一条"特价列表页"。
        """
        # 链路闸门（r1063 T9）：飞猪的「低价机票」就是价格日历，同一次设备
        # 交互算一条路——两档名字都要放行才跑（停「低价」只停特价发现源，
        # 停「日历」则两个都停）。各自记名，面板上看得清是哪一档停的。
        if not self.path_gate("low-fare", "low_fare"):
            return []
        return self.calendar(from_city, to_city, days=days)

    def calendar(self, from_city: str, to_city: str,
                 days: int = 62) -> List[dict]:
        """**价格日历（低价源）**：飞猪日历每格下方就印着当日最低价。

        这是飞猪此前没接入的维度（2026-11-05 新增）。价值在于：
        明细页一次只能看一个日期，而日历页**一屏就能读到整月每天的最低价**，
        是"低价雷达/发现源"最省配额的一条路。

        实现要点（都是实测出来的，改之前先读）：
        * 日历每格 = 「日号 + 其下方价格」，纵向差约 **70px**（日号 y≈1458、
          价格 y≈1528）；无价的日子写「查看」；
        * 日历按**表单当前月份**打开，所以要先用 `_visible_months` 读真实月份；
        * 横/纵都不能按 900×1600 等比缩放（见 `_CAL_TABLE` 的说明）。
        """
        from core.android import ocr as _ocr_mod
        from .app_fliggy_parse import parse_calendar_prices
        if not _ocr_mod.available():
            self.path_note("android-ocr", "unsupported",
                           detail="Windows OCR 不可用（日历价只能截图读）")
            return []
        try:
            days = max(1, min(int(days or 62), 62))
        except (TypeError, ValueError):
            days = 62
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
        started = time.time()
        # 链路闸门（r1063 T9）：价格日历是一个独立阶段，在拿设备锁之前问。
        if not self.path_gate("app-calendar", "calendar"):
            return []
        with rt.device_lock(owner=self.name):
            self.prepare_device(dev)
            if self._ensure_form(dev) is None:
                return []
            if not self._set_city(dev, self._city_name(from_city), "dep"):
                return []
            if not self._set_city(dev, self._city_name(to_city), "arr"):
                return []
            self._ensure_one_way(dev)
            form = self._form(dev)
            if not form.get("date_xy"):
                self.path_note("app-calendar", "timeout",
                               detail="表单未找到日期位")
                return []
            try:
                w, h = dev.window_size() or (900, 1600)
                w, h = int(w), int(h)
            except Exception:
                w, h = 900, 1600
            dev.tap(*form["date_xy"])
            time.sleep(3)
            # 目标区间是「今天起 N 天」，日历可能开在当前月；
            # 若首屏月份晚于今天所在月，先下滑回翻。
            t0 = _date.today()
            for _ in range(3):
                months = self._visible_months(dev)
                if months and months[0][:2] <= (t0.year, t0.month):
                    break
                dev.swipe(int(w * 0.5), int(h * 0.35),
                          int(w * 0.5), int(h * 0.80), duration_ms=400)
                time.sleep(2.5)
            rows = []
            _geo = _CAL_TABLE.get((w, h))
            _cols = _geo.get("cols") if _geo else None
            # 逐屏读取：每屏最多两个月份
            for _screen in range(2):
                months = self._visible_months(dev)
                if not months:
                    break
                # 已标定屏幕才开「价格反推日号」的外推：未标定屏幕的列网格
                # 会塌缩，推出来的日期可能差一列——那种错比缺几天更难发现。
                got = parse_calendar_prices(self._ocr(dev), months, today=t0,
                                            extrapolate=bool(_cols),
                                            cols=_cols)
                rows.extend(got)
                end = t0 + timedelta(days=days - 1)
                if got and _date.fromisoformat(got[-1]["date"]) >= end:
                    break
                dev.swipe(int(w * 0.5), int(h * 0.80),
                          int(w * 0.5), int(h * 0.35), duration_ms=400)
                time.sleep(2.5)
            end = t0 + timedelta(days=days - 1)
            uniq = {}
            for r in rows:
                d0 = _date.fromisoformat(r["date"])
                if not (t0 <= d0 <= end):
                    continue
                if r["date"] not in uniq or r["price"] < uniq[r["date"]]["price"]:
                    uniq[r["date"]] = r
            out = sorted(uniq.values(), key=lambda r: r["date"])
            try:
                dev.keyevent("BACK")
            except Exception:
                pass
            if not out:
                self.path_note(
                    "app-calendar", "empty",
                    detail="OCR 未读到 %s 起 %d 天的日历价"
                           "（遮挡/不可售/OCR 漏读）"
                           % (t0.isoformat(), days),
                    ms=int((time.time() - started) * 1000))
                return []
            self.path_note("app-calendar", "ok", rows=len(out),
                           detail="飞猪 App 价格日历 OCR",
                           ms=int((time.time() - started) * 1000))
            self.logger.info("[%s] 日历 %s→%s %s..%s · %d 天有价",
                             self.name, from_city, to_city, out[0]["date"],
                             out[-1]["date"], len(out))
            return out

    def _fetch_round_trip(self, dev, from_city, to_city, dep, ret):
        """往返一次查询：设航线 → 点双日期 → 查询 → 读「往返总价」。

        只交**总价**（底部「往返总价 ¥N」）这一条记录：返程列显示的是
        **加价**（`+¥0` / `少量+¥13`），逐组合并需要把两列卡片配对，
        在 OCR 噪声下容易配错——先交最可靠的那个数，extra 里带上起价。
        """
        from .app_fliggy_parse import parse_round_trip_result
        started = time.time()
        if not self._ensure_mode(dev, "往返"):
            self.path_note("TRIP", "timeout", detail="切不到「往返」档")
            return None
        if not self._set_city(dev, self._city_name(from_city), "dep"):
            return None
        if not self._set_city(dev, self._city_name(to_city), "arr"):
            return None
        if not self._pick_round_trip_dates(dev, dep, ret):
            return None
        form = self._form(dev)
        if not form.get("search_xy"):
            self.path_note("app-search", "timeout", detail="找不到搜索按钮")
            return None
        dev.tap(*form["search_xy"])
        deadline = time.time() + 45
        got = {"total": None, "dep_min": None}
        while time.time() < deadline:
            time.sleep(3)
            words = self._ocr(dev)
            txt = "".join(str(w.get("t") or "") for w in words)
            if "访问被拒绝" in txt:
                self.path_note("app-block", "blocked",
                               detail="飞猪返回「访问被拒绝」安全页；需人工处理")
                return None
            got = parse_round_trip_result(words)
            if got.get("total"):
                break
        if not got.get("total"):
            self.note_date("%s/%s" % (dep, ret), [], "往返结果页未读到总价",
                           ms=int((time.time() - started) * 1000))
            return None
        # **按仓库约定打往返标记**（与智行/同程/携程 App 一致）：
        # extra 里必须带 `tripType=RT` 与 `retDate`，否则同一渠道的单程/往返
        # 两种口径在账本与报表里分不开（tests/test_r780_round_trip_row_marking）。
        rec = FlightPrice(
            platform=self.name, from_city=from_city, to_city=to_city,
            depart_date=dep, price=float(got["total"]),
            extra=json.dumps({"tripType": "RT",
                              "retDate": ret,
                              "dep_min": got.get("dep_min"),
                              "basis": "round_trip_total"},
                             ensure_ascii=False))
        self.path_note("往返", "ok", rows=1,
                       detail="往返总价 ¥%.0f（去程起价 %s）"
                              % (got["total"], got.get("dep_min")),
                       ms=int((time.time() - started) * 1000))
        self.logger.info("[%s] 往返 %s→%s %s/%s 总价 ¥%.0f（去程起价 %s）",
                         self.name, from_city, to_city, dep, ret,
                         got["total"], got.get("dep_min"))
        return rec

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        # 日期超出 App 视野就直接交浏览器：App 日历只支持近未来，
        # 远期日期每条要白耗 100–150 秒设备时间（实测 2027-01-29）。
        if self.early_skip(dates):      # 停服/需登录：不发请求
            return []
        if self.reject_far_dates(dates):
            return []
        # 链路闸门（r1063 T9）：**必须在拿设备锁之前**按阶段问——闸门要等
        # 时不能占着设备睡（App 渠道的设备是串行独占的）。一次 fetch 走
        # 「登录 → 列表」两段（往返查询走「登录 → 往返」）；被停用的阶段
        # 只记 `paced` 并交空结果，**不记失败**（记失败会拉开整家渠道熔断）。
        if not self.path_gate("app-login", "detail"):
            return []
        if ret_date:
            if not self.path_gate("往返", "round_trip"):
                return []
        elif not self.path_gate("app-list", "detail"):
            return []
        if ret_date:
            if not self.supports_round_trip:
                self.path_note("TRIP", "unsupported",
                               detail="飞猪 App 往返尚未真机验证；走 PC/H5")
                return []
            if not dates:
                return []
            rt = self.runtime()
            ok, why = rt.ensure_ready()
            if not ok:
                return []
            _dev = rt.device()
            if _dev is None:
                return []
            with rt.device_lock(owner=self.name):
                self.prepare_device(_dev)
                if self._ensure_form(_dev) is None:
                    return []
                rec = self._fetch_round_trip(_dev, from_city, to_city,
                                             dates[0], ret_date)
            return [rec] if rec else []
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
        with rt.device_lock(owner=self.name):
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
