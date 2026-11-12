"""App 内滑块验证的识别与自动尝试（r1063 T81）。

**现场证据**（2026-11-08 真机，飞猪 App 点「机票」后）：
屏幕是阿里 `_____tmd_____` / NC 滑块页，UI 树里只有 WebView + 几行文案：

    验证码拦截 / 亲，请拖动下方滑块完成验证 / 通过验证以确保正常访问
    [滑块] 向右滑动验证

我们用 `input swipe` 单段等速滑过一次，页面回的是
`请点我重试(error:x2VW8)` —— 这是**轨迹被判成机器**，不是位置不对。
所以自动尝试必须用**多段变速轨迹**（缓动 + 微抖动 + 端点微调），
而不是一条直线。

设计原则：
* 只处理"**滑到底**"型（轨道与手柄都在 UI 树里），不碰缺口拼图（那需要另做视觉）；
* 尝试次数有限（默认 2 次），失败如实上报并给下一步建议；
* 全程 fail-soft：解不动就让上层照旧记 `captcha`，绝不把采集搞死。
"""

from __future__ import annotations

import random
import re
import time

# 阿里 / 通用滑块页的文案特征（命中两个以上才算，避免误判正文）
SLIDER_MARKS = ("拖动下方滑块", "向右滑动验证", "请按住滑块", "滑动验证",
                "通过验证以", "验证码拦截")

_NODE_RE = re.compile(r"<node[^>]*>")
_BOUND_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def _nodes(xml):
    """[(text, cx, cy, w, h)]：只取有 bounds 的节点。"""
    out = []
    for tag in _NODE_RE.findall(xml or ""):
        t = re.search(r'text="([^"]*)"', tag)
        b = _BOUND_RE.search(tag)
        if not b:
            continue
        x1, y1, x2, y2 = (int(b.group(i)) for i in range(1, 5))
        out.append(((t.group(1) if t else "").strip(),
                    (x1 + x2) // 2, (y1 + y2) // 2, x2 - x1, y2 - y1))
    return out


def is_slider_page(xml: str) -> bool:
    """这一屏是不是"滑到底"型滑块验证页。"""
    texts = " ".join(n[0] for n in _nodes(xml))
    hits = sum(1 for m in SLIDER_MARKS if m in texts)
    return hits >= 2


def slider_geometry(xml: str):
    """找出 (手柄点, 轨道右端)。找不到返回 None。

    手柄＝文案「滑块」且**靠左**的节点（阿里把可拖动的圆钮放左端，
    宽度通常小于轨道的一半）；轨道＝「向右滑动验证」那条长条。
    """
    nodes = _nodes(xml)
    track = None
    for t, cx, cy, w, h in nodes:
        if "向右滑动验证" in t or "滑动验证" in t and w > 300:
            track = (cx, cy, w, h)
            break
    handle = None
    for t, cx, cy, w, h in nodes:
        if t == "滑块":
            handle = (cx, cy, w, h)
            break
    if track is None:
        return None
    tx, ty, tw, th = track
    if handle is not None:
        sx, sy = handle[0], handle[1]
    else:
        # 没有「滑块」文案：从轨道左端往里 40px 起手
        sx, sy = tx - tw // 2 + 40, ty
    # 轨道右端再往里收一点（贴边常被判"没滑到位/滑过头"）
    ex = tx + tw // 2 - 12
    return {"from": (int(sx), int(sy)), "to": (int(ex), int(sy)),
            "distance": int(ex - sx)}


def human_path(x0: int, y0: int, x1: int, *, steps: int = 46,
               seed: int = 0) -> list:
    """单调缓动 + 微抖动 + 端点微调的轨迹（人手像一点）。

    与"一条直线"的区别正是阿里 NC 判机器的地方：变速、y 轴微抖、
    末尾回一点再停。
    """
    rng = random.Random(seed or int(time.time() * 1000) % 100000)
    dist = x1 - x0
    pts = []
    # 留最后两档给"端点微调"，保证整条轨迹**单调向右**（回退会被判机器）
    for i in range(1, max(2, steps - 1)):
        t = i / float(steps)
        e = 1 - (1 - t) ** 1.8          # ease-out：先快后慢
        pts.append((int(round(x0 + dist * e)),
                    int(round(y0 + rng.uniform(-2.2, 2.2)))))
    pts.append((x1 - 3, y0 + rng.randint(-1, 1)))
    pts.append((x1, y0))
    return [p for p in pts if p[0] <= x1]


def solve(dev, xml: str = "", *, tries: int = 2, log=None) -> dict:
    """尝试过一次滑块。返回 {ok, tries, why, geometry}。

    `dev` 需要支持 `dump()` 与（可选）`u2_swipe_points(points, dur)`。
    """
    rep = {"ok": False, "tries": 0, "why": "", "geometry": None}
    if not xml:
        try:
            xml = dev.dump() or ""
        except Exception as e:
            rep["why"] = "取页面失败：%s" % type(e).__name__
            return rep
    geo = slider_geometry(xml)
    rep["geometry"] = geo
    if not geo:
        rep["why"] = "没找到滑块轨道/手柄"
        return rep
    for i in range(max(1, int(tries))):
        rep["tries"] = i + 1
        pts = human_path(geo["from"][0], geo["from"][1], geo["to"][0],
                         seed=0 if i == 0 else i + 1)
        ok = False
        try:
            fn = getattr(dev, "u2_swipe_points", None)
            if callable(fn):
                ok = bool(fn(pts, 1.0 + 0.2 * i))
            else:
                ok = bool(dev.swipe(geo["from"][0], geo["from"][1],
                                    geo["to"][0], geo["to"][1],
                                    900 + 200 * i))
        except Exception as e:
            rep["why"] = "%s: %s" % (type(e).__name__, str(e)[:80])
        time.sleep(1.8)
        try:
            after = dev.dump() or ""
        except Exception:
            after = ""
        if after and not is_slider_page(after):
            rep["ok"] = True
            rep["why"] = "已通过（页面不再有滑块）"
            if log:
                try:
                    log.info("[android] 滑块已通过（第 %d 次尝试）", i + 1)
                except Exception:
                    pass
            return rep
        # 记录平台自报的错误码，便于区分"轨迹被识别"与"位置不对"
        m = re.search(r"error[：:]\s*([A-Za-z0-9]+)", after or "")
        if m:
            rep["why"] = "平台回报 error:%s（多为轨迹被判机器）" % m.group(1)
    return rep
