# -*- coding: utf-8 -*-
"""r924：简易通用验证码（算数 / 文字 OCR / 滑块）的识别与求解。

目标里明确要求：「简易滑块、简易图像识别、文字识别、简易算数识别等**简易通用**
的验证，是否可以自动解码尝试；非常强大的人机识别就没必要了」。

所以本模块的边界是**按"题目是否机器可判"划**，不是按"能不能硬算"：

============================  ==========================================
类别                           本仓库的做法
============================  ==========================================
简易算数 ``3+7=?``              纯文本解析（不依赖 OCR，最可靠）
简易文字 ``AB12``               系统 OCR + cv2 预处理（原图/预处理取更长）
几何滑块                        见 slider.py（边缘成对找缺口）
强人机（极验 v4/天御/baxia/      **一律不做**，交人工
reCAPTCHA/点选/人脸）
============================  ==========================================

钉住的关键行为（都是实测踩出来的）：
  1. **等号左边优先**：OCR 把题面 ``?`` 认成 ``0``，``3+7=?`` 会读成
     ``3+7=0``；若在整串找二元式就会算错 → 必须截断到第一个 ``=`` 之前；
  2. **三元式不猜**：``1+2+3`` 返回 None（简易验证码没有三元题）；
  3. **不用 eval**：自己算四则，杜绝代码注入；
  4. **OCR 双读取更长**：预处理会抹掉细笔画（``AB12`` 只剩空），原图能读；
     小字号只有预处理能读——两者互补；
  5. **预算与滑块共用一本账**：不同类别各记一套会让"失败 2 次拉黑"互相抵消。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r924_captcha_solver.py -q
"""
import io
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from crawlers import captcha as cp  # noqa: E402

_LOG = logging.getLogger("test_r924")


# ---------------------------------------------------------------------------
# 1. 算数求解
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("3 + 7 = ?", 10),
    ("3+7=?", 10),
    ("3+7=0", 10),          # OCR 把 ? 认成 0 —— 仍要算对
    ("计算：12*4=", 48),
    ("12×4", 48),
    ("8÷2=？", 4),
    ("9-3", 6),
    ("12 + 34 =", 46),
    ("三加七", 10),
    ("五乘以六", 30),
    ("九减四", 5),
    ("8除以2", 4),
    ("10.5+0.5", 11),
])
def test_solve_arithmetic_variants(text, expect):
    assert cp.solve_arithmetic(text) == expect, text


@pytest.mark.parametrize("text", [
    "", "无算式", "请拖动滑块", "1+2+3",      # 三元不猜
    "8/0",                                  # 除零
])
def test_solve_arithmetic_rejects(text):
    assert cp.solve_arithmetic(text) is None, text


def test_solve_arithmetic_prefers_left_of_equal():
    """等号右边是 OCR 噪声（0/问号），不能参与运算。"""
    assert cp.solve_arithmetic("7=0") is None
    assert cp.solve_arithmetic("3+7=0+99") == 10


def test_solve_arithmetic_never_uses_eval():
    """注入串不该被执行（自己算四则）。"""
    assert cp.solve_arithmetic("__import__('os').system('echo x')") is None


# ---------------------------------------------------------------------------
# 2. 判型
# ---------------------------------------------------------------------------
def test_classify_arithmetic():
    k = cp.classify_kind("请输入计算结果：3 + 7 = ?")
    assert k.name == "arithmetic" and k.solvable is True


def test_classify_text_captcha():
    k = cp.classify_kind("请输入图中的验证码")
    assert k.name == "text" and k.solvable is True


def test_classify_slider_delegates():
    k = cp.classify_kind('<div class="slide-verify">拖动滑块完成拼图</div>')
    assert k.name == "slider" and k.solvable is True


@pytest.mark.parametrize("html", [
    "极验 智能验证", "geetest v4", "tcaptcha 天御", "baxia",
    "recaptcha", "hcaptcha",
])
def test_classify_strong_is_not_solvable(html):
    k = cp.classify_kind(html)
    assert k.name == "strong" and k.solvable is False


def test_classify_click_is_not_solvable():
    k = cp.classify_kind("请按顺序点击下方文字")
    assert k.name == "click" and k.solvable is False


def test_classify_unknown():
    k = cp.classify_kind("正常列表页")
    assert k.name == "unknown" and k.solvable is False


# ---------------------------------------------------------------------------
# 3. 答案清洗
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expect", [
    ("AB12", "AB12"),
    ("验证码：X7K9", "X7K9"),
    ("a b 1 2", "AB12"),
    ("x7k9", "X7K9"),
    ("  3 7 0  ", "370"),
])
def test_clean_answer(raw, expect):
    assert cp.clean_answer(raw) == expect


def test_clean_answer_digits_only():
    assert cp.clean_answer("答案： 12ab34", digits_only=True) == "1234"


# ---------------------------------------------------------------------------
# 4. 预处理与 OCR（真实图片，需要 Windows OCR）
# ---------------------------------------------------------------------------
def _png(text, size=44):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", size)
    except Exception:
        pytest.skip("没有可用字体")
    im = Image.new("RGB", (460, 120), (255, 255, 255))
    ImageDraw.Draw(im).text((16, 28), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _has_ocr() -> bool:
    try:
        from core.android import ocr
        return bool(ocr.available())
    except Exception:
        return False


def test_preprocess_is_fail_soft():
    assert cp.preprocess(b"not-a-png") == b"not-a-png"
    assert cp.preprocess(b"") == b""


def test_preprocess_returns_png():
    out = cp.preprocess(_png("AB12"))
    assert out.startswith(b"\x89PNG")


@pytest.mark.skipif(not _has_ocr(), reason="系统 OCR 不可用")
def test_read_text_reads_plain_captcha():
    raw = cp.read_text(_png("AB12"))
    assert cp.clean_answer(raw) == "AB12", raw


@pytest.mark.skipif(not _has_ocr(), reason="系统 OCR 不可用")
def test_read_text_survives_thin_strokes():
    """预处理会抹掉细笔画：双读取更长才读得出来（实测 AB12）。"""
    assert cp.clean_answer(cp.read_text(_png("X7K9"))) == "X7K9"


# ---------------------------------------------------------------------------
# 5. 预算共用 + 强人机不动手
# ---------------------------------------------------------------------------
class _Mouse:
    def __init__(self):
        self.events = []

    def move(self, *a, **k):
        self.events.append("move")

    def down(self):
        self.events.append("down")

    def up(self):
        self.events.append("up")


class _Page:
    url = "https://example.test/challenge"

    def __init__(self, html, text=""):
        self.html = html
        self.text = text
        self.mouse = _Mouse()

    def content(self):
        return self.html

    def inner_text(self, sel=None):
        return self.text

    def query_selector(self, sel):
        return None

    def screenshot(self, full_page=False):
        return b""

    def keyboard(self):
        raise AssertionError("不该走到键盘输入")


def test_attempt_refuses_strong_without_touching(tmp_path):
    page = _Page("<div>geetest 智能验证</div>", "智能验证")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "simple"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert rep["kind"] == "strong"
    assert page.mouse.events == []


def test_attempt_respects_shared_budget(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "off"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "预算" in rep["detail"]


def test_attempt_reports_missing_input(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "simple"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    # 没有输入框 → 明确报出来，而不是假装试过
    assert "输入框" in rep["detail"] or "空答案" in rep["detail"]


# ---------------------------------------------------------------------------
# 6. 配置开关必须真生效（配了不读 = 死配置，docs 契约测试会抓）
# ---------------------------------------------------------------------------
def test_arithmetic_switch_off_blocks(tmp_path):
    page = _Page("请输入计算结果：3+7=?", "计算")
    rep = cp.attempt(page, "ctrip",
                     {"slider": {"auto": "simple"},
                      "captcha": {"arithmetic": False}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "算数题开关已关" in rep["detail"]


def test_text_switch_off_blocks(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip",
                     {"slider": {"auto": "simple"},
                      "captcha": {"text": "false"}},      # 字符串假值也要认
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "文字题开关已关" in rep["detail"]


def test_ocr_scale_is_read_from_config(monkeypatch, tmp_path):
    """``captcha.ocr_scale`` 必须被读走（否则是死配置）。"""
    seen = {}

    def _fake_read(png, bbox=None, scale=3.0, crop=None):
        seen["scale"] = scale
        return "AB12"
    monkeypatch.setattr(cp, "read_text", _fake_read)

    class _P(_Page):
        def query_selector(self, sel):
            class _El:
                def is_visible(self):
                    return True

                def click(self):
                    pass

                def fill(self, v):
                    seen["filled"] = v
            return _El()
    page = _P("请输入图中的验证码", "验证码")
    cp.attempt(page, "ctrip",
               {"slider": {"auto": "simple"},
                "captcha": {"text": True, "ocr_scale": 2.0}},
               user_data_dir=str(tmp_path), logger=_LOG)
    assert seen.get("scale") == 2.0, seen


# ---------------------------------------------------------------------------
# 7. 账本：分项观测 + 总账仍是一本
# ---------------------------------------------------------------------------
def test_ledger_records_by_kind(tmp_path):
    from crawlers import slider as sl
    d = str(tmp_path)
    cfg = {"slider": {"auto": True, "max_fails": 2}}
    sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="arithmetic")
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="text")
    sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="arithmetic")
    rec = sl._load(sl._ledger_path(d, "ctrip"))["ctrip"]
    assert rec["tries"] == 3
    bk = rec["by_kind"]
    assert bk["arithmetic"]["tries"] == 2 and bk["arithmetic"]["ok"] == 2
    assert bk["text"]["tries"] == 1 and bk["text"]["fail"] == 1


def test_ledger_blacklist_still_counts_total(tmp_path):
    """拉黑按**总**失败数算：分类别不能让"失败 2 次拉黑"互相抵消。"""
    from crawlers import slider as sl
    d = str(tmp_path)
    cfg = {"slider": {"auto": True, "max_fails": 2}}
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="slider")
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="text")
    rec = sl._load(sl._ledger_path(d, "ctrip"))["ctrip"]
    assert rec["fails"] == 2
    assert rec["blocked_until"] > 0            # 跨类别累计照样拉黑


def test_ledger_old_file_without_by_kind_still_works(tmp_path):
    """老账本没有 ``by_kind`` 字段，读进来不能炸。"""
    import json
    from crawlers import slider as sl
    d = str(tmp_path)
    p = sl._ledger_path(d, "ctrip")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"tries": 5, "fails": 1}}, f)
    cfg = {"slider": {"auto": True}}
    rec = sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="text")
    assert rec["tries"] == 6
    assert rec["by_kind"]["text"]["ok"] == 1
    assert rec["fails"] == 0                    # 成功清零


# ---------------------------------------------------------------------------
# 8. 可选后端 ddddocr：装了优先用，没装退回系统 OCR（都不许抛）
# ---------------------------------------------------------------------------
def test_backend_name_is_one_of_known(tmp_path):
    assert cp.backend_name() in ("ddddocr", "windows-ocr", "none")


def test_read_text_prefers_ddddocr_when_it_reads_more(monkeypatch):
    """ddddocr 读出更多字符时采用它（它对付字符验证码通常更强）。"""
    monkeypatch.setattr(cp, "_ocr_once", lambda png: "AB1")     # 系统 OCR
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "AB12")
    assert cp.read_text(b"\x89PNG fake") == "AB12"


def test_read_text_keeps_windows_result_when_ddddocr_empty(monkeypatch):
    monkeypatch.setattr(cp, "_ocr_once",
                        lambda png: "AB12" if png is not None else "")
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "")
    assert cp.read_text(b"x") == "AB12"


def test_read_text_keeps_windows_result_when_ddddocr_shorter(monkeypatch):
    calls = {"n": 0}

    def _ocr(png):
        calls["n"] += 1
        return "AB12"
    monkeypatch.setattr(cp, "_ocr_once", _ocr)
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "A")
    assert cp.read_text(b"x") == "AB12"


def test_ddddocr_absent_is_not_an_error(monkeypatch):
    """没装 ddddocr 时 ``_read_with_ddddocr`` 返回空串，不抛。"""
    cp._DDDDOCR_TRIED[0] = False
    cp._DDDDOCR.clear()
    monkeypatch.setitem(__import__("sys").modules, "ddddocr", None)
    assert cp._read_with_ddddocr(b"x") == ""


def test_slide_match_absent_returns_none(monkeypatch):
    cp._DDDDOCR_TRIED[0] = False
    cp._DDDDOCR.clear()
    monkeypatch.setitem(__import__("sys").modules, "ddddocr", None)
    assert cp.slide_match(b"x") is None
