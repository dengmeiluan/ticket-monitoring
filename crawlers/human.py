# -*- coding: utf-8 -*-
"""拟人化交互：鼠标轨迹、滚动惯性、打字节奏、停顿分布。

为什么需要（风控里最便宜的一层）
--------------------------------
风控不只算频率，还算**形状**：

* 鼠标从 A 到 B 是**瞬移**（``page.click`` 的默认行为）——真人的轨迹是
  带弧度的、有加速减速的、落点有 1–4px 抖动；
* 请求间隔服从**均匀分布**（本项目 ``delay_min/delay_max`` 的现状）——
  真人的间隔是重尾的（多数 3–8s，偶尔 30s 去接水）；
* 页面打开后 **0 秒**就点目标控件——真人会先扫一眼（滚动/悬停）。

这三条都不需要「更像人」的玄学，只要**分布形状**对：均匀 → 对数正态，
瞬移 → 贝塞尔 + 抖动。它们不改变任何业务语义，只在「养号 / 预热 / 登录
窗口」这类**本来就要停一会儿**的地方使用，因此对采集耗时的边际成本≈0。

使用边界
--------
* 只在 ``warmup()`` 与人工验证窗口里调用（见 ``crawlers/base.py``）；采集
  主路径**不插入**这些动作——那里每一次多余操作都可能点错控件。
* 全部 fail-soft：页面已关闭、浏览器崩了，异常吞掉，调用方照常继续。
* 随机源可注入（``rng``），测试里给固定 seed 即可复现。
"""
from __future__ import annotations

import math
import random
import time


def rng_for(seed=None) -> random.Random:
    """随机源。``seed=None`` 用系统熵（真随机）；测试传固定值。"""
    return random.Random(seed)


def human_delay(lo: float = 1.0, hi: float = 4.0,
                rng: random.Random = None) -> float:
    """重尾间隔：对数正态夹到 ``[lo, hi]``。

    均匀分布本身就是特征（机器人喜欢均匀）。对数正态在同样的均值下
    有更多的「短间隔 + 偶发长间隔」，与人手一致。
    """
    r = rng or random
    lo, hi = max(0.0, float(lo)), max(float(lo), float(hi))
    if hi <= 0:
        return 0.0
    mu = math.log(max(0.05, (lo + hi) / 2.0))
    try:
        v = r.lognormvariate(mu, 0.45)
    except Exception:
        v = (lo + hi) / 2.0
    return max(lo, min(hi, v))


def _bezier(p0, p1, steps=18, curve=0.35, rng=None):
    """两点之间的二次贝塞尔（控制点垂直偏移，模拟手腕弧线）。"""
    r = rng or random
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1.0
    # 法向量 × 随机幅度（正负随机，模拟不同方向的弧）
    off = r.uniform(-curve, curve) * n * 0.12
    cx, cy = (x0 + x1) / 2 + (-dy / n) * off, (y0 + y1) / 2 + (dx / n) * off
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((u * u * x0 + 2 * u * t * cx + t * t * x1,
                    u * u * y0 + 2 * u * t * cy + t * t * y1))
    return pts


def mouse_move(page, x: int, y: int, rng: random.Random = None,
               steps: int = None) -> bool:
    """把鼠标「走」到 (x, y)：贝塞尔轨迹 + 起落点抖动。失败返回 False。"""
    r = rng or random
    try:
        box = page.viewport_size or {"width": 1366, "height": 900}
        sx = r.randint(0, max(1, int(box.get("width", 1366)) - 1))
        sy = r.randint(0, max(1, int(box.get("height", 900)) - 1))
        page.mouse.move(sx, sy)
        for (px, py) in _bezier((sx, sy), (x, y),
                                steps=steps or r.randint(14, 26), rng=r):
            # 每个采样点再抖 1px：轨迹不是数学曲线，是手抖
            page.mouse.move(px + r.uniform(-1.2, 1.2),
                            py + r.uniform(-1.2, 1.2))
            time.sleep(r.uniform(0.006, 0.024))
        # 落点微调（真人在按下前会修正 1–3px）
        page.mouse.move(x + r.uniform(-2.5, 2.5), y + r.uniform(-2.5, 2.5))
        return True
    except Exception:
        return False


def click(page, x: int, y: int, rng: random.Random = None) -> bool:
    """拟人点击：走过去 → 停 80–260ms → 按下 60–140ms 后松开。"""
    r = rng or random
    if not mouse_move(page, x, y, rng=r):
        return False
    try:
        time.sleep(r.uniform(0.08, 0.26))
        page.mouse.down()
        time.sleep(r.uniform(0.06, 0.14))
        page.mouse.up()
        return True
    except Exception:
        return False


def scroll(page, dy: int = 600, rng: random.Random = None) -> bool:
    """分段滚动 + 惯性尾：一次滚一大截是脚本特征，真人是一串 wheel。"""
    r = rng or random
    try:
        left = int(abs(dy))
        sign = 1 if dy >= 0 else -1
        while left > 0:
            step = min(left, r.randint(90, 260))
            page.mouse.wheel(0, sign * step)
            left -= step
            time.sleep(r.uniform(0.04, 0.16))
        # 惯性尾（滚动结束后的一点点回弹）
        page.mouse.wheel(0, sign * r.randint(10, 40))
        return True
    except Exception:
        return False


def type_text(page, text: str, rng: random.Random = None) -> bool:
    """逐字输入：间隔对数正态，偶尔 300–600ms 的「想一下」。"""
    r = rng or random
    try:
        for ch in str(text):
            page.keyboard.type(ch, delay=0)
            d = human_delay(70, 260, rng=r) / 1000.0
            if r.random() < 0.08:
                d += r.uniform(0.3, 0.6)
            time.sleep(d)
        return True
    except Exception:
        return False


def idle(page, lo: float = 0.8, hi: float = 2.4,
         rng: random.Random = None) -> float:
    """发呆：不操作，只等。返回实际秒数。"""
    d = human_delay(lo, hi, rng=rng)
    try:
        time.sleep(d)
    except Exception:
        pass
    return d


def warm(page, profile: str = "", rng: random.Random = None,
         rounds: int = 3) -> dict:
    """养号动作序列：扫一眼 → 滚两屏 → 回滚 → 悬停。

    这正是「登录前先把会话养熟」要的东西：让服务端看到的是一段**有停留、
    有滚动、有回访**的浏览，而不是「打开页面 → 直接 POST 登录」。

    返回 ``{"moves": n, "scrolls": n, "seconds": x}``；页面不可用则全 0。
    """
    r = rng or rng_for(profile)
    rep = {"moves": 0, "scrolls": 0, "seconds": 0.0}
    t0 = time.time()
    try:
        box = page.viewport_size or {"width": 1366, "height": 900}
        w = int(box.get("width", 1366))
        h = int(box.get("height", 900))
        for _ in range(max(1, int(rounds))):
            if mouse_move(page, r.randint(int(w * 0.2), int(w * 0.8)),
                          r.randint(int(h * 0.2), int(h * 0.7)), rng=r):
                rep["moves"] += 1
            idle(page, 0.5, 1.6, rng=r)
            if scroll(page, r.randint(400, 900), rng=r):
                rep["scrolls"] += 1
            idle(page, 0.6, 1.8, rng=r)
        # 回滚到顶部（真人会回到搜索框）
        scroll(page, -r.randint(600, 1200), rng=r)
        idle(page, 0.4, 1.2, rng=r)
    except Exception:
        pass
    rep["seconds"] = round(time.time() - t0, 2)
    return rep
