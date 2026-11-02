# -*- coding: utf-8 -*-
"""r309 E1（推送审校立案）：KPI 行1 地板档「5 位数线」带超预算破口。

r309 推送审校实锤（_scratch/r309_push_E.md E1）：`_pct_fallback_forms`
三档降级链的末档 base 含「　线￥N　」参照段全量——「5 位数线×5 位
价×🎯加粗」合法配置带实宽 41-42/40 超预算（真实 _dw_bold 网格实测），
_fit_line 全档超宽取末档原样=恒达标律（LESSONS 十九§1）破口，三处
镜像同构（主链 _kpi_block / legacy _push_digest 直飞+中转）。

修法：单源 `_bare_line_form`（剥「　线￥N」参照段，保价格+差额核心
判据与链接壳）收进 `_pct_fallback_forms` 尾位 + 主链 mkt 分支内联链
尾——链尾地板档 ≈31 半角恒落位。剥的是参照段非核心判据，与末档输
出可辨、非数学死档（卅一§5/§16 判据）。
"""
from core.alerter import (_bare_line_form, _dw, _dw_bold, _fit_line,
                          _pct_fallback_forms)

# 最坏合法样本：5 位数线 × 5 位数价（超线差 5 位）× 🎯 点 + 加粗
_BASE_WIDE = "🎯 直飞 ￥10000　线￥39999　差￥29999"


def test_bare_line_form_strips_threshold_keeps_core():
    """地板档=剥「　线￥N」参照段：价格+差额核心判据与全角空格
    间隔保留，词面与末档可辨。"""
    bare = _bare_line_form(_BASE_WIDE)
    assert bare == "🎯 直飞 ￥10000　差￥29999"
    assert "线￥" not in bare


def test_bare_line_form_keeps_markdown_link_shell():
    """链接壳保留（LESSONS 三十§2：剥除档不剥链接——链接是该日期
    唯一文本跳转入口）。"""
    base = "[🎯 直飞 ￥10000](https://flights.example.com/x)　线￥39999　差￥29999"
    bare = _bare_line_form(base)
    assert bare.startswith("[🎯 直飞 ￥10000](https://flights.example.com/x)")
    assert bare.endswith("　差￥29999")


def test_pct_chain_tail_is_bare_form():
    """pct 有/无两分支的链尾都是剥线档（pct 空三档同形+地板档）。"""
    forms = _pct_fallback_forms(_BASE_WIDE, "3%")
    assert forms == [_BASE_WIDE + "（3%）", _BASE_WIDE + "·3%",
                     _BASE_WIDE, "🎯 直飞 ￥10000　差￥29999"]
    forms_empty = _pct_fallback_forms(_BASE_WIDE, "")
    assert forms_empty[-1] == "🎯 直飞 ￥10000　差￥29999"


def test_extreme_band_chain_lands_on_bare_within_budget():
    """端到端：极限带全链超宽时 _fit_line 落地板档且预算内达标
    （恒达标律闭合；样本可达性用真实计宽自证，非手算）。"""
    forms = _pct_fallback_forms(_BASE_WIDE, "")
    assert _dw_bold(forms[0]) > 40, "样本须确实超宽（触发档可达性前提）"
    line = _fit_line(forms[0], fallbacks=forms[1:], bold=True)
    assert line == forms[-1]
    assert _dw(line) <= 40


def test_normal_band_chain_unchanged():
    """常规带（4 位数线）首档合规：新档零触发零回归。"""
    base = "🎯 直飞 ￥1760　线￥1900　低￥140"
    forms = _pct_fallback_forms(base, "")
    line = _fit_line(forms[0], fallbacks=forms[1:], bold=True)
    assert line == forms[0]          # 首档合规原样直出
    assert forms[-1] == "🎯 直飞 ￥1760　低￥140"   # 尾档形态仍正确


def test_kpi_block_mkt_branch_uses_bare_tail():
    """主链 mkt 分支内联链尾收进单源（防调用点内联回退——档序
    悄悄回退的温床判例，源码钉锁走 helper）。"""
    import inspect
    from core import alerter
    src = inspect.getsource(alerter.Alerter._digest_payload)
    assert src.count("_bare_line_form(") >= 1, (
        "mkt 分支内联 forms 链尾必须走 _bare_line_form 单源")
