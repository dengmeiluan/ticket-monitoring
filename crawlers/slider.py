# -*- coding: utf-8 -*-
"""滑块分级与「简单滑块」自动尝试。

为什么要分级，而不是"有滑块就解"
--------------------------------
滑块不是一类东西，是两类完全不同的东西：

* **简单滑块**：一张背景图 + 一个形状固定的缺口，拖动条把方块送到缺口即可。
  判定落在**几何**上（缺口位置），没有采集你的鼠标轨迹做模型判别。
  这类在技术上可以稳定复现：找缺口 → 走一条像人的轨迹 → 校验缺口是否闭合。
* **强人机**：极验 v4 智能验证、腾讯天御、阿里 baxia/无痕、reCAPTCHA/hCaptcha、
  点选文字/图片、行为序列模型。它们的判定输入是**你的行为分布本身**
  （加速度、抖动频谱、停顿分布、设备传感器相关性）。这类不是"算不出来"，
  而是"越算越像机器"——花成本还把自己打成高风控分。

所以本模块的第一件事是**分级**（`classify`），第二件事才是**尝试**，且：

========================  ==================================================
约束                      理由
========================  ==================================================
默认关闭（`off`）          仓库既有立场是「识别 → 记账 → 停手 → 人来过」，
                          自动尝试必须是操作员显式打开的能力
只对 `simple` 尝试         `strong`/`unknown` 一律不动手——判错一次就是
                          一条「自动化行为」样本，代价远大于收益
每次最多 `max_attempts`    失败一次就记账，不重试风暴
每日上限 + 连续失败拉黑    `slider_ledger.json`：某渠道连续 2 次失败 →
                          7 天内不再尝试（风控是动态的，硬试只会更糟）
不接第三方打码服务         不开这个口子：它是把账号交给陌生人
========================  ==================================================

对外接口
--------
``classify(html, text)`` → ``Tier(name, confidence, reasons)``
``find_gap(png, bbox)`` → ``(offset_x, candidates)``   纯图像计算，离线可测
``trajectory(distance)`` → ``[(dx, dy, delay_s), ...]`` 拟人轨迹，含回拉
``should_attempt(plat, cfg)`` → ``(bool, why)``         预算/黑名单
``attempt_page(page, plat, cfg)`` → ``bool``            浏览器侧一次完整尝试
``attempt_device(dev, plat, cfg)`` → ``bool``           App 侧（坐标拖动）
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import random
import time

# ---------------------------------------------------------------------------
# 分级
# ---------------------------------------------------------------------------
# 强人机标记：命中任一即 upcast 到 strong（**只加不减**，宁可少解）
_STRONG_MARKS = (
    # 极验 v4 / 智能验证：没有固定缺口，判定看行为
    "极验", "geetest", "gt4", "sensebot", "智能验证", "无感验证",
    # 腾讯天御 / 阿里 baxia
    "tcaptcha", "天御", "tencent captcha", "baxia", "whaleguard", "无痕",
    # 国际
    "recaptcha", "hcaptcha", "turnstile", "cf-challenge", "arkose",
    # 语义/点选类：不是几何题
    "点选", "请按顺序点击", "按顺序点击", "选出", "依次点击",
    # 活体/人脸
    "人脸", "活体", "眨眼", "摇头",
)

# 简单滑块标记：几何题
_SIMPLE_MARKS = (
    "拖动滑块", "拖动下方滑块", "滑动验证", "按住滑块", "向右拖动",
    "拖动左侧滑块", "slide to verify", "slide-verify", "slider",
)

# 简单滑块的 DOM 特征（存在这些类名/结构说明是经典拼图）
_SIMPLE_DOM = ("slide-verify", "slider-verify", "sliderContainer", "nc_1_n1",
               "verify-slider", "slider-btn", "slideBlock", "slide-block")

TIERS = ("off", "simple", "strong", "unknown")


class Tier:
    """分级结果。``name`` 只会是 ``simple`` / ``strong`` / ``unknown``。"""

    __slots__ = ("name", "confidence", "reasons")

    def __init__(self, name: str, confidence: float = 0.0, reasons=None):
        self.name = name if name in TIERS else "unknown"
        self.confidence = float(confidence)
        self.reasons = list(reasons or [])

    @property
    def solvable(self) -> bool:
        """只有 simple 才算"可尝试"。strong/unknown 一律交给人工。"""
        return self.name == "simple"

    def as_dict(self) -> dict:
        return {"name": self.name, "confidence": round(self.confidence, 2),
                "solvable": self.solvable, "reasons": list(self.reasons)}

    def __repr__(self):
        return "<Tier %s %.2f>" % (self.name, self.confidence)


def classify(html: str = "", text: str = "") -> Tier:
    """判断这是「简单滑块」还是「强人机」。

    判据全部是**可复现的字符串证据**，不做"看起来像"的猜测：
    先命中强人机标记就 upcast（安全侧），再找简单滑块标记 + 拼图 DOM。
    """
    blob = ("%s\n%s" % (html or "", text or "")).lower()
    if not blob.strip():
        return Tier("unknown", 0.0, ["空页面"])

    strong = [m for m in _STRONG_MARKS if m.lower() in blob]
    if strong:
        return Tier("strong", 0.95,
                    ["命中强人机标记：%s" % "、".join(strong[:3])])

    simple = [m for m in _SIMPLE_MARKS if m.lower() in blob]
    dom = [m for m in _SIMPLE_DOM if m.lower() in blob]
    if simple and dom:
        return Tier("simple", 0.9,
                    ["简单滑块文案：%s" % simple[0],
                     "拼图 DOM：%s" % dom[0]])
    if simple:
        # 只有文案没有拼图结构：可能是自定义实现，给中等置信度
        return Tier("simple", 0.55, ["只有滑块文案：%s（无拼图 DOM）" % simple[0]])
    if dom:
        return Tier("simple", 0.6, ["只有拼图 DOM：%s" % dom[0]])
    return Tier("unknown", 0.2, ["没有任何滑块/人机标记"])


# ---------------------------------------------------------------------------
# 缺口检测（纯图像，离线可测）
# ---------------------------------------------------------------------------
_NP_WARNED = False


def _np():
    """取 numpy。缺失时只告警一次：空候选必须能区分「没找到缺口」和
    「环境缺依赖」，否则滑块尝试失败在日志里表现为正常的无候选。"""
    global _NP_WARNED
    try:
        import numpy as np
        return np
    except Exception as exc:
        if not _NP_WARNED:
            _NP_WARNED = True
            logging.getLogger(__name__).warning(
                "numpy 不可用，滑块缺口检测将始终返回空候选；"
                "请安装 requirements.txt（%s）", exc)
        return None


def _open_gray(png: bytes):
    try:
        from PIL import Image
        return Image.open(io.BytesIO(png)).convert("L")
    except Exception:
        return None


def find_gap(png: bytes, bbox=None, *, gap_min: int = 24, gap_max: int = 140,
             top: int = 3, min_offset: int = 12) -> tuple:
    """在滑块条区域里找缺口中心的 x 偏移。

    算法（刻意简单、可解释）：
      1. 取灰度图 + 灰度列方向一阶差分 → **竖直边缘强度**（缺口两侧一定有边）；
      2. 用宽度 ``gap_min..gap_max`` 的滑动窗求和 → 找"两条边 + 中间有落差"
         的整体响应最大处（单看某一条边会被背景纹理骗）；
      3. 返回响应最高的前 ``top`` 个候选的**窗口中心**。

    为什么不用模板匹配：缺口形状/透明度各家不同，模板要一家一份；边缘能量
    是形状无关的，代价是精度差几像素——而滑块验证一般留 5–10px 容差，
    实测够用。精度不够时用 ``top`` 候选逐个试（`attempt_*` 里已实现）。

    返回 ``(best_offset, [(offset, score), ...])``；失败返回 ``(0, [])``。
    """
    np = _np()
    im = _open_gray(png)
    if np is None or im is None:
        return 0, []
    arr = np.asarray(im)
    if arr.ndim != 2 or arr.size == 0:
        return 0, []
    h, w = arr.shape
    if bbox:
        try:
            x0, y0, x1, y1 = [int(v) for v in bbox]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            if x1 - x0 > 20 and y1 - y0 > 10:
                arr = arr[y0:y1, x0:x1]
                h, w = arr.shape
        except (TypeError, ValueError):
            pass
    if w < 60 or h < 12:
        return 0, []

    roi = arr.astype(np.int16)
    # 列方向边缘强度：横向差分后按列求和（跨越缺口两边时响应高）
    edge = np.abs(np.diff(roi, axis=1)).mean(axis=0)      # 长度 w-1
    if float(edge.max() or 0) < 1.0:                      # 纯色/无纹理
        return 0, []

    lo = max(2, int(min_offset))
    # 缺口在物理上就是**两条强竖直边**夹一块区域，所以按"成对的局部极大"
    # 配对打分；按单条边打分会被背景纹理或滑块的起始方块骗走（实测：最小
    # 窗口总能抢到最高分，于是返回的是某一条边而不是缺口中心）。
    thr = float(edge.max()) * 0.35
    peaks = [i for i in range(lo, len(edge) - 1)
             if edge[i] >= thr and edge[i] >= edge[i - 1]
             and edge[i] >= edge[i + 1]]
    if len(peaks) < 2:
        return 0, []
    gap_lo = max(8, int(gap_min) // 2)
    gap_hi = max(gap_lo + 4, int(gap_max))
    best = []
    for i in range(len(peaks)):
        for j in range(i + 1, len(peaks)):
            a, b = peaks[i], peaks[j]
            gap = b - a
            if gap < gap_lo or gap > gap_hi:
                continue
            inside = float(edge[a + 1:b].mean()) if b > a + 1 else 0.0
            # 两侧边要强、中间要平（缺口内部没有纹理）
            score = float(edge[a] + edge[b]) - inside
            best.append((int((a + b) // 2), round(score, 3)))
    if not best:
        return 0, []
    ranked = sorted(best, key=lambda kv: -kv[1])
    return ranked[0][0], ranked[:top]
    if not best:
        return 0, []
    # 同一位置被多个宽度覆盖 → 按位置聚合取最高分
    agg = {}
    for off, sc in best:
        key = int(round(off / 8.0)) * 8
        agg[key] = max(agg.get(key, 0.0), sc)
    ranked = sorted(((k, v) for k, v in agg.items()), key=lambda kv: -kv[1])
    # 去掉贴边的候选（那里通常是"起点方块"自己）
    ranked = [kv for kv in ranked if kv[0] >= lo] or ranked
    return ranked[0][0], ranked[:top]


# ---------------------------------------------------------------------------
# 拟人轨迹
# ---------------------------------------------------------------------------
def trajectory(distance: int, rng: random.Random = None,
               duration: float = None) -> list:
    """生成一条"像人"的拖动轨迹：``[(dx, dy, delay_s), ...]``。

    三条与真实手部动作对齐的性质：

    1. **加速—巡航—减速**：起步慢、中段快、末尾收（用平滑 S 曲线的离散化）；
    2. **回拉**：中途 1–2 次轻微反向（人不会一路单调推到底），幅度 2–6px；
    3. **落点修正**：最后 20% 内有一次 1–3px 的微调，终点不抖。

    返回的是**增量**序列（每次移动多少、停多久），总位移严格等于 distance。
    """
    r = rng or random
    d = int(max(1, abs(int(distance))))
    if duration is None:
        # 人类拖 200–400px 大约 0.7–1.5s
        duration = max(0.55, min(1.8, 0.45 + d / 420.0)) * r.uniform(0.9, 1.15)
    n = max(18, min(60, int(d / 8) + 14))

    # 先算**位置**再算增量：这样终点天然精确，不会因为逐段抖动累积漂移。
    pos = []
    for i in range(1, n + 1):
        t = i / n
        pos.append(int(round(d * (t * t * (3 - 2 * t)))))   # smoothstep
    pos[-1] = d
    steps = []
    prev = 0
    for p in pos:
        steps.append(p - prev)
        prev = p

    # 回拉：成对插入（净位移 0），模拟中途的轻微反向修正
    if len(steps) >= 12 and d >= 80:
        k = int(len(steps) * r.uniform(0.55, 0.75))
        back = r.randint(2, 6)
        steps.insert(k, -back)
        steps.insert(k + 1, back)

    per = duration / max(1, len(steps))
    out = []
    for i, step in enumerate(steps):
        # 纵向抖动只改 y（不改 dx，否则终点就不精确了）
        dy = r.choice((0, 0, 0, 1, -1)) if i % 5 == 0 else 0
        out.append((step, dy, max(0.004, per * r.uniform(0.6, 1.35))))

    # 落点修正：同样成对（一 -1 一 +1，净零）+ 松手前的停留
    if len(out) >= 6 and d >= 40:
        j = r.choice((-1, 1))
        out.insert(len(out) - 1, (j, 0, r.uniform(0.03, 0.07)))
        out.insert(len(out) - 1, (-j, 0, r.uniform(0.03, 0.07)))
        out.append((0, 0, r.uniform(0.15, 0.35)))
    return out


def apply_trajectory(move, x: float, y: float, distance: int,
                     rng: random.Random = None, sleep=None) -> float:
    """按轨迹调用 ``move(dx, dy)``。返回总耗时（秒）。

    ``move`` 是 ``(dx, dy) -> None`` 的可调用对象（浏览器传 mouse.move 的包装，
    设备传相对滑动的实现）。全部异常吞掉——解不出来不该影响采集主流程。
    """
    t0 = time.time()
    sleep = sleep or time.sleep
    try:
        for dx, dy, delay in trajectory(distance, rng=rng):
            move(dx, dy)
            if delay:
                sleep(delay)
    except Exception:
        pass
    return time.time() - t0


# ---------------------------------------------------------------------------
# 预算 / 黑名单（跨进程持久化）
# ---------------------------------------------------------------------------
LEDGER = "slider_ledger.json"
BLACKLIST_S = 7 * 86400


def _ledger_path(user_data_dir: str, profile: str) -> str:
    base = os.path.join(str(user_data_dir or "user_data"), profile or "")
    return os.path.join(base, LEDGER)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        pass


def _cfg(config: dict = None) -> dict:
    sec = (config or {}).get("slider") if isinstance(config, dict) else None
    return sec if isinstance(sec, dict) else {}


def _flag(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "simple", "auto")
    return bool(v)


def should_attempt(plat: str, config: dict = None, *,
                   user_data_dir="user_data", profile="",
                   now: float = None) -> tuple:
    """``(是否允许尝试, 原因)``。默认关闭——必须先显式打开。"""
    ts = float(now if now is not None else time.time())
    sec = _cfg(config)
    mode = sec.get("auto")
    if not _flag(mode, False):
        return False, "未开启（crawler.slider.auto=false）"

    path = _ledger_path(user_data_dir, profile or str(plat))
    data = _load(path)
    rec = data.get(str(plat)) if isinstance(data.get(str(plat)), dict) else {}
    until = float(rec.get("blocked_until") or 0)
    if until > ts:
        return False, "连续失败冷却中（还剩 %d 小时）" % int((until - ts) // 3600 + 1)

    day = time.strftime("%Y%m%d", time.localtime(ts))
    used = int(rec.get("day_used") or 0) if rec.get("day") == day else 0
    cap = int(sec.get("daily_cap") or 3)
    if used >= cap:
        return False, "今日已达上限（%d/%d）" % (used, cap)
    return True, "ok"


def note_result(plat: str, ok: bool, config: dict = None, *,
                user_data_dir="user_data", profile="", now: float = None,
                kind: str = "") -> dict:
    """记一次尝试结果；连续失败 2 次 → 拉黑 7 天。

    ``kind`` 为类别标签（``slider`` / ``arithmetic`` / ``text``）。
    账本里额外维护 ``by_kind`` 分项——**总账仍是一本**（拉黑按总失败数算），
    分项只用于"哪一类更容易过"的观测，不参与预算决策。
    这样既不会因为分类别而让"失败 2 次拉黑"互相抵消，又能看出该关哪一类。
    """
    ts = float(now if now is not None else time.time())
    path = _ledger_path(user_data_dir, profile or str(plat))
    data = _load(path)
    rec = data.get(str(plat)) if isinstance(data.get(str(plat)), dict) else {}
    day = time.strftime("%Y%m%d", time.localtime(ts))
    if rec.get("day") != day:
        rec["day"] = day
        rec["day_used"] = 0
    rec["day_used"] = int(rec.get("day_used") or 0) + 1
    rec["tries"] = int(rec.get("tries") or 0) + 1
    if ok:
        rec["fails"] = 0
        rec["blocked_until"] = 0
        rec["last_ok"] = ts
    else:
        rec["fails"] = int(rec.get("fails") or 0) + 1
        rec["last_fail"] = ts
        if rec["fails"] >= int(_cfg(config).get("max_fails") or 2):
            rec["blocked_until"] = ts + BLACKLIST_S
    # 分项记账（只做观测，不影响预算）
    k = str(kind or "unknown")
    bk = rec.get("by_kind")
    bk = bk if isinstance(bk, dict) else {}
    item = bk.get(k) if isinstance(bk.get(k), dict) else {}
    item["tries"] = int(item.get("tries") or 0) + 1
    if ok:
        item["ok"] = int(item.get("ok") or 0) + 1
    else:
        item["fail"] = int(item.get("fail") or 0) + 1
    item["last"] = ts
    bk[k] = item
    rec["by_kind"] = bk
    rec["last_at"] = ts
    data[str(plat)] = rec
    _save(path, data)
    return rec


# ---------------------------------------------------------------------------
# 执行（浏览器 / 设备）
# ---------------------------------------------------------------------------
# 常见滑块控件选择器（按命中概率排；找不到就放弃，不去猜 DOM 结构）
_BTN_SELECTORS = (
    ".geetest_slider_button",
    "[class*=slide-verify] [class*=btn]",
    "[class*=slider] [class*=btn]",
    "[class*=slideBlock]",
    "[class*=slide-block]",
    "#nc_1_n1z",
    ".verify-move-block",
    "[class*=sliderContainer] div[class*=button]",
    "[class*=slider] span[class*=btn]",
)

_TRACK_SELECTORS = (
    "[class*=slide-verify]",
    "[class*=sliderContainer]",
    "[class*=slider-verify]",
    ".nc_scale",
    "[class*=slider]",
)


def _first_box(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el is None:
                continue
            box = el.bounding_box()
            if box and box.get("width", 0) > 20 and box.get("height", 0) > 8:
                return box
        except Exception:
            continue
    return None


def _shot(page) -> bytes:
    try:
        return page.screenshot(full_page=False) or b""
    except Exception:
        return b""


def _slider_gone(page) -> bool:
    """滑块是不是真的过去了——**看控件，不看文案**。

    踩过的坑：成功后页面里往往还留着 `.slide-verify` / `.slideBlock` 的
    CSS 类名（样式块不随控件删除），拿 ``classify(page.content())`` 复判会
    把"已通过"重新判成 simple，于是明明解开了却报失败（2026-11-03 E2E 实测）。

    可靠的信号按强度排：
      1. 滑块手柄元素消失 → 一定通过；
      2. 手柄还在但提示文案（"拖动滑块"等）没了 → 大概率通过；
      3. 手柄被复位到最左 → 明确失败（页面通常会归位让人重试）。
    """
    try:
        box = _first_box(page, _BTN_SELECTORS)
    except Exception:
        return False
    if box is None:
        return True
    try:
        body = page.inner_text("body")[:2000]
    except Exception:
        body = ""
    still_text = any(m in body for m in _SIMPLE_MARKS)
    if still_text:
        return False
    # 手柄还在、文案没了：再看它是否被归位到最左（归位=失败重试）
    try:
        edges = page.query_selector("[class*=sliderContainer]") \
            or page.query_selector("[class*=slider]")
        if edges is not None:
            tb = edges.bounding_box()
            if tb and box["x"] - tb["x"] <= 6:
                return False
    except Exception:
        pass
    return True


def attempt_page(page, plat: str, config: dict = None, *, tier=None,
                 logger=None, user_data_dir="user_data", profile="",
                 rng: random.Random = None) -> bool:
    """浏览器侧一次尝试。返回 True=滑块消失（大概率过了）。

    **前置条件**：``should_attempt`` 放行，且分级为 simple。这里再判一次分级，
    防止调用方拿错 tier 把强人机也送进来。
    """
    sec = _cfg(config)
    try:
        html = page.content()[:20000]
        body = ""
        try:
            body = page.inner_text("body")[:2000]
        except Exception:
            pass
        t = tier or classify(html, body)
        if not t.solvable:
            if logger:
                logger.info("[%s] 滑块非 simple（%s），不尝试自动解", plat,
                            t.name)
            return False
        btn = _first_box(page, _BTN_SELECTORS)
        if btn is None:
            if logger:
                logger.info("[%s] 找不到滑块按钮控件，放弃自动解", plat)
            return False
        track = _first_box(page, _TRACK_SELECTORS) or btn
        shot = _shot(page)
        bx = int(btn["x"] + btn["width"] / 2)
        by = int(btn["y"] + btn["height"] / 2)
        tb = None
        if track and track.get("width", 0) > 40:
            tb = (int(track["x"]), int(track["y"]),
                  int(track["x"] + track["width"]),
                  int(track["y"] + track["height"]))
        best, cands = find_gap(shot, tb)
        if not cands:
            if logger:
                logger.info("[%s] 图像里找不到缺口，放弃自动解", plat)
            return False
        r = rng or random.Random()
        # 顺着候选逐个试（精度不足时靠容差）
        tries = [best] if sec.get("single_shot") else [c[0] for c in cands]
        for offset in tries:
            distance = max(30, int(offset - (bx - (tb[0] if tb else 0))))
            try:
                page.mouse.move(bx, by)
                page.mouse.down()
                cx, cy = float(bx), float(by)
                for dx, dy, delay in trajectory(distance, rng=r):
                    cx += dx
                    cy += dy
                    page.mouse.move(cx, cy)
                    if delay:
                        time.sleep(delay)
                page.mouse.up()
            except Exception as e:
                if logger:
                    logger.info("[%s] 滑块拖动异常：%s", plat, e)
                continue
            time.sleep(0.8)
            # 验证看**控件是否消失**，不用 classify 复判（残留 CSS 类名会误判）
            if _slider_gone(page):
                note_result(plat, True, config, user_data_dir=user_data_dir,
                            profile=profile, kind="slider")
                if logger:
                    logger.info("[%s] 简单滑块已通过（偏移 %dpx）", plat, offset)
                return True
        note_result(plat, False, config, user_data_dir=user_data_dir,
                    profile=profile, kind="slider")
        if logger:
            logger.warning("[%s] 简单滑块尝试未通过，交给人工", plat)
        return False
    except Exception as e:
        if logger:
            logger.info("[%s] 滑块尝试失败（异常）：%s", plat, e)
        return False


def _safe_html(page) -> str:
    try:
        return page.content()[:20000]
    except Exception:
        return ""


def _safe_text(page) -> str:
    try:
        return page.inner_text("body")[:2000]
    except Exception:
        return ""


def attempt_device(dev, plat: str, config: dict = None, *, tier=None,
                   logger=None, user_data_dir="user_data", profile="",
                   rng: random.Random = None) -> bool:
    """App 侧：按 UI 树里带"拖动/滑块"文案的节点定位，再按轨迹滑动。"""
    sec = _cfg(config)
    try:
        xml = dev.dump() or ""
        t = tier or classify(xml, xml)
        if not t.solvable:
            return False
        # 找滑块手柄：文案含 拖动/滑块 的节点，取它右侧可拖动的点
        import re
        m = re.search(
            r'text="([^"]*(?:拖动|滑块|向右)[^"]*)"[^>]*bounds="\[(\d+),(\d+)\]'
            r'\[(\d+),(\d+)\]"', xml)
        if not m:
            return False
        x1, y1, x2, y2 = (int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)))
        sx, sy = x1 + max(8, (x2 - x1) // 10), (y1 + y2) // 2
        dist = int(sec.get("device_distance") or 260)
        r = rng or random.Random()
        cur = {"x": float(sx), "y": float(sy)}

        def _move(dx, dy):
            nx, ny = cur["x"] + dx, cur["y"] + dy
            # 单段滑动用 24–40ms：太快会被判脚本，太慢会被判卡住
            dev.swipe(int(cur["x"]), int(cur["y"]), int(nx), int(ny), 32)
            cur["x"], cur["y"] = nx, ny

        apply_trajectory(_move, sx, sy, dist, rng=r)
        time.sleep(0.6)
        # App 侧同理：看**界面里还有没有滑块控件/文案**，不要拿 classify 复判
        after_xml = dev.dump() or ""
        still = any(m in after_xml for m in _SIMPLE_MARKS) or \
            any(m in after_xml for m in _SIMPLE_DOM)
        if not still:
            note_result(plat, True, config, user_data_dir=user_data_dir,
                        profile=profile, kind="slider")
            if logger:
                logger.info("[%s] App 简单滑块已通过", plat)
            return True
        note_result(plat, False, config, user_data_dir=user_data_dir,
                    profile=profile, kind="slider")
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 接进挑战处置接缝（**必须显式注册才生效**）
# ---------------------------------------------------------------------------
class SliderHandler:
    """``crawlers.challenge.ChallengeHandler`` 的现成实现。

    用法（显式注册，默认不挂）::

        from crawlers.challenge import register_handler
        from crawlers.slider import SliderHandler
        register_handler(SliderHandler(cfg, user_data_dir="user_data"))

    行为：
      * 识别为 ``strong``/``unknown`` → 直接 ``handled=False``，**什么都不做**
        （与仓库「识别→记账→停手→人来过」的默认处置一致）；
      * ``simple`` 且预算允许 → 尝试一次；成功后 ``handled=True`` 让采集器
        继续解析，失败则如实 ``False``（由调用方记 blocked）。
    """

    name = "slider-handler"

    def __init__(self, config: dict = None, *, user_data_dir="user_data",
                 profile: str = "", logger=None):
        self.config = config if isinstance(config, dict) else {}
        self.user_data_dir = user_data_dir
        self.profile = profile
        self.logger = logger

    # --- 浏览器 ---
    def on_navigation(self, page, ctx):
        from .challenge import ChallengeOutcome
        plat = str(getattr(ctx, "plat", "") or "")
        body = str(getattr(ctx, "body", "") or "")
        try:
            html = page.content()[:20000]
        except Exception:
            html = ""
        tier = classify(html, body)
        if not tier.solvable:
            return ChallengeOutcome(handled=False, detail=tier.name)
        ok, why = should_attempt(plat, self.config,
                                 user_data_dir=self.user_data_dir,
                                 profile=self.profile)
        if not ok:
            return ChallengeOutcome(handled=False, detail=why)
        solved = attempt_page(page, plat, self.config, tier=tier,
                             logger=self.logger,
                             user_data_dir=self.user_data_dir,
                             profile=self.profile)
        if solved:
            try:
                page.reload()
            except Exception:
                pass
        return ChallengeOutcome(handled=bool(solved),
                                detail="slider-solved" if solved else "slider-failed")

    # --- App ---
    def on_device(self, dev, ctx):
        from .challenge import ChallengeOutcome
        plat = str(getattr(ctx, "plat", "") or "")
        tier = classify(str(getattr(ctx, "body", "") or ""), "")
        if not tier.solvable:
            return ChallengeOutcome(handled=False, detail=tier.name)
        ok, why = should_attempt(plat, self.config,
                                 user_data_dir=self.user_data_dir,
                                 profile=self.profile)
        if not ok:
            return ChallengeOutcome(handled=False, detail=why)
        solved = attempt_device(dev, plat, self.config, tier=tier,
                                logger=self.logger,
                                user_data_dir=self.user_data_dir,
                                profile=self.profile)
        return ChallengeOutcome(handled=bool(solved),
                                detail="slider-solved" if solved else "slider-failed")
