# -*- coding: utf-8 -*-
"""r971：把"能力边界"钉成单一事实来源（文档 + 代码双向）。

背景（2026-11-05）：仓库里关于"要不要碰验证码"的表述**自相矛盾**——
现行实现已经自动解简单滑块/拼图/算数/文字题，而
`docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md` 仍写着
「不绕过验证码/滑块」，等于告诉后来的代理"别试"。
用户明确要求：简易通用的要自动解，非常强大的人机没必要；
限制这些设计的旧文案要改掉或删掉。

处理方式：
  * 历史文档**不改写历史**，但在冲突处加「已被取代」标注并指回权威节；
  * 新增 `YIELD_AND_SESSION_STRATEGY.md` §6.51 作为唯一权威表述；
  * 本测试同时钉住**文档**和**代码标记表**，防止两边再次漂移
    （只要有人把 `点选` 从 strong 里删掉、或把旧文案改回来，这里就红）。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r971_boundary_single_source.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawlers.captcha as captcha  # noqa: E402
import crawlers.slider as slider  # noqa: E402


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. 文档：权威节存在，且两类清单都写清
# ---------------------------------------------------------------------------
def test_authoritative_section_exists():
    s = _read("docs/YIELD_AND_SESSION_STRATEGY.md")
    assert "## 6.51" in s, "权威边界节丢了"
    sec = s[s.find("## 6.51"):]
    sec = sec[:sec.find("\n## 7. ")] if "\n## 7. " in sec else sec[:8000]
    # 必须写明"自动解"和"不做"两栏
    assert "自动解" in sec
    assert "不做" in sec
    # 自动解一侧的代表项
    for kw in ("滑块", "拼图", "算数", "文字", "ddddocr"):
        assert kw in sec, "自动解清单缺 %s" % kw
    # 不做一侧的代表项（文档里 recaptcha 写作小写，比较时统一大小写）
    low = sec.lower()
    for kw in ("极验", "recaptcha", "点选", "人脸"):
        assert kw.lower() in low, "不做清单缺 %s" % kw


def test_historical_doc_is_marked_superseded():
    """历史指南里"不绕过验证码/滑块"必须带「已被取代」并指回 §6.51。

    不是删掉原文（那会篡改历史决定），而是明确它已过期——
    否则后来的代理会照着它**一次都不试**。
    """
    s = _read("docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md")
    assert "已被取代" in s or "不再是一律停手" in s, "历史文案没有标注已过期"
    assert "§6.51" in s, "没指回权威节"


# ---------------------------------------------------------------------------
# 2. 代码：强/简标记表必须与文档一致
# ---------------------------------------------------------------------------
def test_strong_marks_keep_semantic_and_behavioral_types():
    """强人机必须继续被 upcast：极验/天御/recaptcha/人脸。

    注：点选题自 r1063 T21 起属于**可解图像题**（`captcha.classify_kind`
    判 click，有检测后端时可尝试），不再放强人机表——这里同步收紧，
    避免旧断言把已实现的能力重新判死。
    """
    strong = " ".join(slider._STRONG_MARKS).lower()
    for kw in ("geetest", "tcaptcha", "recaptcha", "人脸"):
        assert kw in strong, "强人机标记缺 %s（会被误判成简单题去解）" % kw


def test_simple_marks_keep_slider_and_puzzle():
    """简单侧必须包含通用滑块与**携程拼图**（不含"滑块"字样的那种）。"""
    simple = " ".join(slider._SIMPLE_MARKS)
    for kw in ("拖动滑块", "滑动验证", "拼图验证"):
        assert kw in simple, "简单滑块标记缺 %s" % kw


def test_classify_upcasts_strong_before_simple():
    """顺序即安全侧：两个标记同时出现时必须判 strong，不许去解。"""
    t = slider.classify("极验 gt4 拖动滑块 slide-verify", "")
    assert t.name == "strong", t.name


def test_click_captcha_is_reported_but_not_solved():
    """点选题要单独报出来（对操作员有信息量），但不提供解法。"""
    kind = captcha.classify_kind("请按顺序点击【天】【安】【门】")
    assert kind.name == "click", kind.name
    assert not hasattr(captcha, "solve_click"), "不该有解点选题的实现"


def test_empty_page_is_unknown_not_simple():
    """空页面不能默认成"可以试"——那是最容易把强人机当简单题的时刻。"""
    assert slider.classify("", "").name == "unknown"
