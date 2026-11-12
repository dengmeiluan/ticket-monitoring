# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r923_slider_registration.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import pytest
import sys

from crawlers import challenge
from crawlers.base import BaseCrawler


# ---- merged from tests/test_r923_slider_registration.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r923")


@pytest.fixture(autouse=True)
def _clean():
    challenge.unregister_handler()
    yield
    challenge.unregister_handler()


def _crawler(tmp_path, **cfg):
    cfg.setdefault("user_data_dir", str(tmp_path))
    return BaseCrawler(cfg, _LOG)


# ---------------------------------------------------------------------------
# 1. 开关语义
# ---------------------------------------------------------------------------
def test_no_config_registers_handler(tmp_path):
    """r944：未配 `slider.auto` 现在是**开**。

    改这一条的理由：默认关的时候，这套能力实际上从没生效过（配了不注册、
    注册了默认还是关的）。边界改为由 `classify()` 的分级守——
    `strong`/`unknown` 一律不碰，这是真正该守的地方。
    """
    _crawler(tmp_path)
    assert getattr(challenge.current_handler(), "name", "") in (
        "solver-handler", "slider-handler")


def test_auto_off_means_no_handler(tmp_path):
    _crawler(tmp_path, slider={"auto": "off"})
    assert challenge.current_handler() is None


def test_auto_false_means_no_handler(tmp_path):
    """``auto: false``（YAML 里的布尔假）也要当作关。"""
    _crawler(tmp_path, slider={"auto": False})
    assert challenge.current_handler() is None


def test_auto_simple_registers_handler(tmp_path):
    """开 `simple` 要挂上处理器——**超集优先**（滑块 + 算数 + 文字）。

    r924 之后挂的是 ``solver-handler``（`captcha.SolverHandler`），它是
    ``slider.SliderHandler`` 的超集；两个名字都接受，因为挂不上超集时会
    退回旧实现（老行为仍可用）。
    """
    _crawler(tmp_path, slider={"auto": "simple"})
    h = challenge.current_handler()
    assert h is not None
    assert getattr(h, "name", "") in ("solver-handler", "slider-handler")


def test_auto_true_registers_handler(tmp_path):
    _crawler(tmp_path, slider={"auto": True})
    assert getattr(challenge.current_handler(), "name", "") in (
        "solver-handler", "slider-handler")


# ---------------------------------------------------------------------------
# 2. 幂等
# ---------------------------------------------------------------------------
def test_registration_is_idempotent(tmp_path):
    _crawler(tmp_path, slider={"auto": "simple"})
    first = challenge.current_handler()
    _crawler(tmp_path, slider={"auto": "simple"})
    _crawler(tmp_path, slider={"auto": "simple"})
    assert challenge.current_handler() is first      # 没被反复替换


def test_ensure_returns_handler_without_config(tmp_path):
    """未配也是开：`ensure_slider_handler` 应直接返回挂好的处理器。"""
    h = challenge.ensure_slider_handler(
        {}, user_data_dir=str(tmp_path), profile="x")
    assert getattr(h, "name", "") in ("solver-handler", "slider-handler")


# ---------------------------------------------------------------------------
# 3. 注册后接缝真的走处理器
# ---------------------------------------------------------------------------
class _Ctx:
    plat = "ctrip"
    body = ""
    url = ""


class _StrongPage:
    """强人机页：处理器必须**什么都不做**。"""

    url = "https://example.test/login"

    def __init__(self):
        self.mouse = _Mouse()

    def content(self):
        return "<div>geetest 智能验证</div>"

    def inner_text(self, sel=None):
        return "智能验证"

    def screenshot(self, full_page=False):
        return b""

    def query_selector(self, sel):
        return None


class _Mouse:
    def __init__(self):
        self.events = []

    def move(self, *a, **k):
        self.events.append("move")

    def down(self):
        self.events.append("down")

    def up(self):
        self.events.append("up")


def test_seam_routes_to_handler_but_strong_is_untouched(tmp_path):
    _crawler(tmp_path, slider={"auto": "simple"})
    page = _StrongPage()
    # after_navigation 只在识别到挑战页时调处理器；这里识别成 blocked
    handled = challenge.after_navigation(page, challenge.ChallengeContext(
        plat="ctrip", url=page.url))
    assert handled is False                       # 强人机 → 不处置
    assert page.mouse.events == []                # 一根手指都没动


# ---------------------------------------------------------------------------
# 4. 失败一律静默（不许拖垮采集器创建）
# ---------------------------------------------------------------------------
def test_broken_config_does_not_raise(tmp_path):
    """`slider` 段不是字典也要能活：当空段处理（= 默认开），且不抛。"""
    _crawler(tmp_path, slider="不是字典")
    assert getattr(challenge.current_handler(), "name", "") in (
        "solver-handler", "slider-handler")


def test_foreign_handler_is_not_clobbered(tmp_path):
    """别人显式注册的处理器不许被采集器构造顺手换掉。

    2026-11-05 实测：`ensure_slider_handler` 原先无条件注册，于是
    `register_handler(MyHandler())` 之后只要构造任一采集器就被静默换回
    内置实现——接缝等于形同虚设（`test_challenge_handler_seam` 抓到）。
    """

    class _Mine:
        name = "my-handler"

    challenge.register_handler(_Mine())
    _crawler(tmp_path, slider={"auto": "auto"})
    assert getattr(challenge.current_handler(), "name", "") == "my-handler"


def test_recording_ledger_dir_unwritable_is_silent(tmp_path):
    # 用一个不存在的深层路径做 user_data，写账本会失败 → 但不应抛
    c = BaseCrawler({"user_data_dir": str(tmp_path / "a" / "b" / "c"),
                     "slider": {"auto": "simple"}}, _LOG)
    assert c is not None
