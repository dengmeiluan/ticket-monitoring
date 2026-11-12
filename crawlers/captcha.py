# -*- coding: utf-8 -*-
"""简易通用验证码的**识别与尝试**：算数、文字（OCR）、滑块。

边界先写在最前面（这条不能含糊）
--------------------------------
**图像型题目默认自动做，行为型题目由开关决定**（r1063 T21 起）：

============================  ============================================
类别                           为什么能做 / 为什么不做
============================  ============================================
简易算数 ``3 + 7 = ?``          题面是**结构化文本**，答案唯一、可验算 → 做
简易文字 ``请输入图中字符``      单行印刷体 + 无扭曲/无轨迹采集 → 用 OCR 做
几何滑块 ``拖动滑块完成拼图``    判定落在几何上 → 做（见 ``slider.py``）
强人机（极验 v4/天御/baxia/     判定输入是**你的行为分布本身**（加速度、抖动
reCAPTCHA/点选/人脸）           频谱、停顿分布）→ **不纳入自动尝试**：通用开源方案拿不到稳定通过，
                                通用开源方案无法稳定通过；是否尝试由
                                `crawler.captcha.behavior` 开关决定（默认关）
============================  ============================================

依赖策略
--------
**系统 OCR 是零依赖底座；开源识别库是可选增强。**

* 本机已有 OpenCV + numpy + PIL，加上项目自带 ``core.android.ocr``
  （Windows.Media.Ocr）——「cv2 预处理 + 系统 OCR」是验证码识别里最经典
  且零成本的一档：原图直接喂 OCR 常常读不出（字号小、有噪点、有干扰线），
  先灰度化 → 放大 2–3 倍 → Otsu 二值化 → 中值滤波去噪，命中率明显不同
  （实测 48px 字体一次读全 ``3 + 7 = ?``）。
* **`ddddocr` 已接入**（装在 `_vendor/`，不进 requirements）：它对字符型
  验证码通常明显强于系统 OCR。``read_text`` 会两个后端各读一次、取更长
  的那个；没装时自动退回系统 OCR，功能不中断。
  ``backend_name()`` 可查当前实际走哪个后端。
* 模型类后端（easyocr / paddleocr）继续复用同一个接缝：装进 `_vendor/`
  就会被选中，不需要改这里。

边界：上面这些库全部只对**本地图片**做字符识别，不把会话或账号交给任何
外部服务。外部打码平台默认**不接**（会把验证码图与上下文交给第三方，是隐私/会话边界问题，
与本地识别是两件事）；需要时可以按同一接缝自行接入，本项目不做限制。

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
# 点选题标记（只用来判型；真要做点选需要图文对齐，成本远高于本模块）
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
        """这道题**当前环境**能不能自动做。

        r1063 T21：点选题也算可解——但只在**图像检测后端可用**时才算：
        没有检测模型就无从知道点哪儿，此时如实返回 False（降级为识别→记账
        →停手），而不是"假装可解"然后在页面上瞎点（瞎点会把风控分自己拉高）。
        """
        if self.name in ("arithmetic", "text", "slider"):
            return True
        if self.name == "click":
            _det = _det_backend() is not None
            if not _det:
                # 记账（r1063 T60）：点选题"降级为停手"必须看得见，
                # 否则用户以为系统没能力解点选，而不是"缺一个后端"。
                try:
                    from core import degraded as _dg
                    _dg.note("captcha_det", "",
                             "点选题无图像检测后端（ddddocr 未装），降级为停手")
                except Exception:
                    pass
            return _det
        return False

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

# 允许把可选依赖装到项目内的 `_vendor/`（`pip install --target`），
# 不需要管理员、也不污染系统 site-packages。装在这里时自动加进 sys.path。
_VENDOR_DIRS = ("_vendor",)


def _ensure_vendor_path() -> None:
    """把项目内 ``_vendor/`` 加进 ``sys.path``（存在才加，幂等）。"""
    try:
        import os
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in _VENDOR_DIRS:
            p = os.path.join(root, name)
            if os.path.isdir(p) and p not in sys.path:
                sys.path.append(p)
    except Exception:
        pass


def _ddddocr():
    """惰性初始化 ddddocr；不可用返回 None。**失败只探一次**。"""
    if _DDDDOCR_TRIED[0]:
        return _DDDDOCR.get("cls")
    _DDDDOCR_TRIED[0] = True
    _ensure_vendor_path()
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


def _det_backend():
    """图像**目标检测**后端（r1063 T21）：ddddocr 的 ``det=True`` 实例。

    点选题（"按顺序点击图中的字/图标"）本质是检测题：它要的是**每类目标的
    坐标**，不是整图分类。ddddocr 自带检测模型，装了就能用；没装返回 ``None``，
    调用方据此**降级**（不试，而不是瞎点——瞎点等于把风控分自己打上去）。
    """
    if _DDDDOCR_TRIED[0]:
        return _DDDDOCR.get("det")
    _ensure_vendor_path()
    try:
        import ddddocr  # type: ignore
        if _DDDDOCR.get("cls") is None:
            _DDDDOCR["cls"] = ddddocr.DdddOcr(show_ad=False)
        _DDDDOCR["det"] = ddddocr.DdddOcr(show_ad=False, det=True,
                                          ocr=False)
    except Exception:
        _DDDDOCR["det"] = None
    if not _DDDDOCR_TRIED[0]:
        _DDDDOCR_TRIED[0] = True
    return _DDDDOCR.get("det")


def detect_targets(png: bytes, expect: int = 0) -> list:
    """在题目图里找可点目标，返回按**从左到右**排序的中心点 ``[(x, y), ...]``。

    "按顺序点击"类题面的语序几乎都是从左到右（中文/英文皆然），所以排序就是
    最省事的先验；`expect` 给了目标个数时只取前 N 个（宁少不多，多点的那个
    往往直接判错）。
    没有检测后端 / 解不出 → 返回 ``[]``（调用方据此**不尝试**）。
    """
    det = _det_backend()
    if det is None:
        return []
    try:
        res = det.detection(png)
    except Exception:
        return []
    pts = []
    for box in (res or []):
        try:
            x1, y1, x2, y2 = (float(v) for v in box[:4])
        except (TypeError, ValueError):
            continue
        pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    pts.sort(key=lambda p: (round(p[0] / 8.0), p[1]))   # 先按列、再按行
    if expect and expect > 0:
        pts = pts[:int(expect)]
    return pts


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

    # 点选题先判（r1063 T21）：它是**图像定位题**，不是行为题——装得起检测后端
    # 就自动试；装不起就如实说"缺后端"。
    click = [m for m in _CLICK_HINT if m.lower() in blob]
    if click:
        if _det_backend() is not None:
            return Kind("click", 0.85,
                        ["点选题：%s（图像定位，检测后端可用）" % click[0]])
        return Kind("click", 0.85,
                    ["点选题：%s（缺检测后端：装 ddddocr 即可自动尝试）"
                     % click[0]])

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

# **OCR 把运算符认成别的字形**时的纠正表（只在正常解析失败后才用）。
# 来源不是想象，是 2026-11-04 的实测：`ddddocr` 没装、后端退到
# `windows-ocr`，拿一张写着 `3+7=?` 的图喂进去，回来的是 **`3爷7=`**
# —— `+` 被认成了"爷"。这条不修，App 侧"算式在图里"的兜底就是空气。
#
# 只在**第一次解析失败**时才启用，因此正常输入完全不受影响；
# 认不出来的字符一律不猜（宁可放弃，也不要把错答案喂进验证框——
# 答错验证码比不答更容易触发风控）。
_OCR_OP_CONFUSE = {
    "+": ("爷", "丁", "干", "艹", "卄", "†", "＋", "✚", "t", "T"),
    "-": ("一", "–", "—", "－", "ー", "一"),
    "*": ("✕", "ⅹ", "乘", "㑂"),
    "/": ("∕", "／", "÷", "丿"),
}


def _ocr_fix_ops(text: str) -> str:
    """把明显是运算符误认的字形换成 ASCII 运算符（只换**数字之间**的单个字符）。

    刻意做得很窄：
    * 只处理 `数字 + 1~2 个非数字字符 + 数字` 的夹缝位置，
      绝不全局 replace —— 否则"3爷7"里的"爷"可能出现在题面文字里；
    * 一次只认**一个**运算符位；出现两个以上可疑位就放弃（不猜）；
    * 换完仍解析不出，就交回原样由调用方判失败。
    """
    t = str(text or "")
    if not t:
        return t
    rev = {}
    for op, glyphs in _OCR_OP_CONFUSE.items():
        for g in glyphs:
            rev[g] = op
    out = []
    i = 0
    replaced = 0
    n = len(t)
    while i < n:
        ch = t[i]
        # 夹在两个数字之间（允许 1~2 个字符宽）的可疑字形才换
        if ch in rev:
            prev_digit = bool(out) and out[-1].isdigit()
            # 往后找下一个非空字符是不是数字
            j = i + 1
            while j < n and t[j] in " \u3000":
                j += 1
            next_digit = j < n and t[j].isdigit()
            if prev_digit and next_digit:
                out.append(rev[ch])
                replaced += 1
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out) if replaced else t


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
        # **正常解析失败时**才试运算符纠正（OCR 把 `+` 认成"爷"这类）。
        # 顺序很重要：先按原样解，能解就绝不动输入 —— 反过来的话，
        # 字形替换会污染本来正确的题面，等于用一个猜测去修另一个猜测。
        fixed = _ocr_fix_ops(s)
        if fixed != s:
            m = re.search(r"(?<![\d.])(%s)(%s)(%s)(?![\d.])" % (_NUM, _OP, _NUM),
                          fixed)
            if m:
                s = fixed
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


def _pval(pid: str, plat: str, default=None):
    """读策略参数（r1063 T42）：**参数层有意见才采用**，否则用调用方的值。

    优先级：渠道/维度/全局覆盖（`source != "default"`）> 调用方给的 cfg >
    契约默认（由 `default` 兜底）。

    为什么不能"只要 provider 能算就用"：离线单测与部分调用点传的是裸 cfg 且
    没有 `set_config`，那时 provider 只会吐出**契约默认值**，把调用方的开关顶掉
    ——配置看着"没生效"，其实是读点优先级错了。
    """
    try:
        from core import strategy_params as _sp
        got = _sp.resolve(pid, plat=str(plat or ""))
        if str(getattr(got, "source", "") or "default") != "default":
            return got.value
    except Exception:
        pass
    return default

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


def _png_size(png: bytes) -> tuple:
    """从 PNG 头里读 (宽, 高)，读不到返回 (0, 0)。

    为什么不用 PIL：截图换算只需要宽高，PNG 头部第 16–24 字节就是；
    为一个除法引入 PIL 依赖不值得（而且 PIL 在部分打包里被裁掉过）。
    """
    try:
        if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        import struct
        w, h = struct.unpack(">II", png[16:24])
        return int(w), int(h)
    except Exception:
        return 0, 0


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

    # 族开关（r1063 T56）：pacing 会先问一次，但直接调用 attempt() 的地方也要认，
    # 否则「关了还在解」只在部分路径上成立。
    try:
        from core.strategy_params import switch_on as _sw
        if not _sw("captcha_solve.enabled", plat=str(plat or "")):
            # 契约是**返回 dict**（调用方读 rep["ok"]），早退也必须守形状
            return {"ok": False, "kind": str(kind or ""),
                    "detail": "验证码识别已关闭（策略族开关）"}
    except Exception:
        pass
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
    if k.name == "arithmetic" and not _on(
            _pval("captcha_solve.arithmetic", str(plat or ""),
                  sec.get("arithmetic")), True):
        rep["detail"] = "算数题开关已关（captcha.arithmetic=false）"
        return rep
    if k.name == "text" and not _on(
            _pval("captcha_solve.text", str(plat or ""),
                  sec.get("text")), True):
        rep["detail"] = "文字题开关已关（captcha.text=false）"
        return rep

    # 「点选 / 滑块」都不需要答案输入框：先处理这两类，再去找输入框。
    # 顺序错了就等于能力不可达（点选题没有 input，old code 会在这里 return）。
    if k.name == "click":
        # ── 点选题（r1063 T21）：检测 → 按语序（左→右）依次点击 ──────────
        # 不猜、不瞎点：检测不出目标就直接记一次失败并交回上层，
        # 因为"多点一个"在多数实现里立刻判错，反而把风控分拉高。
        if not _on(_pval("captcha_solve.click", str(plat or ""),
                      _cfg(config).get("click")), True):
            rep["detail"] = "点选题开关已关（captcha.click=false）"
            return rep
        shot = b""
        try:
            shot = page.screenshot(full_page=False) or b""
        except Exception as _se:
            # 记账（r1063 T61）：没有截图就没有识别输入——这不是"没检测到目标"，
            # 而是"根本没拿到图"，两者的处理完全不同（后者该去查页面/设备）。
            try:
                from core import degraded as _dg
                _dg.note("captcha_shot", str(plat or ""),
                         "点选题截图失败：%s" % str(_se)[:80])
            except Exception:
                pass
        pts = detect_targets(shot)
        if not pts:
            rep["detail"] = "点选题：检测不到可点目标（不尝试）"
            slider_mod.note_result(plat, False, config,
                                   user_data_dir=user_data_dir,
                                   profile=profile, kind=k.name)
            return rep
        # 截图是**设备像素**、鼠标坐标是 **CSS 像素**：按宽度比换算
        sw, _sh = _png_size(shot)
        vw = 0
        try:
            vw = int((page.viewport_size or {}).get("width") or 0)
        except Exception:
            vw = 0
        scale = (float(sw) / float(vw)) if (sw and vw) else 1.0
        rnd = rng or random.Random()
        clicked = 0
        for (cx, cy) in pts[:6]:
            try:
                page.mouse.click(cx / scale, cy / scale)
            except Exception:
                break
            clicked += 1
            time.sleep(rnd.uniform(0.14, 0.34))     # 人手不会同时落点
        time.sleep(0.9)
        ok = clicked > 0 and not _still_there(page, k.name)
        slider_mod.note_result(plat, ok, config,
                               user_data_dir=user_data_dir, profile=profile,
                               kind=k.name)
        rep["ok"] = ok
        rep["detail"] = ("点选题：点了 %d 个目标，%s"
                         % (clicked, "已通过" if ok else "未通过"))
        return rep

    elif k.name == "slider":
        solved = slider_mod.attempt_page(
            page, plat, config, tier=slider_mod.classify(html, body),
            logger=logger, user_data_dir=user_data_dir, profile=profile,
            rng=rng)
        rep["ok"] = bool(solved)
        rep["detail"] = "滑块%s" % ("通过" if solved else "失败")
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
                        scale=float(_pval("captcha_solve.ocr_scale", str(plat or ""),
                         _cfg(config).get("ocr_scale")) or 3.0))
        answer = clean_answer(raw)
        rep["detail"] = "OCR=%r → %r" % (raw[:20], answer)

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


def dump_texts(xml) -> str:
    """把 uiautomator dump 里各节点的 `text` / `content-desc` 拼成纯文本。

    为什么必须有这个（2026-11-04 实测）：`solve_arithmetic` 为了躲 OCR 把
    `?` 认成 `0` 的坑，会**在第一个 `=` 处截断**。而 dump 里每个属性都是
    `name="value"`，全文第一处 `=` 在 `<?xml version="1.0"` —— 于是整段被截成
    一行声明，算式永远抠不出来：

        solve_arithmetic(整段 dump) = None      ← App 侧算数题因此从没解出来过
        solve_arithmetic(纯题面)   = 10

    取纯文本再喂给它，截断规则才回到它设计时的语境。
    """
    parts = []
    for a in _nodes(xml):
        for key in ("text", "content-desc"):
            v = str(a.get(key) or "").strip()
            if v:
                parts.append(v)
    return " ".join(parts)


def _answer_arithmetic(text: str) -> str:
    """从"题面"里算出答案。既吃纯文本，也吃整段 uiautomator dump。

    顺序不能反：纯文本先试（PC/H5 走的路，语义最干净），
    失败再从 dump 的 text/content-desc 里拼——**直接把 dump 原文喂给
    `solve_arithmetic` 一定返回 None**（见 `dump_texts` 的实测说明）。
    """
    v = solve_arithmetic(text)
    if v is None:
        v = solve_arithmetic(dump_texts(text))
    return "" if v is None else str(v)


# ---------------------------------------------------------------------------
# 统一处理器（挂到 crawlers.challenge 的接缝上）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# App 侧：从 uiautomator dump 里选「答案输入框」和「提交按钮」
# ---------------------------------------------------------------------------
# dump 的属性名带连字符（`resource-id`），所以属性正则**必须允许 `-`**；
# 只写 [\w:]+ 会把 `resource-id="x"` 解析成 key=`id` —— 静默丢字段，
# 然后选择器"看起来找不到输入框"，而实际是解析器瞎了。
_NODE = re.compile(r"<node\b([^>]*?)/?>", re.S)
_ATTR = re.compile(r'([A-Za-z0-9_:.$-]+)="([^"]*)"')
_BOX = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# resource-id 里的这些词强指向"这是要填的框"
_EDIT_HINT = ("edit", "input", "code", "captcha", "verif", "answer", "text")
# 提交按钮文案（找到才点，找不到不瞎点：很多题输入完自动提交）
_SUBMIT_TEXTS = ("提交", "确定", "确认", "验证", "立即验证", "完成", "登录")


def _nodes(xml):
    """把 dump 里的 node 解析成 dict 列表，附带中心点（坐标全在这里算）。"""
    out = []
    for m in _NODE.finditer(str(xml or "")):
        a = dict(_ATTR.findall(m.group(1)))
        b = _BOX.search(a.get("bounds") or "")
        if not b:
            continue
        x1, y1, x2, y2 = (int(x) for x in b.groups())
        if x2 <= x1 or y2 <= y1:      # 零尺寸节点不可点
            continue
        a["_cx"] = (x1 + x2) // 2
        a["_cy"] = (y1 + y2) // 2
        out.append(a)
    return out


def find_input_box(xml):
    r"""返回答案框中心坐标 (x, y)，找不到返回 None。

    **旧写法是致命错误**（2026-11-04 复查）：

        re.search(r'text="([^"]*)"[^>]*bounds="\[..\]"', xml)

    uiautomator 的 dump 里**每个 node 都有 text 属性**（答案框通常是
    `text=""`，有字的往往是题面 `TextView`）。所以这条命中的是
    **第一个带 text 的节点** —— 实测是全屏根容器（等于点在屏幕正中），
    换一种排版就是题面。两者都不是答案框：`input_text` 没有落点，
    答案写进空气里，行为表现为"解了但没解"，
    而流程还会因为"点了、输了"继续往下走，并记下一次"试过"。

    所以按**语义**选，而不是按"有没有 text"选：
      * `class` 含 `EditText` → 决定性证据（+100）；
      * `resource-id` 含 edit/input/code/captcha/verify/answer → 强提示（+30）；
      * `focusable` / `clickable` → 弱提示（+10 / +5）。
    得分全 0 就返回 None（**不许退回去点第一个带 text 的节点**：
    宁可报"找不到输入框"让人来看，也不要制造一次假尝试）。
    """
    best, score_best = None, 0
    for a in _nodes(xml):
        cls = str(a.get("class") or "")
        rid = str(a.get("resource-id") or "").lower()
        sc = 0
        if "EditText" in cls:
            sc += 100
        if any(h in rid for h in _EDIT_HINT):
            sc += 30
        if str(a.get("focusable")) == "true":
            sc += 10
        if str(a.get("clickable")) == "true":
            sc += 5
        if sc > score_best:
            best, score_best = a, sc
    if best is None or score_best <= 0:
        return None
    return best["_cx"], best["_cy"]


def find_submit_button(xml):
    """返回提交按钮中心，找不到返回 None（不硬点，很多题自动提交）。"""
    for a in _nodes(xml):
        t = str(a.get("text") or "").strip()
        if not t:
            continue
        if not any(x == t or x in t for x in _SUBMIT_TEXTS):
            continue
        cls = str(a.get("class") or "")
        if "Button" in cls or str(a.get("clickable")) == "true":
            return a["_cx"], a["_cy"]
    return None


class SolverHandler:
    """把 slider / arithmetic / text 三类简易题统一处理；强人机不投入（见模块头）。

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
        # 第一个参数保留**原始 dump**：滑块的判定看的是 class/resource-id
        # （`slide-verify`、`nc_1_n1` 这些在属性里，不在 text 里）；
        # 第二个参数给纯文本，让算式/文字关键词按人读到的内容来判。
        k = classify_kind(xml, dump_texts(xml) or xml)
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
            if not answer:
                # 算数题面很多时候是**一张图**（"图里 3+7 等于几"），
                # dump 的 text 里根本没有算式。这时先 OCR 再算。
                # **不许先过 `clean_answer`**：那是给文字验证码清洗字符用的，
                # 会把 `+`/`×` 一并清掉 —— "4+5" 变 "45"，OCR 兜底就白加了
                # （实测踩过：兜底写完了却仍然报"空答案"）。
                shot = dev.screencap() or b""
                if shot:
                    answer = _answer_arithmetic(read_text(shot))
        else:
            shot = dev.screencap() or b""
            answer = clean_answer(read_text(shot))
        if not answer:
            slider_mod.note_result(plat, False, self.config,
                                   user_data_dir=self.user_data_dir,
                                   profile=self.profile, kind=k.name)
            return ChallengeOutcome(handled=False, detail="空答案")
        # 输入框按**语义**选（见 find_input_box 的说明）：旧写法命中题面
        # TextView，等于把答案输进空气里，还留下一次"我们试过了"的假记录。
        box = find_input_box(xml)
        if box is None:
            slider_mod.note_result(plat, False, self.config,
                                   user_data_dir=self.user_data_dir,
                                   profile=self.profile, kind=k.name)
            return ChallengeOutcome(handled=False,
                                    detail="找不到输入框（dump 里没有可输入的节点）")
        try:
            dev.tap(*box)
            time.sleep(0.4)
            dev.input_text(str(answer))
            time.sleep(0.8)
            btn = find_submit_button(xml)
            if btn:
                dev.tap(*btn)
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
