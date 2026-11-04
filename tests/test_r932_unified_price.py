# -*- coding: utf-8 -*-
"""r932：价格归一化收成**唯一实现**（`core/price.py`）。

为什么收（2026-11-04 事故链）：

============================  ==================================
解析器                         价格正则
============================  ==================================
`app_qunar_parse`              `r"\\d{2,5}"`          ← **错**，`¥5711` 全丢
`app_zhixing_parse`            `r"^[¥￥]\\s*(\\d{2,5})$"`  ← 对
`app_fliggy_parse`             `r"^\\d{3}$"`          ← 只认三位（潜在坑）
============================  ==================================

三份实现、两种写法——于是 qunar 的中转混合列表整页「带价 0 行」，
而现场 dump 里六个价好端端都在。**每处各写一套正则就是根因**。

现在统一到 `core.price.parse_price()`，谁解析价格都调它。

两条硬纪律在这里固化成代码：

1. **遮罩价不是价**：`4??` 必须返回 None。把"看不到"当成"4 元"会误触发
   降价提醒——这是比缺数据更坏的错（`app_zhixing` 的 docstring 早就警告过）。
2. **绝不返回 0**：任何取不到的情况一律 None。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r932_unified_price.py -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.price import (CURRENCY_ONLY, is_masked, looks_like_price,  # noqa
                        parse_price, strip_currency)


# ---------------------------------------------------------------------------
# 1. 正常形态
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("¥5711", 5711),
    ("￥5711", 5711),
    ("5711", 5711),
    ("¥ 680", 680),
    ("￥1,234", 1234),
    ("1，234", 1234),          # 全角逗号
    ("$999", 999),
    ("99.5", 99.5),
    ("  3305  ", 3305),
])
def test_parse_price_normal(text, want):
    assert parse_price(text) == want


# ---------------------------------------------------------------------------
# 2. 必须拒绝的（绝不给 0）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "", "   ", "¥", "￥", "$",
    "4??", "4？?", "??",                      # 遮罩
    "7",                                      # 1 位：不是票价
    "123456",                                 # 6 位：不是票价
    "已减70",                                  # 优惠标签整串
    "abc", "¥abc",
])
def test_parse_price_rejects(text):
    v = parse_price(text)
    assert v is None, (text, v)


def test_zero_is_not_a_price():
    """`¥0` 不是合法票价——0 会让"降价提醒"误触发。"""
    assert parse_price("¥0") is None
    assert parse_price("0") is None


# ---------------------------------------------------------------------------
# 3. 遮罩识别（与价格解析分开，便于上层单独判断）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("4??", True), ("4？?", True), ("??", True),
    ("¥450", False), ("450", False), ("", False),
])
def test_is_masked(text, want):
    assert is_masked(text) is want


# ---------------------------------------------------------------------------
# 4. 辅助函数
# ---------------------------------------------------------------------------
def test_strip_currency():
    assert strip_currency("¥ 1,234") == "1234"
    assert strip_currency("￥5711") == "5711"
    assert strip_currency("") == ""


def test_currency_only_tuple():
    for ch in CURRENCY_ONLY:
        assert parse_price(ch) is None


def test_looks_like_price():
    assert looks_like_price("¥5711") is True
    assert looks_like_price("4??") is False


# ---------------------------------------------------------------------------
# 5. 解析器已统一（源码钉：不许再各写一套）
# ---------------------------------------------------------------------------
def test_qunar_uses_unified_price():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar_parse.py"),
                  encoding="utf-8").read()
    assert "core.price" in src, "qunar 解析器没用统一价格实现"
    # 不允许再出现"自己剥符号再 fullmatch 位数"的老写法
    assert not any(
        ("re.sub(r\"[¥" in ln and "ItemPrice" in ln)
        for ln in src.splitlines())
