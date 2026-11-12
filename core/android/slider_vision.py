# -*- coding: utf-8 -*-
'''r1063 T86：滑块**截图兜底**——UI 树没有节点时，用 OCR 在截图里定位轨道。

真机背景（飞猪，2026-11-08 12:39）：阿里 NC 滑块把控件画在 canvas 里，
`uiautomator`/u2 的 UI 树里**只有 `WVUCWebView` 和一两行文案**，而且文案
在渲染早期还会消失。于是 `appvcode.solve()` 的"按文案找轨道"经常找不到。

做法：`solve_by_ocr(dev)` —— 截图 → Windows OCR 拿词块坐标 →
用「向右滑动验证 / 拖动下方滑块」那一行定位轨道带 → 走同一条人化轨迹。

判据：
* 命中即说明**这屏就是滑块页**（不依赖 UI 树）；
* 轨道 y 取该行文字的垂直中心；x 从屏幕 12% 到 85%（阿里轨道常态），
  手柄从轨道左端 +30px 起手；
* 过没过的判据：再过一次 OCR，滑块文案消失。
'''
from __future__ import annotations

import time

from . import ocr

SLIDER_TEXTS = ("向右滑动验证", "拖动下方滑块", "滑动验证", "通过验证以")
# 滑块文案的关键字符（OCR 可能乱序，故按字符集判）
_CHARS = set("向右滑动验证拖动下方滑块通过以确保正常访问")


def _lines(words):
    """把 OCR 词块按 y 归行：返回 [{y, h, text, x0, x1}]（按 y 升序）。"""
    rows = []
    for w in sorted(words or [], key=lambda x: (int(x.get("y") or 0),
                                                int(x.get("x") or 0))):
        y = int(w.get("y") or 0)
        h = int(w.get("h") or 1)
        placed = None
        for r in rows:
            if abs(r["yc"] - (y + h // 2)) <= max(h, r["h"]) // 2:
                placed = r
                break
        if placed is None:
            placed = {"yc": y + h // 2, "h": h, "parts": [], "x0": None,
                      "x1": None}
            rows.append(placed)
        placed["parts"].append(str(w.get("t") or ""))
        x = int(w.get("x") or 0)
        placed["x0"] = x if placed["x0"] is None else min(placed["x0"], x)
        placed["x1"] = x + int(w.get("w") or 0) if placed["x1"] is None \
            else max(placed["x1"], x + int(w.get("w") or 0))
    out = []
    for r in sorted(rows, key=lambda z: z["yc"]):
        out.append({"y": r["yc"], "h": r["h"], "text": "".join(r["parts"]),
                    "x0": r["x0"] or 0, "x1": r["x1"] or 0})
    return out


def find_track(words, screen_w: int = 0, screen_h: int = 0):
    """从 OCR 词块里定位滑块轨道 → {from, to, y, text} 或 None。

    先按行拼文本再匹配（OCR 会拆单字）；命中行的 y 就是轨道中线，
    轨道水平范围取**该行文字范围两侧留白**（文字居中排在轨道里）。
    """
    _cands = []
    for ln in _lines(words):
        # OCR 会把艺术字读成乱序（实测 `向右动验滑证`），所以按**命中字符数**判：
        # 一行里出现 ≥3 个滑块关键词字符，就认定是候选行。
        _hit = sum(1 for ch in ln["text"] if ch in _CHARS)
        if _hit < 3 and not any(k in ln["text"] for k in SLIDER_TEXTS):
            continue
        _cands.append(ln)
    # 命中多行是常态（标题、副标题、轨道文案都命中）：取**最下面那一行**
    # ——轨道在标题下方；同时排除页脚（>90% 高度）。
    _H = int(screen_h or 2800)
    _cands = [ln for ln in _cands if ln["y"] < _H * 0.9]
    for ln in (sorted(_cands, key=lambda z: -z["y"])[:1]):
        W = int(screen_w or 1260)
        y = int(ln["y"])
        # 轨道左右各留一点余量；夹到屏幕内
        # 轨道宽度**不能**用文字宽度推（文字只占轨道中间一段）：
        # 用经验轨道带 12%..85%；若文字行本身更宽则以文字行为界。
        x0, x1 = int(W * 0.12), int(W * 0.85)
        if ln["x0"] and ln["x0"] < x0:
            x0 = max(0, int(ln["x0"]) - 4)
        if ln["x1"] and ln["x1"] > x1:
            x1 = min(W - 2, int(ln["x1"]) + 4)
        return {"from": (x0, y), "to": (x1, y), "y": y,
                "text": ln["text"][:24], "distance": x1 - x0}
    return None


def visible(dev) -> bool:
    """截图 + OCR 判断这一屏是不是滑块页（不依赖 UI 树）。"""
    try:
        png = dev.screencap() or b""
        if not png:
            return False
        return find_track(ocr.ocr_words(png)) is not None
    except Exception:
        return False


def solve_by_ocr(dev, *, tries: int = 2, log=None) -> dict:
    """用截图定位 + 人化轨迹尝试过滑块。返回 {ok, tries, why, geometry}。"""
    from .appvcode import human_path

    rep = {"ok": False, "tries": 0, "why": "", "geometry": None}
    for i in range(max(1, int(tries))):
        rep["tries"] = i + 1
        try:
            png = dev.screencap() or b""
        except Exception as e:
            rep["why"] = "截图失败：%s" % type(e).__name__
            return rep
        track = find_track(ocr.ocr_words(png))
        if track is None:
            rep["why"] = "截图里没找到滑块轨道（可能已不在验证页）"
            return rep
        rep["geometry"] = track
        pts = human_path(track["from"][0], track["from"][1], track["to"][0],
                         seed=i + 1)
        try:
            fn = getattr(dev, "u2_swipe_points", None)
            if callable(fn):
                fn(pts, 1.1 + 0.2 * i)
            else:
                dev.swipe(track["from"][0], track["from"][1],
                          track["to"][0], track["to"][1], 900)
        except Exception as e:
            rep["why"] = "滑动失败：%s" % str(e)[:60]
        time.sleep(2.0)
        try:
            gone = not visible(dev)
        except Exception:
            gone = False
        if gone:
            rep["ok"] = True
            rep["why"] = "已通过（截图里不再有滑块文案）"
            if log:
                try:
                    log.info("[android] 滑块（截图兜底）已通过，第 %d 次", i + 1)
                except Exception:
                    pass
            return rep
        rep["why"] = "滑动后仍在验证页（轨迹可能仍被识别为机器）"
    return rep
