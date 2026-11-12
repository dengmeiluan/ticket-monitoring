# -*- coding: utf-8 -*-
"""r1185：轴 19「可精准控制」——改**一格**，邻格不许跟着变。

v2.1 §4.1 轴 19 的判据是"能定位到这一家渠道 × 这一条通路 × 这一阶段，改它只影响它"。
光有作用域键（`override_key`）不算数：真正要证明的是**泄漏为零**。

本文件就是那个"单格实验"：
只给 `ctrip / dom / PC` 这**一格**关掉 `path_fallback.enabled`，然后逐个查邻居——
同一渠道的另一条通路、同一通路的另一个维度、另一家渠道的同一格，都必须仍旧是"启用"。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import strategy_params as sp  # noqa: E402
from core.pacing import Pacing  # noqa: E402


@pytest.fixture(autouse=True)
def _restore():
    yield
    sp.invalidate()


def _cfg_one_cell_off():
    key = sp.override_key("ctrip", "domestic", "PC")
    return {"crawler": {"strategy_overrides": {
        key: {"path_fallback.enabled": False}}}}


def test_only_that_cell_turns_off():
    sp.set_config(_cfg_one_cell_off())
    p = Pacing()
    assert p._path_enabled("ctrip", "domestic", "PC") is False, "目标格本身没关掉"
    # 邻居一格都不许受影响
    assert p._path_enabled("ctrip", "domestic", "H5") is True, "同渠道另一条通路被误伤"
    assert p._path_enabled("ctrip", "intl", "PC") is True, "同通路另一维度被误伤"
    assert p._path_enabled("fliggy", "domestic", "PC") is True, "另一家渠道被误伤"
    assert p._path_enabled("tongcheng", "domestic", "PC") is True


def test_empty_config_keeps_everything_on():
    """负控：没有覆盖时必须全开（默认启用是行为基线）。"""
    sp.set_config({})
    p = Pacing()
    for plat in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        for path in ("PC", "H5", "H5/API"):
            assert p._path_enabled(plat, "domestic", path) is True, (plat, path)


def test_restore_after_invalidate():
    """把配置撤掉，那一格必须自己恢复——否则"关一格"会变成永久伤。"""
    sp.set_config(_cfg_one_cell_off())
    assert Pacing()._path_enabled("ctrip", "domestic", "PC") is False
    sp.invalidate()
    assert Pacing()._path_enabled("ctrip", "domestic", "PC") is True


def test_override_key_roundtrip_with_slash_path():
    """通路名里带 `/`（真实存在 `H5/API`）也要能拼回去、解回来。"""
    key = sp.override_key("tuniu", "intl", "H5/API")
    assert "/" in key
    assert sp.parse_override_key(key) == ("tuniu", "intl", "H5/API")
