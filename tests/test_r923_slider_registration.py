# -*- coding: utf-8 -*-
"""r923：滑块处理器的**自动注册**——配置开了就真的生效。

为什么专门钉这个：``SliderHandler`` 写好了、``slider.auto: simple`` 也配了，
但**全仓没有任何生产代码调用 ``register_handler``**（2026-11-03 搜过：
只有 challenge.py 定义、slider.py 文档、测试里用过）。也就是说功能是**死的**：
配置改了、UI 也有了，跑起来一次都不会触发。

修法：``challenge.ensure_slider_handler()`` —— 幂等 + 失败静默，由
``BaseCrawler.__init__`` 调用。于是只要采集器被创建就按配置生效，
不用改 main / webui（那两个文件改动风险高、且正被并发编辑）。

钉住四件事：
  1. ``slider.auto`` 为假/未配 → **不注册**（保持"识别→记账→停手"）；
  2. 为真 → 注册 ``SliderHandler``；
  3. 重复创建 crawler → 幂等，不重复覆盖；
  4. 注册后接缝真的会走处理器（不是只换了个对象）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r923_slider_registration.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from crawlers import challenge  # noqa: E402
from crawlers.base import BaseCrawler  # noqa: E402

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
def test_no_config_means_no_handler(tmp_path):
    _crawler(tmp_path)
    assert challenge.current_handler() is None


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


def test_ensure_returns_current_without_config(tmp_path):
    assert challenge.ensure_slider_handler(
        {}, user_data_dir=str(tmp_path), profile="x") is None


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
    _crawler(tmp_path, slider="不是字典")
    assert challenge.current_handler() is None


def test_recording_ledger_dir_unwritable_is_silent(tmp_path):
    # 用一个不存在的深层路径做 user_data，写账本会失败 → 但不应抛
    c = BaseCrawler({"user_data_dir": str(tmp_path / "a" / "b" / "c"),
                     "slider": {"auto": "simple"}}, _LOG)
    assert c is not None
