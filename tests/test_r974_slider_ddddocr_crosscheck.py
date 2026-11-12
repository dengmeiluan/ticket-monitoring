# -*- coding: utf-8 -*-
"""r974：ddddocr 滑轨模型接进 `find_gap`——两法互补，且缺它时行为不变。

背景（2026-11-05 核实）：`captcha.slide_match()` 的注释早就写着

> 这是给 ``slider.find_gap`` 的可选增强：ddddocr 的滑轨模型对"缺口与背景
> 同色系/有噪点"的图更稳，而我们的边缘法对"两条强边"最稳——两者互补。

但全仓 **grep 调用点为零**：装了 ddddocr，滑轨模型一直闲置，
`find_gap` 只有边缘能量一种方法。属于"文档承诺了、代码没做"那一族
（与 §6.53/§6.54 同类），区别是它不制造错误结论，只让能力闲置。

合并规则（`_merge_gap`，刻意不喧宾夺主）：

1. ddddocr 不可用 / 结果小于 `min_offset` → **原样返回**，与旧实现逐字节等价；
2. 边缘法**空结果**而 ddddocr 有值 → 用它（旧行为是 `(0, [])` 直接放弃，白丢一题）；
3. 两法接近（≤ `GAP_AGREE_PX`）→ 保持边缘法结果（互证＝高置信，顺序不动）；
4. 两法分歧 → ddddocr 的值作为**额外候选**追加，交给既有
   "顺次试前 3 个候选"的机制，不篡改首选。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r974_slider_ddddocr_crosscheck.py -q
"""
import io as _io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import slider  # noqa: E402


def _png(w=822, h=200, gray=128) -> bytes:
    from PIL import Image
    im = Image.new("L", (w, h), gray)
    buf = _io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 纯函数：合并规则
# ---------------------------------------------------------------------------
def test_none_degrades_to_old_behaviour():
    """ddddocr 不可用 → 原样返回（**不得**改变任何既有结果）。"""
    for best, cands in ((300, [(300, 1.3), (120, 1.1)]), (0, []), (57, [(57, 1.4)])):
        assert slider._merge_gap(best, cands, None) == (best, cands)


def test_too_small_value_is_rejected():
    """小于 min_offset 的 x 是"拼图块自己"，不可信 → 原样返回。"""
    assert slider._merge_gap(300, [(300, 1.3)], 5, min_offset=12) == (300, [(300, 1.3)])


def test_rescues_when_edge_method_found_nothing():
    """边缘法空 + ddddocr 有值 → 用它。旧行为在这里直接放弃。"""
    best, cands = slider._merge_gap(0, [], 304)
    assert best == 304
    assert cands and cands[0][0] == 304


def test_agreement_keeps_edge_result_and_order():
    """两法接近 → 保持边缘法结果与顺序（互证即高置信）。"""
    cands = [(300, 1.3), (120, 1.1)]
    assert slider._merge_gap(300, cands, 308) == (300, cands)


def test_disagreement_appends_without_usurping():
    """两法分歧 → 追加为额外候选，但首选仍是边缘法的。"""
    cands = [(300, 1.3), (120, 1.1)]
    best, merged = slider._merge_gap(300, cands, 500)
    assert best == 300, "ddddocr 的分歧值不许篡位"
    offsets = [o for o, _s in merged]
    assert 500 in offsets, "分歧值应作为额外候选被尝试"
    assert offsets[0] == 300


def test_duplicate_disagreement_is_not_appended_twice():
    """已存在同一位置就不重复追加。"""
    cands = [(300, 1.3), (500, 1.2)]
    _best, merged = slider._merge_gap(300, cands, 502)
    assert [o for o, _s in merged].count(500) == 1


# ---------------------------------------------------------------------------
# 2. 整条链路：缺 ddddocr 时与旧实现完全一致
# ---------------------------------------------------------------------------
def test_find_gap_equals_edge_only_when_ddddocr_missing(monkeypatch):
    monkeypatch.setattr(slider, "_ddddocr_gap", lambda *a, **k: None)
    png = _png()
    assert slider.find_gap(png) == slider._find_gap_edges(png)


def test_find_gap_rescues_uniform_image(monkeypatch):
    """纯色图边缘法找不到任何缺口（旧行为 (0, [])）；ddddocr 给出值时用它。"""
    png = _png()
    base = slider._find_gap_edges(png)
    assert base == (0, []), "前提变了：纯色图不该有边缘候选"
    monkeypatch.setattr(slider, "_ddddocr_gap", lambda *a, **k: 304)
    best, cands = slider.find_gap(png)
    assert best == 304 and cands[0][0] == 304


def test_ddddocr_gap_returns_none_when_backend_missing(monkeypatch):
    """`slide_match` 不可用（返回 None）→ `_ddddocr_gap` 也是 None，不抛。"""
    from crawlers import captcha
    monkeypatch.setattr(captcha, "slide_match", lambda *a, **k: None)
    assert slider._ddddocr_gap(_png()) is None


def test_ddddocr_gap_survives_bad_image():
    """坏图不许抛：返回 None 就走边缘法。"""
    assert slider._ddddocr_gap(b"not-a-png") is None
    assert slider.find_gap(b"not-a-png") == (0, [])


# ---------------------------------------------------------------------------
# 3. 结构约束：不能再出现"注释承诺、无人调用"
# ---------------------------------------------------------------------------
def test_slide_match_now_has_a_caller():
    src = _io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                   encoding="utf-8").read()
    assert "_ddddocr_gap" in src and "slide_match" in src, \
        "slider 里没有接 slide_match 的调用点"
    assert "def _find_gap_edges(" in src, "边缘法实现应保留为独立函数"
