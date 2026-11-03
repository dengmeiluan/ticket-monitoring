# -*- coding: utf-8 -*-
"""滑块分级与简单滑块自动尝试：分级、缺口检测、轨迹、预算。

钉住的口径（错了就会变成"见滑块就乱试"）：
  * ``strong`` / ``unknown`` **一律不尝试**（判错一次就是一条自动化样本）；
  * 默认关闭（``slider.auto`` 不配 = 不动手）；
  * 每次只试候选里的少数几个，连续失败 2 次拉黑 7 天、每日有上限；
  * 轨迹必须有加速—巡航—减速 + 回拉 + 落点修正，终点精确。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r914_slider_solver.py -q
"""
import io
import logging
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import slider  # noqa: E402

_LOG = logging.getLogger("test_r914")


def _png(w=320, h=140, gap_x=200, gap_w=46, seed=7) -> bytes:
    """造一张"背景有噪点 + 一个高对比缺口"的图，用于验证缺口检测。"""
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    im = Image.new("L", (w, h), 150)
    d = ImageDraw.Draw(im)
    # 背景噪点（模拟真实图片纹理，防止"靠整列亮度"取巧）
    for x in range(0, w, 3):
        for y in range(0, h, 5):
            v = 140 + rnd.randint(-18, 18)
            d.point((x, y), fill=v)
    # 缺口：深色块 + 白色描边（两条强竖直边）
    d.rectangle([gap_x, 30, gap_x + gap_w, 110], fill=60, outline=250, width=2)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 分级
# ---------------------------------------------------------------------------
def test_classify_simple_slider():
    t = slider.classify('<div class="slide-verify">拖动滑块完成拼图</div>')
    assert t.name == "simple" and t.solvable is True
    assert t.confidence >= 0.8


def test_classify_strong_human_verification():
    for html in ("<div>极验 智能验证</div>",
                 "<div>geetest v4</div>",
                 "<div>tcaptcha 天御</div>",
                 "<div>baxia</div>",
                 "<div>请按顺序点击下方文字</div>",
                 "<div>recaptcha</div>"):
        t = slider.classify(html)
        assert t.name == "strong", html
        assert t.solvable is False


def test_classify_unknown_when_no_marker():
    t = slider.classify("<div>正常页面</div>")
    assert t.name == "unknown" and t.solvable is False


def test_strong_wins_over_simple_markers():
    """同时出现两类标记时按更危险的一类处理（安全侧）。"""
    t = slider.classify('<div class="slide-verify">拖动滑块</div>'
                        "<script>geetest.init()</script>")
    assert t.name == "strong"


# ---------------------------------------------------------------------------
# 2. 缺口检测
# ---------------------------------------------------------------------------
def test_find_gap_locates_synthetic_gap():
    png = _png(gap_x=200, gap_w=46)
    off, cands = slider.find_gap(png)
    assert cands, "应当找到候选"
    # 窗口中心 ≈ gap_x + gap_w/2 = 223
    assert abs(off - 223) <= 14, (off, cands)


def test_find_gap_respects_bbox_offset():
    png = _png(w=640, h=200, gap_x=430, gap_w=50)
    off, cands = slider.find_gap(png, bbox=(200, 60, 620, 160))
    # bbox 内偏移 ≈ 430-200+25 = 255
    assert cands and abs((off + 200) - 455) <= 18, (off, cands)


def test_find_gap_is_fail_soft():
    assert slider.find_gap(b"") == (0, [])
    assert slider.find_gap(b"not-a-png") == (0, [])
    # 纯色图没有边 → 不返回候选（不许瞎给一个数）
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (300, 100), 128).save(buf, format="PNG")
    off, cands = slider.find_gap(buf.getvalue())
    assert off == 0 and cands == []


def test_missing_numpy_is_visible_in_log(monkeypatch, caplog):
    """缺依赖与「没找到缺口」返回同一个空值，必须靠日志区分（否则
    滑块能力在缺 numpy 的环境里静默空转，CI 曾因此红得没有线索）。"""
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setattr(slider, "_NP_WARNED", False)
    with caplog.at_level(logging.WARNING, logger="crawlers.slider"):
        assert slider.find_gap(_png()) == (0, [])
        assert slider.find_gap(_png()) == (0, [])
    hits = [r for r in caplog.records if "numpy" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in caplog.records]


# ---------------------------------------------------------------------------
# 3. 轨迹
# ---------------------------------------------------------------------------
def test_trajectory_lands_exactly_and_looks_human():
    r = random.Random(11)
    seq = slider.trajectory(300, rng=r)
    total = sum(dx for dx, _dy, _d in seq)
    assert total == 300, total                      # 终点精确
    assert len(seq) >= 18                           # 不是一次瞬移
    assert any(dx < 0 for dx, _dy, _d in seq)       # 有回拉
    assert all(0 <= d <= 0.5 for _x, _y, d in seq)  # 间隔合理
    assert all(abs(dy) <= 1 for _x, dy, _d in seq)


def test_trajectory_short_distance_still_works():
    seq = slider.trajectory(40, rng=random.Random(3))
    assert sum(dx for dx, _y, _d in seq) == 40


def test_apply_trajectory_calls_move_and_tolerates_errors():
    moves = []
    ticks = []
    total = slider.apply_trajectory(
        lambda dx, dy: moves.append((dx, dy)), 0, 0, 120,
        rng=random.Random(5), sleep=lambda s: ticks.append(s))
    assert len(moves) >= 10
    assert sum(dx for dx, _dy in moves) == 120
    assert total >= 0 and ticks

    def _boom(dx, dy):
        raise RuntimeError("x")
    assert slider.apply_trajectory(_boom, 0, 0, 100,
                                   rng=random.Random(1)) >= 0


# ---------------------------------------------------------------------------
# 4. 预算 / 黑名单
# ---------------------------------------------------------------------------
def test_should_attempt_is_off_by_default():
    ok, why = slider.should_attempt("ctrip", {}, user_data_dir=".")
    assert ok is False and "auto" in why


def test_daily_cap_and_two_strikes_blacklist(tmp_path):
    cfg = {"slider": {"auto": True, "daily_cap": 5}}
    d = str(tmp_path)
    assert slider.should_attempt("ctrip", cfg, user_data_dir=d)[0] is True
    slider.note_result("ctrip", False, cfg, user_data_dir=d)
    assert slider.should_attempt("ctrip", cfg, user_data_dir=d)[0] is True
    slider.note_result("ctrip", False, cfg, user_data_dir=d)   # 第 2 次失败
    ok, why = slider.should_attempt("ctrip", cfg, user_data_dir=d)
    assert ok is False and "冷却" in why
    # 成功会清零
    slider.note_result("ctrip", True, cfg, user_data_dir=d)
    assert slider.should_attempt("ctrip", cfg, user_data_dir=d)[0] is True


def test_daily_cap_blocks_after_n(tmp_path):
    cfg = {"slider": {"auto": True, "daily_cap": 2}}
    d = str(tmp_path)
    slider.note_result("qunar", True, cfg, user_data_dir=d)
    slider.note_result("qunar", True, cfg, user_data_dir=d)
    ok, why = slider.should_attempt("qunar", cfg, user_data_dir=d)
    assert ok is False and "上限" in why


# ---------------------------------------------------------------------------
# 5. 浏览器侧一次尝试（假 page）
# ---------------------------------------------------------------------------
class _El:
    def __init__(self, box):
        self._box = box

    def bounding_box(self):
        return self._box


class _Mouse:
    def __init__(self, page):
        self.page = page
        self.events = []

    def move(self, x, y):
        self.events.append(("move", int(x), int(y)))

    def down(self):
        self.events.append(("down",))

    def up(self):
        self.events.append(("up",))
        self.page.solved = True


class _Page:
    """够用的假页面：过完滑块后把 html 换成正常页。"""

    def __init__(self, html, shot: bytes):
        self.html = html
        self.shot = shot
        self.solved = False
        self.mouse = _Mouse(self)

    def content(self):
        return "<div>正常列表页</div>" if self.solved else self.html

    def inner_text(self, sel=None):
        return "" if self.solved else "拖动滑块完成拼图"

    def screenshot(self, full_page=False):
        return self.shot

    def query_selector(self, sel):
        # 成功后控件被移除（真实页面就是这样，也是 _slider_gone 的主判据）
        if self.solved:
            return None
        if "btn" in sel or "Button" in sel or "n1z" in sel or "Block" in sel:
            return _El({"x": 40, "y": 300, "width": 48, "height": 40})
        if "slide" in sel or "slider" in sel or "scale" in sel:
            return _El({"x": 20, "y": 280, "width": 280, "height": 60})
        return None


def test_attempt_page_refuses_strong_tier(tmp_path):
    page = _Page("<div>geetest 智能验证</div>", _png())
    ok = slider.attempt_page(page, "ctrip", {"slider": {"auto": True}},
                             user_data_dir=str(tmp_path), logger=_LOG)
    assert ok is False
    assert page.mouse.events == []          # 一根手指都不许动


def test_attempt_page_solves_simple_slider(tmp_path):
    page = _Page('<div class="slide-verify">拖动滑块完成拼图</div>', _png())
    ok = slider.attempt_page(page, "ctrip", {"slider": {"auto": True}},
                             user_data_dir=str(tmp_path), logger=_LOG,
                             rng=random.Random(2))
    assert ok is True
    kinds = [e[0] for e in page.mouse.events]
    assert kinds[0] == "move" and "down" in kinds and kinds[-1] == "up"
    assert len(kinds) > 10                  # 轨迹不是瞬移
    rec = slider.note_result("ctrip", True, {"slider": {"auto": True}},
                             user_data_dir=str(tmp_path))
    assert rec["fails"] == 0


def test_attempt_page_fails_soft_without_button(tmp_path):
    page = _Page('<div class="slide-verify">拖动滑块</div>', _png())
    page.query_selector = lambda sel: None          # 找不到控件
    assert slider.attempt_page(page, "ctrip",
                               {"slider": {"auto": True}},
                               user_data_dir=str(tmp_path),
                               logger=_LOG) is False


# ---------------------------------------------------------------------------
# 6. 挑战接缝处理器（必须显式注册才生效）
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self, plat="ctrip", body=""):
        self.plat = plat
        self.body = body


class _Page2(_Page):
    def __init__(self, html, shot):
        super().__init__(html, shot)
        self.reloads = 0

    def reload(self):
        self.reloads += 1
        self.solved = True


def test_handler_ignores_strong_and_unknown(tmp_path):
    h = slider.SliderHandler({"slider": {"auto": True}},
                             user_data_dir=str(tmp_path), logger=_LOG)
    page = _Page2("<div>geetest 智能验证</div>", _png())
    out = h.on_navigation(page, _Ctx(body="智能验证"))
    assert out.handled is False and page.mouse.events == []

    page2 = _Page2("<div>平常页面</div>", _png())
    assert h.on_navigation(page2, _Ctx(body="")).handled is False


def test_handler_respects_budget_switch(tmp_path):
    h = slider.SliderHandler({}, user_data_dir=str(tmp_path), logger=_LOG)
    page = _Page2('<div class="slide-verify">拖动滑块</div>', _png())
    out = h.on_navigation(page, _Ctx(body="拖动滑块"))
    assert out.handled is False
    assert "auto" in out.detail
    assert page.mouse.events == []


def test_handler_solves_simple_when_enabled(tmp_path):
    h = slider.SliderHandler({"slider": {"auto": True}},
                             user_data_dir=str(tmp_path), logger=_LOG)
    page = _Page2('<div class="slide-verify">拖动滑块</div>', _png())
    out = h.on_navigation(page, _Ctx(body="拖动滑块"))
    assert out.handled is True
    assert page.reloads == 1
    assert len(page.mouse.events) > 10
