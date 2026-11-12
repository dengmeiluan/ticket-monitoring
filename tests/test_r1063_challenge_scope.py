# -*- coding: utf-8 -*-
"""r1063 T42：挑战族的开关必须**按作用域**求值（渠道覆盖不能白写）。

修的是「声明写大、读点没接」：目录里 `slider_attempt`/`slider_guard` 早已声明
`channel` 作用域，但读点只读原始 cfg（`crawler.slider.*`），用户按渠道写的覆盖
被**静默忽略**——最痛的那类缺陷。

优先级刻意定成：**参数层有意见才采用** > 调用方 cfg > 契约默认。
（"只要 provider 能算就用"是错的：离线调用没有 `set_config` 时 provider 只会
吐契约默认值，把调用方的开关顶掉。）
"""
import pytest

from core import strategy_params as sp
from crawlers import captcha as cp
from crawlers import slider as sl


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_channel_override_turns_slider_off_for_one_channel_only():
    """渠道覆盖优先于调用方 cfg（cfg 显式给 on，覆盖给 off）。"""
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"slider_attempt.auto": "off"}}}})
    ok_f, why_f = sl.should_attempt("fliggy", {})
    ok_c, why_c = sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})
    assert ok_f is False, (ok_f, why_f)
    assert ok_c is True, (ok_c, why_c)
    # 文案不许写死键名（开关可能来自渠道覆盖）
    assert "crawler.slider.auto" not in why_f, why_f


def test_caller_cfg_still_wins_when_provider_has_no_opinion():
    """没有 `set_config`（离线/单测）时，调用方传的 cfg 必须照旧生效。"""
    assert sl.should_attempt("ctrip", {"slider": {"auto": False}})[0] is False
    assert sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})[0] is True


def test_daily_cap_follows_the_channel_override():
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"slider_guard.daily_cap": 1}}}})
    # cap=1：用掉一次之后就不许再试（账本写到 tmp）
    import tempfile
    d = tempfile.mkdtemp()
    sl.note_result("ctrip", False, {}, user_data_dir=d, profile="ctrip")
    ok, why = sl.should_attempt("ctrip", {"slider": {"auto": "auto"}},
                                user_data_dir=d, profile="ctrip")
    assert ok is False and "上限" in why, (ok, why)
    sp.invalidate()


def test_captcha_click_switch_follows_the_channel_override(monkeypatch):
    monkeypatch.setattr(cp, "_det_backend", lambda: object())
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"captcha_solve.click": False}}}})
    assert cp._pval("captcha_solve.click", "fliggy",
                    True) is False
    assert cp._pval("captcha_solve.click", "ctrip", True) is True


def test_contract_declares_channel_scope_for_captcha_solve():
    """声明必须与读点一致：读点已按 plat 求值，scope 就得有 channel。"""
    from core.strategy_contract import STRATEGIES

    s = [x for x in STRATEGIES if x.id == "captcha_solve"][0]
    assert "channel" in tuple(s.scope), s.scope


def test_param_layer_priority_is_documented_in_code():
    """优先级写进了文档串——这条守的是"下一个人不会再把它改错"。"""
    import io
    import os

    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "slider.py"),
        encoding="utf-8").read()
    seg = src[src.index("def _pval("):][:700]
    assert "source" in seg and "default" in seg
