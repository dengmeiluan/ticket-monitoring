# -*- coding: utf-8 -*-
"""简易通用验证码的**识别与尝试**：算数、文字（OCR）、滑块。

边界先写在最前面（这条不能含糊）
--------------------------------
**只做"机器可判"的题**，遇到强人机一律停手交人工：

============================  ============================================
类别                           为什么能做 / 为什么不做
============================  ============================================
简易算数 ``3 + 7 = ?``          题面是**结构化文本**，答案唯一、可验算 → 做
简易文字 ``请输入图中字符``      单行印刷体 + 无扭曲/无轨迹采集 → 用 OCR 做
几何滑块 ``拖动滑块完成拼图``    判定落在几何上 → 做（见 ``slider.py``）
强人机（极验 v4/天御/baxia/     判定输入是**你的行为分布本身**（加速度、抖动
reCAPTCHA/点选/人脸）           频谱、停顿分布）→ 越算越像机器，**一律不做**
============================  ============================================

依赖策略：**不引入新依赖**。本机已有 OpenCV 4.12 + numpy + PIL，加上项目
自带 ``core.android.ocr``（Windows.Media.Ocr）——「cv2 预处理 + 系统 OCR」
是验证码识别里最经典且零成本的一档：

* 原图直接喂 OCR 常常读不出（字号小、有噪点、有干扰线）；
* 先灰度化 → 放大 2–3 倍 → Otsu 二值化 → 中值滤波去噪，再喂 OCR，
  命中率明显不同（实测 48px 字体一次读全 ``3 + 7 = ?``）。

**不装** ``pytesseract/easyocr/ddddocr``：前者要额外装 Tesseract 二进制、
后两个要拖 onnxruntime/torch 级依赖，而它们对"无扭曲的简易题"并不比
系统 OCR + 预处理强多少。真要上模型时，接缝已经留好（``read_text``）。

公共预算
--------
和滑块共用同一本账（``slider_ledger.json``）与同一套规则：
每日上限、连续失败拉黑、失败如实记账。**不同类别不各记一套**——否则
「滑块失败 2 次拉黑」和「算数失败 2 次拉黑」会互相抵消。
"""
from __future__ import annotations

import io
import random
import re
import time

from . import slider as slider_mod

KINDS = ("arithmetic", "text", "slider", "click", "strong", "unknown")

# 强人机标记（与 slider 同源，避免两处漂移）
_STRONG = slider_mod._STRONG_MARKS

# 算数题标记
_ARITH_HINT = ("等于", "计算", "算式", "what is", "等于多少", "求和")
# 文字题标记
_TEXT_HINT = ("验证码", "图中", "字符", "看不清", "请输入以下", "输入下方",
              "captcha", "verify code", "security code")
# 点选题标记（不做，只用来判型）
_CLICK_HINT = ("点选", "按顺序点击", "依次点击", "选出")

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2,
             "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
             "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
             "九": 9, "玖": 9}
_CN_OP = {"加": "+", "减": "-", "乘以": "*", "乘": "*", "除以": "/", "除": "/",
          "×": "*", "x": "*", "X": "*", "÷": "/", "＋": "+", "－": "-",
          "＊": "*", "／": "/"}


class Kind:
    """判型结果。``name`` 只会是本模块 ``KINDS`` 里的一项。"""

    __slots__ = ("name", "confidence", "reasons")

    def __init__(self, name: str, confidence: float = 0.0, reasons=None):
        self.name = name if name in KINDS else "unknown"
        self.confidence = float(confidence)
        self.reasons = list(reasons or [])

    @property
    def solvable(self) -> bool:
        return self.name in ("arithmetic", "text", "slider")

    def as_dict(self):
        return {"name": self.name, "confidence": round(self.confidence, 2),
                "solvable": self.solvable, "reasons": list(self.reasons)}

    def __repr__(self):
        return "<Kind %s %.2f>" % (self.name, self.confidence)


# ---------------------------------------------------------------------------
# 可选后端：ddddocr（开源验证码识别，装了就用）
# ---------------------------------------------------------------------------
# 用户明确要求"Python 应该有很多现成的解码开源框架吧，可以试试"。
# ddddocr 是中文验证码识别里最常用的一个（纯 onnxruntime，不需要 torch），
# 它自带三类能力，正好对上我们的题目分类：
#
#   * ``classification``   —— 字符验证码（我们叫 text）
#   * ``slide_match``      —— 滑块缺口坐标（可替代我们的边缘检测）
#   * ``slide_comparison`` —— 两张图对比找缺口
#
# **做成可选后端**：装了就优先用、没装就自动退回"系统 OCR + cv2"。
# 这样既满足"试试现成框架"，又不给项目强加 onnxruntime 级依赖
# （那会让打包体积涨几十 MB，而多数场景用不上）。
_DDDDOCR = {}
_DDDDOCR_TRIED = [False]


def _ddddocr():
    """惰性初始化 ddddocr；不可用返回 None。**失败只探一次**。"""
    if _DDDDOCR_TRIED[0]:
        return _DDDDOCR.get("cls")
    _DDDDOCR_TRIED[0] = True
    try:
        import ddddocr  # type: ignore
        _DDDDOCR["cls"] = ddddocr.DdddOcr(show_ad=False)
        _DDDDOCR["slide"] = ddddocr.DdddOcr(show_ad=False,
                                            det=False, ocr=False)
    except Exception:
        _DDDDOCR["cls"] = None
        _DDDDOCR["slide"] = None
    return _DDDDOCR.get("cls")


def backend_name() -> str:
    """当前文字识别走哪个后端（``ddddocr`` / ``windows-ocr`` / ``none``）。"""
    if _ddddocr() is not None:
        return "ddddocr"
    try:
        from core.android import ocr
        if ocr.available():
            return "windows-ocr"
    except Exception:
        pass
    return "none"


def _read_with_ddddocr(png: bytes) -> str:
    try:
        cls = _ddddocr()
        if cls is None:
            return ""
        out = cls.classification(png)
        return str(out or "").strip()
    except Exception:
        return ""


def slide_match(png: bytes, bg_png: bytes = None):
    """用 ddddocr 的 ``slide_match`` 找缺口 x；不可用返回 ``None``。

    这是给 ``slider.find_gap`` 的可选增强：ddddocr 的滑轨模型对"缺口与背景
    同色系/有噪点"的图更稳，而我们的边缘法对"两条强边"最稳——两者互补。
    """
    try:
        import ddddocr  # type: ignore
        if not _DDDDOCR_TRIED[0]:
            _ddddocr()
        det = _DDDDOCR.get("slide")
        if det is None:
            return None
        res = det.slide_match(png, simple_target=True)
        if isinstance(res, dict) and "target" in res:
            box = res["target"]
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                return int((box[0] + box[2]) / 2)
        return None
    except Exception:
        return None
def classify_kind(html: str = "", text: str = "") -> Kind:
    """判「这是哪一类验证」。强人机优先级最高（安全侧）。"""
    blob = ("%s\n%s" % (html or "", text or "")).lower()
    if not blob.strip():
        return Kind("unknown", 0.0, ["空页面"])

    # 点选题先判：它和强人机一样**不做**，但单独报出来对操作员更有信息量
    # （"这类题要理解图像语义" vs "这类题吃行为分布"是两种不同的停手理由）。
    click = [m for m in _CLICK_HINT if m.lower() in blob]
    if click:
        return Kind("click", 0.85, ["点选题：%s（不做）" % click[0]])

    strong = [m for m in _STRONG if m.lower() in blob]
    if strong:
        return Kind("strong", 0.95, ["强人机标记：%s" % "、".join(strong[:3])])

    # 算数：先看有没有可解析的算式，这比关键词更硬
    expr = solve_arithmetic(blob)
    arith_hint = [m for m in _ARITH_HINT if m.lower() in blob]
    if expr is not None and (arith_hint or re.search(r"\d\s*[+\-*/×÷]\s*\d", blob)):
        return Kind("arithmetic", 0.9,
                    ["算式可解析：%s" % (expr,)] if not arith_hint
                    else ["算式可解析 + 关键词 %s" % arith_hint[0]])
    if arith_hint:
        return Kind("arithmetic", 0.55, ["只有算数关键词：%s" % arith_hint[0]])

    txt = [m for m in _TEXT_HINT if m.lower() in blob]
    if txt:
        return Kind("text", 0.75, ["文字验证码关键词：%s" % txt[0]])

    # 滑块交给 slider 自己的分级
    tier = slider_mod.classify(html, text)
    if tier.solvable:
        return Kind("slider", tier.confidence, list(tier.reasons))
    if tier.name == "strong":
        return Kind("strong", tier.confidence, list(tier.reasons))
    return Kind("unknown", 0.2, ["没有任何可识别标记"])


# ---------------------------------------------------------------------------
# 算数：纯文本解析（可离线验证，最可靠的一环）
# ---------------------------------------------------------------------------
def _normalize(expr: str) -> str:
    """全角转半角、中文数字/运算符转 ASCII、去掉空白与尾部问号。"""
    s = str(expr or "")
    for k, v in _CN_OP.items():
        s = s.replace(k, v)
    # 中文数字：仅处理单字 0-9（够用于"三加七"这类题面）
    for k, v in _CN_DIGIT.items():
        s = s.replace(k, str(v))
    s = s.replace("＝", "=").replace("？", "?").replace("＝", "=")
    s = re.sub(r"[\s\u3000]", "", s)
    return s


_NUM = r"\d+(?:\.\d+)?"
_OP = r"[+\-*/]"


def solve_arithmetic(text: str):
    """从任意文本里抠出**一个**二元算式并求值；抠不到返回 ``None``。

    支持：``3+7=?``、``3 + 7 = ?``、``12×4``、``8÷2``、``9-3``、
    ``三加七``、``计算：12*3=``。

    两个刻意的处理：

    * **只看 ``=`` 之前**：OCR 常把题面的 ``?`` 认成 ``0``，于是
      ``3+7=?`` 读成 ``3+7=0``；若从整串里找二元式就可能把 ``7=0`` 甚至
      ``=0`` 当算式。截断到第一个 ``=`` 之前最稳。
    * **严格求值，不用 eval**：自己算，所以不存在代码注入。

    边界：只做二元式。``1+2+3`` 会取到最后一个二元式（``2+3``=5）——
    "简易算数验证码"不存在三元题，遇到就当解析失败更安全，因此这里对
    多个运算符的串返回 ``None``。
    """
    s = _normalize(text)
    if not s:
        return None
    if "=" in s:
        s = s.split("=", 1)[0]          # 只看等号左边（避开 OCR 的 ?→0）
    m = re.search(r"(?<![\d.])(%s)(%s)(%s)(?![\d.])" % (_NUM, _OP, _NUM), s)
    if not m:
        return None
    # 三元及以上不猜：整个串里出现两个以上运算符就放弃
    if len(re.findall(_OP, s)) > 1:
        return None
    a, op, b = m.group(1), m.group(2), m.group(3)
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if op == "+":
        r = x + y
    elif op == "-":
        r = x - y
    elif op == "*":
        r = x * y
    else:
        if y == 0:
            return None
        r = x / y
    # 整数就返回 int，避免 "10.0" 这种与答案框格式不符
    return int(r) if abs(r - round(r)) < 1e-9 else round(r, 4)


# ---------------------------------------------------------------------------
# OCR：cv2 预处理 + 系统 OCR（零新依赖）
# ---------------------------------------------------------------------------
def preprocess(png: bytes, scale: float = 3.0) -> bytes:
    """灰度 → 放大 → **轻度**二值化。失败/无改善时原样返回。

    为什么"轻"：验证码的字往往细且小，重手二值化 + 中值滤波会把笔画抹掉
    （实测 44px 的 ``AB12`` 被 Otsu + medianBlur(3) 处理后 OCR 直接读空）。
    所以这里只做两件低损伤的事：放大（INTER_CUBIC，保住笔画过渡）+
    Otsu 二值化（不做滤波）。调用方应**同时试原图与预处理图**，取更长的
    识别结果（``read_text`` 就是这么做的）。
    """
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(png, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return png
        h, w = img.shape[:2]
        if scale and scale > 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if (bw == 0).mean() > 0.5:      # 黑底白字 → 反成白底黑字
            bw = cv2.bitwise_not(bw)
        ok, out = cv2.imencode(".png", bw)
        return out.tobytes() if ok else png
    except Exception:
        return png


def _ocr_once(png: bytes) -> str:
    try:
        from core.android import ocr
        words = ocr.ocr_words(png) or []
    except Exception:
        return ""
    parts = []
    for w in words:
        if isinstance(w, dict):
            t = str(w.get("t") or w.get("text") or "")
        else:
            t = str(w)
        if t:
            parts.append(t)
    return "".join(parts).strip()


def read_text(png: bytes, bbox=None, *, scale: float = 3.0,
              crop: bytes = None) -> str:
    """图 → 文本（走项目自带的 Windows OCR）。读不到返回空串。

    **关键策略：原图与预处理图各读一次，取更长的**。预处理对"细笔画"有损伤，
    原图对"小字号/低对比"读不出——两者互补。实测 ``AB12`` 只有原图读得出，
    ``3 + 7 = ?`` 预处理后才读全。

    ``bbox`` 是页面坐标 ``(x0, y0, x1, y1)``；传了就先裁剪。
    ``crop`` 允许调用方直接给已裁好的图。
    """
    raw = crop or png
    if not raw:
        return ""
    if bbox:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            x0, y0, x1, y1 = [int(v) for v in bbox]
            im = im.crop((max(0, x0), max(0, y0),
                          max(x0 + 1, x1), max(y0 + 1, y1)))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            raw = buf.getvalue()
        except Exception:
            pass
    a = _ocr_once(raw)                       # 原图
    b = _ocr_once(preprocess(raw, scale=scale))   # 预处理图
    win = a if len(a) >= len(b) else b
    # 可选后端优先：ddddocr 对"字符验证码"通常明显强于系统 OCR。
    # 只在它**读出了东西**时才采用，否则保留系统 OCR 的结果。
    d4 = _read_with_ddddocr(raw)
    if len(d4) >= len(win) and d4:
        return d4
    return win


def clean_answer(text: str, *, digits_only: bool = False) -> str:
    """把 OCR 结果清成"可填的答案"。

    OCR 常带干扰：全角符号、空格、``验证码：`` 前缀、以及把 ``0`` 认成 ``O``。
    """
    s = str(text or "")
    s = s.replace("：", ":").replace("＝", "=")
    # 去掉常见前缀
    s = re.sub(r"^(验证码|captcha|code|verify)\s*[:：]?\s*", "", s, flags=re.I)
    if digits_only:
        s = re.sub(r"[^0-9.\-]", "", s)
        return s
    s = re.sub(r"\s+", "", s)
    # 只保留字母数字（验证码字符集几乎都是这两类）
    s = re.sub(r"[^0-9A-Za-z]", "", s)
    # 字母里常把 O/0、l/1 认错：这里只做"全大写"统一，不猜替换
    return s.upper()


# ---------------------------------------------------------------------------
# 尝试（浏览器 / 设备）
# ---------------------------------------------------------------------------
def _cfg(config: dict) -> dict:
    """读 ``crawler.captcha`` 段（缺省跟随 slider 的开关）。"""
    if not isinstance(config, dict):
        return {}
    sec = config.get("captcha")
    if isinstance(sec, dict):
        return sec
    return config.get("slider") if isinstance(config.get("slider"), dict) else {}


def _on(v, default=False) -> bool:
    """布尔开关解析：容忍字符串假值（``"false"`` 在 YAML 里是字符串）。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(v)


_INPUT_SELECTORS = (
    "input[name*=code]", "input[id*=code]", "input[name*=captcha]",
    "input[id*=captcha]", "input[placeholder*=验证]", "input[type=text]",
    "input:not([type])",
)
_SUBMIT_SELECTORS = (
    "button[type=submit]", "input[type=submit]",
    "[class*=submit]", "[class*=confirm]", "[class*=verify-btn]",
)


def _first(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el is not None and el.is_visible():
                return el
        except Exception:
            continue
    return None


def _img_bbox(page, selectors=None) -> tuple:
    """找验证码图片区域（给 OCR 裁剪用）。"""
    sels = selectors or ("img[src*=captcha]", "img[src*=code]",
                         "[class*=captcha] img", "[class*=verify] img",
                         "canvas[class*=captcha]")
    for sel in sels:
        try:
            el = page.query_selector(sel)
            if el is None:
                continue
            box = el.bounding_box()
            if box and box.get("width", 0) > 20 and box.get("height", 0) > 12:
                return (int(box["x"]), int(box["y"]),
                        int(box["x"] + box["width"]),
                        int(box["y"] + box["height"]))
        except Exception:
            continue
    return ()


def _still_there(page, kind: str) -> bool:
    """挑战还在不在：按"题面是否仍可判型"看，比看元素更稳。"""
    try:
        html = page.content()[:20000]
        body = page.inner_text("body")[:2000]
    except Exception:
        return True
    k = classify_kind(html, body)
    return k.solvable


def attempt(page, plat: str, config: dict = None, *, kind=None,
            logger=None, user_data_dir="user_data", profile="",
            rng: random.Random = None) -> dict:
    """尝试一次。返回 ``{"ok": bool, "kind": str, "detail": str}``。

    预算与拉黑**共用滑块那本账**（``should_attempt`` / ``note_result``）：
    不同类别各记一套会让"失败 2 次拉黑"互相抵消。
    """
    rep = {"ok": False, "kind": "", "detail": ""}
    ok_allow, why = slider_mod.should_attempt(
        plat, config, user_data_dir=user_data_dir, profile=profile)
    if not ok_allow:
        rep["detail"] = "预算不放行：%s" % why
        return rep
    try:
        html = page.content()[:20000]
        body = page.inner_text("body")[:2000]
    except Exception:
        html, body = "", ""
    k = kind if isinstance(kind, Kind) else classify_kind(html, body)
    rep["kind"] = k.name
    if not k.solvable:
        rep["detail"] = "不可解（%s）：%s" % (k.name, "、".join(k.reasons)[:80])
        return rep
    # 类别开关：配了就该生效（`captcha.arithmetic` / `captcha.text`）
    sec = _cfg(config)
    if k.name == "arithmetic" and not _on(sec.get("arithmetic"), True):
        rep["detail"] = "算数题开关已关（captcha.arithmetic=false）"
        return rep
    if k.name == "text" and not _on(sec.get("text"), True):
        rep["detail"] = "文字题开关已关（captcha.text=false）"
        return rep

    box = _first(page, _INPUT_SELECTORS)
    if box is None:
        rep["detail"] = "找不到答案输入框"
        return rep

    answer = ""
    if k.name == "arithmetic":
        answer = _answer_arithmetic(html + "\n" + body)
        rep["detail"] = "算式答案 %s" % answer
    elif k.name == "text":
        shot = b""
        try:
            shot = page.screenshot(full_page=False) or b""
        except Exception:
            pass
        bbox = _img_bbox(page)
        raw = read_text(shot, bbox or None,
                        scale=float(_cfg(config).get("ocr_scale") or 3.0))
        answer = clean_answer(raw)
        rep["detail"] = "OCR=%r → %r" % (raw[:20], answer)
    elif k.name == "slider":
        solved = slider_mod.attempt_page(
            page, plat, config, tier=slider_mod.classify(html, body),
            logger=logger, user_data_dir=user_data_dir, profile=profile,
            rng=rng)
        rep["ok"] = bool(solved)
        rep["detail"] = "滑块%s" % ("通过" if solved else "失败")
        return rep

    if not answer:
        slider_mod.note_result(plat, False, config,
                               user_data_dir=user_data_dir, profile=profile,
                               kind=k.name)
        rep["detail"] += "（空答案，记失败）"
        return rep

    try:
        box.click()
        box.fill(str(answer))
        btn = _first(page, _SUBMIT_SELECTORS)
        if btn is not None:
            btn.click()
        else:
            page.keyboard.press("Enter")
        time.sleep(1.2)
    except Exception as e:
        rep["detail"] += "，填写异常：%s" % str(e)[:60]
        slider_mod.note_result(plat, False, config,
                               user_data_dir=user_data_dir, profile=profile,
                               kind=k.name)
        return rep

    ok = not _still_there(page, k.name)
    slider_mod.note_result(plat, ok, config,
                           user_data_dir=user_data_dir, profile=profile,
                           kind=k.name)
    rep["ok"] = ok
    rep["detail"] += "，%s" % ("已通过" if ok else "未通过")
    if logger:
        logger.info("[%s] %s验证：%s", plat, k.name, rep["detail"])
    return rep


def _answer_arithmetic(text: str) -> str:
    v = solve_arithmetic(text)
    return "" if v is None else str(v)


# ---------------------------------------------------------------------------
# 统一处理器（挂到 crawlers.challenge 的接缝上）
# ---------------------------------------------------------------------------
class SolverHandler:
    """把 slider / arithmetic / text 三类简易题统一处理；强人机不碰。

    与 ``slider.SliderHandler`` 的关系：本类是它的超集，``challenge``
    的引导函数会优先挂本类；``SliderHandler`` 保留以兼容既有调用。
    """

    name = "solver-handler"

    def __init__(self, config: dict = None, *, user_data_dir="user_data",
                 profile: str = "", logger=None):
        self.config = config if isinstance(config, dict) else {}
        self.user_data_dir = user_data_dir
        self.profile = profile
        self.logger = logger

    def on_navigation(self, page, ctx):
        from .challenge import ChallengeOutcome
        plat = str(getattr(ctx, "plat", "") or "")
        body = str(getattr(ctx, "body", "") or "")
        try:
            html = page.content()[:20000]
        except Exception:
            html = ""
        k = classify_kind(html, body)
        if not k.solvable:
            return ChallengeOutcome(handled=False, detail=k.name)
        rep = attempt(page, plat, self.config, kind=k, logger=self.logger,
                      user_data_dir=self.user_data_dir, profile=self.profile)
        if rep.get("ok"):
            try:
                page.reload()
            except Exception:
                pass
        return ChallengeOutcome(handled=bool(rep.get("ok")),
                                detail=rep.get("detail") or k.name)

    def on_device(self, dev, ctx):
        """App 侧：滑块走 slider；算数/文字用「截图 + OCR + 点击输入框」。"""
        from .challenge import ChallengeOutcome
        plat = str(getattr(ctx, "plat", "") or "")
        xml = str(getattr(ctx, "body", "") or "")
        k = classify_kind(xml, xml)
        if not k.solvable:
            return ChallengeOutcome(handled=False, detail=k.name)
        if k.name == "slider":
            solved = slider_mod.attempt_device(
                dev, plat, self.config, tier=slider_mod.classify(xml, xml),
                logger=self.logger, user_data_dir=self.user_data_dir,
                profile=self.profile)
            return ChallengeOutcome(handled=bool(solved),
                                    detail="slider-solved" if solved
                                    else "slider-failed")
        # 算数/文字：先算答案（算数不需要 OCR），再点输入框 + 输入
        answer = ""
        if k.name == "arithmetic":
            answer = _answer_arithmetic(xml)
        else:
            shot = dev.screencap() or b""
            answer = clean_answer(read_text(shot))
        if not answer:
            slider_mod.note_result(plat, False, self.config,
                                   user_data_dir=self.user_data_dir,
                                   profile=self.profile, kind=k.name)
            return ChallengeOutcome(handled=False, detail="空答案")
        m = re.search(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]'
                      r'\[(\d+),(\d+)\]"', xml)
        if not m:
            return ChallengeOutcome(handled=False, detail="找不到输入框")
        x = (int(m.group(2)) + int(m.group(4))) // 2
        y = (int(m.group(3)) + int(m.group(5))) // 2
        try:
            dev.tap(x, y)
            time.sleep(0.4)
            dev.input_text(str(answer))
            time.sleep(0.8)
            after = dev.dump() or ""
            ok = not classify_kind(after, after).solvable
        except Exception:
            ok = False
        slider_mod.note_result(plat, ok, self.config,
                               user_data_dir=self.user_data_dir,
                               profile=self.profile, kind=k.name)
        return ChallengeOutcome(handled=bool(ok),
                                detail="%s %s" % (k.name,
                                                  "ok" if ok else "fail"))
