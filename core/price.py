# -*- coding: utf-8 -*-
"""价格文本的**唯一**归一化实现（各解析器不要再各写一套正则）。

为什么要有这个模块（2026-11-04 的一次真实事故）
------------------------------------------------
`app_qunar` 的中转混合列表整页「有航班行、带价 0 行」，现场 dump 里价格明明
都在：

    | ¥5711 | ...|QunarFlightInterRoundMixList|ItemPrice |

但取值处写的是 ``re.fullmatch(r"\\d{2,5}", "¥5711")`` —— **带货币符号的直接
不匹配**，六个价一个不剩。上层只看到"解析不到价"，记 `no-priced-rows`。

而同一个仓库里 ``app_zhixing_parse`` 是**对的**（``^[¥￥]\\s*(\\d{2,5})$``），
``app_fliggy_parse`` 又是第三种写法（``^\\d{3}$``，只认三位）。
三份实现、两种 bug——这就是"每处各写一套"的代价。

所以把「价格文本 → 整数」收成一份，谁要解析价格都调它：

    >>> parse_price("¥5711")
    5711
    >>> parse_price("￥1,234")
    1234
    >>> parse_price("4??")          # 遮罩：看不到 ≠ 便宜
    >>> parse_price("3305")
    3305

``parse_price`` 对**遮罩价**返回 ``None`` 而不是 0 —— 把"看不到"伪装成
"很便宜"是最坏的一种错（会误触发降价提醒）。
"""
from __future__ import annotations

import re

# 货币符号：¥(U+00A5) ￥(U+FFE5) $ 及全角
CURRENCY = "\u00a5\uffe5$\uff04"
CURRENCY_ONLY = tuple(CURRENCY)

# 千分位与空白：1,234 或 1 234
_SEP = ",\uff0c"

# 合理票价区间：2–5 位整数（含两位小数）。低于 2 位或高于 5 位不是票价
# （现场反例：「已减 ¥70」的 70 是优惠标签，由上层的位置判据排除；
#  6 位数不是任何真实票价）。
_PRICE_RE = re.compile(r"^\d{2,5}(?:\.\d{1,2})?$")

# 遮罩：`4??` / `4？?` / `??` —— 数字被换成问号，说明未登录或需点击解锁
_MASK_RE = re.compile(r"^[\d?？]{1,6}$")


def strip_currency(text: str) -> str:
    """剥掉货币符号/千分位/空白，只留数字与小数点。"""
    s = str(text or "").strip()
    out = []
    for ch in s:
        if ch in CURRENCY_ONLY or ch in _SEP or ch.isspace():
            continue
        out.append(ch)
    return "".join(out)


def is_masked(text: str) -> bool:
    """这个价格是不是被遮罩（``4??``）——遮罩不是价格。"""
    s = str(text or "").strip()
    if not s:
        return False
    if "?" in s or "？" in s:
        return True
    return False


def parse_price(text: str):
    """价格文本 → ``int``；不是合法票价返回 ``None``（**绝不给 0**）。

    接受：``¥5711`` / ``￥1,234`` / ``3305`` / ``¥ 680`` / ``99.5``
    拒绝：``¥``（只有符号）/ ``4??``（遮罩）/ ``7``（1 位）/ ``123456``（6 位）
    """
    s = str(text or "").strip()
    if not s:
        return None
    if is_masked(s):
        return None
    digits = strip_currency(s)
    if not digits or not _PRICE_RE.match(digits):
        return None
    try:
        v = float(digits)
    except (TypeError, ValueError):
        return None
    # 整数就返回 int（与各渠道 "价格是整数" 的既有契约一致）
    return int(v) if abs(v - round(v)) < 1e-9 else round(v, 2)


def looks_like_price(text: str) -> bool:
    """只是判"像不像票价"，不做归一（给需要保留原文的调用方）。"""
    return parse_price(text) is not None
