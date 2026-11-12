# -*- coding: utf-8 -*-
"""携程 App 价格日历的纯 OCR 解析。

真机日期弹层是自绘 View，`uiautomator dump` 只有月标题、没有日格文本；
但截图经 Windows OCR 后，每个日格的 `¥N` 与月份标题都可读（2026-11-02
17:47 真机截图：2026-11 / 2026-12 / 2027-01 三个月逐日价）。

日号经常 OCR 不出来（大号黑字、与节日标签混排），所以不依赖日号：
用「月标题 + 7 列网格 + 周行距」反推日期，行距从本次截图的价格行
实测（国内档 88px、国际档 107px），不写死。月首星期由
`date(year, month, 1)` 计算，列序为周日..周六（截图表头 日..六）。
"""
from __future__ import annotations

import calendar as _cal
import datetime as _dt
import re

_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")
# OCR 常把数字认成形近字母；只用于价格 token（三/四位数），
# 不做全文替换，避免把普通文字改坏。
_DIGIT_FIX = str.maketrans({
    "g": "9", "G": "9", "O": "0", "o": "0",
    "I": "1", "l": "1", "S": "5", "B": "8",
})
_WEEK_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
# 900×1600 截图实测：价格列中心 71.5 + 126*i。行距随日历档位变化
# （国内 88px、国际 107px），由 `_row_pitch` 从本次 OCR 结果实测；
# ROW_STEP/FIRST_ROW_DY 只在测不出行距时兜底。
COL0 = 71.5
COL_STEP = 126.0
FIRST_ROW_DY = 106.0
ROW_STEP = 88.0

#: 按屏幕宽度标定的列几何：(列中心起点, 列距, 首行相对月标题的 dy)。
#: 900×1600 是历史基准；1260×2800 与选日栅格（app_ctrip_parse 的
#: CAL_CALIB）用同一组实测值，避免两条路各标一套。
_CAL_GEO = {
    900.0: (71.5, 126.0, 106.0),
    1260.0: (90.0, 180.0, 139.0),
}


def _geo(width=None):
    """取该宽度下的 (col0, col_step, first_row_dy)；未知宽度按 900 等比缩放。"""
    try:
        w = float(width) if width else None
    except (TypeError, ValueError):
        w = None
    if not w:
        return (COL0, COL_STEP, FIRST_ROW_DY)
    if w in _CAL_GEO:
        return _CAL_GEO[w]
    k = w / 900.0
    return (COL0 * k, COL_STEP * k, FIRST_ROW_DY * k)
_ROW_CLUSTER_DY = 25.0
_PRICE_MAX_DX = 48.0
# 机票不会是 ¥1：OCR 把 1001 拆成 1+001 时只认后段会读出 1，
# 宁可丢这一格也不写假价。
_PRICE_MIN = 10.0


def _price_num(text: str):
    s = re.sub(r"[,\s]", "", (text or "").translate(_DIGIT_FIX))
    m = re.search(r"\d{2,6}", s)
    return float(m.group()) if m else None


def _month_headers(words, x_max=240.0):
    """[(year, month, header_y)]，按 y 排序；只取左侧标题区。"""
    lines = []
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        if w["x"] > x_max:
            continue
        for ln in lines:
            if abs(ln["y"] - w["y"]) <= 12:
                ln["ws"].append(w)
                break
        else:
            lines.append({"y": w["y"], "ws": [w]})
    out = []
    for ln in lines:
        txt = "".join(x["t"] for x in sorted(ln["ws"], key=lambda x: x["x"]))
        m = _MONTH_RE.search(txt)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), int(ln["y"])))
    return sorted(out, key=lambda x: x[2])


def _price_cells(words):
    """[(center_x, y, price)]：把 `¥` 与右侧金额合成一个日格锚点。

    OCR 会把 `¥1001` 拆成 `¥` + `1` + `001` 三个相邻词块（真机国际档
    截图实测），相邻数字块要先拼回一个价格再取数。
    """
    out = []
    for w in words:
        if w["t"].strip() not in ("￥", "¥"):
            continue
        right = []
        for v in words:
            if v is w or abs(v["y"] - w["y"]) > 10:
                continue
            if v["x"] < w["x"]:
                continue
            if v["x"] - (w["x"] + w["w"]) > _PRICE_MAX_DX:
                continue
            # 单个数字也可能是被拆开的金额（1001 → 1 + 001），
            # 先收进来拼接，拼完再校验。
            if not re.search(r"\d", v["t"].translate(_DIGIT_FIX)):
                continue
            right.append(v)
        right.sort(key=lambda v: v["x"])
        chosen = []
        for v in right:
            if chosen and v["x"] - (chosen[-1]["x"] + chosen[-1]["w"]) > 6:
                break
            chosen.append(v)
        if not chosen:
            # 金额与货币符号被 OCR 合成一个词块（如 `¥1068`）
            p = _price_num(w["t"])
            if p is not None and p >= _PRICE_MIN:
                out.append(((w["x"] + w["w"]) / 2.0, w["y"], p))
            continue
        p = _price_num("".join(v["t"] for v in chosen))
        if p is None or p < _PRICE_MIN:
            continue
        end = chosen[-1]["x"] + chosen[-1]["w"]
        out.append(((w["x"] + end) / 2.0, w["y"], p))
    return out


def _row_centers(prices, hy, nxt):
    """某个月标题带内的价格行 y 中心（同一行 OCR 抖动按 25px 聚类）。"""
    ys = sorted({py for _, py, _ in prices if hy <= py < nxt})
    clusters = []
    for y in ys:
        if clusters and y - clusters[-1][-1] <= _ROW_CLUSTER_DY:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    return [sum(c) / len(c) for c in clusters]


def _row_pitch(prices, heads):
    """从截图实测周行距（国内 88 / 国际 107）；跨月大缝不参与取最小值。"""
    diffs = []
    for i, (_y, _m, hy) in enumerate(heads):
        nxt = heads[i + 1][2] if i + 1 < len(heads) else 10 ** 9
        cys = _row_centers(prices, hy, nxt)
        for a, b in zip(cys, cys[1:]):
            d = b - a
            if 40 <= d <= 200:
                diffs.append(d)
    return min(diffs) if diffs else ROW_STEP


def _weekday_label(d, today):
    delta = (d - today).days
    if delta in (0, 1, 2):
        return ("今天", "明天", "后天")[delta]
    return _WEEK_CN[d.weekday()]


def parse_calendar_words(words, today=None, width=None):
    """OCR 词块 → [{date, weekday, price}]（只含能反推且有价的日期）。

    空/坏输入返回 []；不猜没有价格的日期，不造月外日期。
    """
    if not words:
        return []
    today = today or _dt.date.today()
    col0, col_step, first_dy = _geo(width)
    # 左栏界限按宽度缩放：900 下是 240，1260 下是 336。
    heads = _month_headers(words,
                           x_max=(float(width) if width else 900.0)
                           * 240.0 / 900.0)
    if not heads:
        return []
    prices = _price_cells(words)
    if not prices:
        return []
    pitch = _row_pitch(prices, heads)
    out = {}
    for i, (y, m, hy) in enumerate(heads):
        nxt = heads[i + 1][2] if i + 1 < len(heads) else 10 ** 9
        first = _dt.date(y, m, 1)
        days = _cal.monthrange(y, m)[1]
        # 周日=0..周六=6（截图表头 日..六）
        offset = (first.weekday() + 1) % 7
        cys = _row_centers(prices, hy, nxt)
        if not cys:
            continue
        # 首行一般在标题下 ~105px；若首行整行无价（都已过期/不可售），
        # 第一个价格行会落到 ~210px，此时用标题兜底换算，不把第 2 行当第 1 行。
        # 首行可能整行无价（都已过期/不可售），此时用标题兜底换算。
        _near = first_dy * 1.25          # 阈值也按宽度缩放（900 下≈132）
        base = cys[0] if cys[0] - hy <= _near else hy + first_dy
        for cx, py, price in prices:
            if not (hy <= py < nxt):
                continue
            col = int(round((cx - col0) / col_step))
            if col < 0 or col > 6:
                continue
            row = int(round((py - base) / pitch))
            if row < 0:
                continue
            # 价格必须落在某条周行线上，否则是横幅/节日标签里的数字。
            if abs(py - (base + row * pitch)) > pitch * 0.45:
                continue
            day = 1 + row * 7 + col - offset
            if day < 1 or day > days:
                continue
            d = _dt.date(y, m, day)
            if d not in out or price < out[d]:
                out[d] = price
    return [{"date": d.isoformat(),
             "weekday": _weekday_label(d, today),
             "price": float(out[d])}
            for d in sorted(out)]
