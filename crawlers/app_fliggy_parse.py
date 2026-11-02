# -*- coding: utf-8 -*-
"""飞猪 App 结果页解析（Windows OCR 词块，纯函数，可离线测）。

飞猪 App 的航班页是 Flutter 画布：`uiautomator`/u2 只能拿到系统状态栏，
拿不到航班文本。2026-11-02 真机（900×1600 竖屏）验证 Windows 自带
zh-Hans-CN OCR 能稳定读出结果页的支付价、时刻、航班号与机场。

输入是 OCR 的**词块**列表（含 x/y/w/h），不是整行文本——OCR 会把左右
两列拼进同一行，按 y 分带、按 x 分列才可靠。行锚点取左列的出发时刻
（大字号两位数字），同一行内再取到达时刻、右侧支付价、机场、航班号。

价格口径：取右侧最大字号、最靠右的 3 位数字为**页面支付价**；左侧
小字号划线价单独保留为 `list_price`。App 未标注是否含税，不冒充含税。
"""
from __future__ import annotations

import re
from typing import Iterable, List

_PRICE_RE = re.compile(r"^\d{3}$")
_TWO_DIGIT = re.compile(r"^\d{2}$")
_FLIGHT_NO = re.compile(r"^([A-Z0-9]{2})(\d{3,4})$")
_TAGS = ("历史低价", "可能涨价", "限特定乘客", "少量")


def _words(items: Iterable[dict]) -> List[dict]:
    out = []
    for w in items or []:
        t = str(w.get("t") or w.get("text") or "").replace(" ", "")
        if not t:
            continue
        try:
            x, y = int(w["x"]), int(w["y"])
            ww, hh = int(w["w"]), int(w["h"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"t": t, "x": x, "y": y, "w": ww, "h": hh})
    return out


def _near(words, y, tol=10, x0=0, x1=10 ** 9):
    return sorted([w for w in words
                   if abs(w["y"] - y) <= tol and x0 <= w["x"] < x1],
                  key=lambda w: w["x"])


def _join(words):
    return "".join(w["t"] for w in words)


def _time_at(words, y, x0, x1):
    """同一行里按 x 取时刻：两个两位数字 + 中间冒号。"""
    cells = _near(words, y, tol=12, x0=x0, x1=x1)
    digits = [w["t"] for w in cells if _TWO_DIGIT.match(w["t"])
              and w["h"] >= 24]
    if len(digits) >= 2:
        return "%s:%s" % (digits[0], digits[1])
    return ""


def _fix_flight_no(raw: str) -> str:
    """OCR 把航班号里的字母 O 读成 0（实测 H01017=HO1017）。"""
    m = _FLIGHT_NO.match(raw or "")
    if not m:
        return ""
    pre, num = m.group(1), m.group(2)
    if "0" in pre:
        pre = pre.replace("0", "O")
    return pre + num


def _flight_no(words, y):
    for w in sorted(words, key=lambda w: w["x"]):
        if abs(w["y"] - y) <= 26 and w["x"] < 360:
            f = _fix_flight_no(w["t"])
            if f:
                return f, w
    return "", None


def _airline(words, y, fno_word):
    if fno_word is None:
        return ""
    left = _join([w for w in _near(words, fno_word["y"], tol=8, x0=0,
                                   x1=fno_word["x"])])
    m = re.search(r"([\u4e00-\u9fa5]{2,4})$", left)
    return m.group(1) if m else ""


def _airport(txt):
    """去掉经停/时长等混入词，只留机场+航站楼。"""
    txt = re.split(r"(?:经停|停\d|停\s*\d|经)", txt or "")[0]
    txt = txt.replace("TI", "T1").replace("Tl", "T1")
    return txt[:8]


def _center(box):
    return (box["x"] + box["w"] // 2, box["y"] + box["h"] // 2)


def _lines(words):
    """按 y + 水平间距把词块并成视觉行（「上海」「昆明」同一 y 也要分开）。"""
    lines = []
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        target = None
        for ln in lines:
            if (abs(w["y"] - ln["y"]) <= 12
                    and w["x"] <= ln["x2"] + 60):
                target = ln
                break
        if target is None:
            lines.append({"y": w["y"], "x2": w["x"] + w["w"],
                          "y2": w["y"] + w["h"], "parts": [w]})
            continue
        target["parts"].append(w)
        target["x2"] = max(target["x2"], w["x"] + w["w"])
        target["y2"] = max(target["y2"], w["y"] + w["h"])
    for ln in lines:
        parts = sorted(ln["parts"], key=lambda w: w["x"])
        ln["text"] = "".join(p["t"] for p in parts)
        ln["x"] = parts[0]["x"]
        ln["w"] = ln["x2"] - ln["x"]
        ln["h"] = ln["y2"] - ln["y"]
    return lines


def pick_best(rows):
    """渠道最低价：优先可公开购买的班次。

    「限特定乘客」（学生/长者等）仍保留在明细里，但不能当普通最低价；
    若整页只有受限价，才退回它并保留标签，不静默隐瞒。
    """
    if not rows:
        return None
    general = [r for r in rows
               if "限特定乘客" not in (r.get("tags") or [])]
    return min(general or rows, key=lambda r: r["price"])


def parse_form_words(items):
    """飞猪机票表单页 OCR 词块 → 当前航线/日期/可点坐标。

    表单也是 Flutter 画布；用大字号城市行和日期行定位。返回空字段表示
    该页不是可识别的机票表单（调用方应记 unsupported，不要盲点坐标）。
    """
    lines = _lines(_words(items))
    cities = [ln for ln in lines
              if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", ln["text"])
              and ln["h"] >= 30 and 560 <= ln["y"] <= 700]
    cities.sort(key=lambda ln: ln["x"])
    dep = cities[0] if len(cities) >= 1 else None
    arr = cities[-1] if len(cities) >= 2 else None
    # 日期行 OCR 会按字号拆分（「11」「月」「2」「日」y 差 13px），
    # 不能按视觉行合并；按 y 区间 + x 排序重建。
    dws = sorted([w for w in _words(items)
                  if 700 <= w["y"] <= 830 and w["x"] < 380],
                 key=lambda w: w["x"])
    date_text = "".join(w["t"] for w in dws)
    date_box = None
    if re.search(r"\d{1,2}月\d{1,2}日", date_text) and dws:
        date_box = {
            "x": min(w["x"] for w in dws),
            "y": min(w["y"] for w in dws),
            "w": max(w["x"] + w["w"] for w in dws)
                 - min(w["x"] for w in dws),
            "h": max(w["y"] + w["h"] for w in dws)
                 - min(w["y"] for w in dws),
        }
    search = next((ln for ln in lines if ln["text"] == "搜索机票"), None)
    return {
        "dep": dep["text"] if dep else "",
        "arr": arr["text"] if arr else "",
        "date_text": date_text,
        "dep_xy": _center(dep) if dep else None,
        "arr_xy": _center(arr) if arr else None,
        "date_xy": _center(date_box) if date_box else None,
        "search_xy": _center(search) if search else None,
    }


def parse_words(items, from_city="", to_city="", date=""):
    """OCR 词块 → 航班行（按页面顺序）。

    每行字段：price / list_price / dep_time / arr_time / arr_day_note /
    dep_airport / arr_airport / airline / flight_no / tags / cabin_note。
    """
    words = _words(items)
    anchors = [w for w in words
               if _TWO_DIGIT.match(w["t"]) and w["h"] >= 28
               and w["x"] < 220 and 600 <= w["y"] <= 1520]
    anchors.sort(key=lambda w: w["y"])
    merged = []
    for w in anchors:
        if merged and abs(w["y"] - merged[-1]["y"]) <= 24:
            continue
        merged.append(w)

    rows = []
    for a in merged:
        dep = _time_at(words, a["y"], 0, 300)
        arr = _time_at(words, a["y"], 300, 640)
        if not dep or not arr:
            continue
        big = [w for w in words
               if _PRICE_RE.match(w["t"]) and w["h"] >= 28
               and w["x"] >= 700 and abs(w["y"] - a["y"]) <= 32]
        if not big:
            continue
        pay = max(big, key=lambda w: w["x"])
        small = [w for w in words
                 if _PRICE_RE.match(w["t"]) and w["h"] <= 22
                 and 650 <= w["x"] < 740 and abs(w["y"] - a["y"]) <= 32]
        list_price = max(small, key=lambda w: w["x"])["t"] if small else ""
        fno, fw = _flight_no(words, a["y"] + 95)
        dep_air = _join([w for w in _near(words, a["y"] + 50, tol=16, x0=0,
                                          x1=300)])
        arr_air = _join([w for w in _near(words, a["y"] + 50, tol=16,
                                          x0=400, x1=700)])
        day_note = _join([w for w in words
                          if abs(w["y"] - (a["y"] - 30)) <= 18
                          and 380 <= w["x"] < 620])
        tags = [t for t in _TAGS
                if t in _join([w for w in words
                               if a["y"] - 70 <= w["y"] < a["y"]])]
        cabin = _join([w for w in words
                       if abs(w["y"] - (a["y"] + 52)) <= 20
                       and w["x"] >= 700])
        rows.append({
            "price": int(pay["t"]),
            "list_price": int(list_price) if list_price else None,
            "dep_time": dep,
            "arr_time": arr,
            "arr_day_note": day_note,
            "dep_airport": _airport(dep_air),
            "arr_airport": _airport(arr_air),
            "airline": _airline(words, a["y"] + 95, fw),
            "flight_no": fno,
            "tags": tags,
            "cabin_note": cabin[:20],
            "from_city": from_city,
            "to_city": to_city,
            "date": date,
        })
    # 同航班同刻只留最低支付价（列表滚动会重复）
    merged_rows = {}
    for r in rows:
        key = (r["flight_no"], r["dep_time"], r["arr_time"])
        old = merged_rows.get(key)
        if old is None or r["price"] < old["price"]:
            merged_rows[key] = r
    return sorted(merged_rows.values(),
                  key=lambda r: (r["dep_time"], r["price"]))
