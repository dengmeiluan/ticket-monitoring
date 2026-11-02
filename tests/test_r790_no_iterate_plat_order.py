# -*- coding: utf-8 -*-
"""r790：不允许用 `SRX_PLAT_ORDER` **遍历**去渲染渠道（它只有 5 家）。

来由（2026-11-01 实测）：检索页「本次渠道产物」条写的是
`SRX_PLAT_ORDER.forEach(...)`。那个常量是**排序表**，只有 5 家浏览器
渠道；于是 App 渠道即使本轮真有产出（真实库 SHA→SIN 智行 App 14 行），
在产物条里也永远不出现——用户无从知道它跑没跑。

这不是孤例：同一文件里另有三处已修过的同款（探针结果、通路证据、
实时进度），注释都写着「App 渠道永远不显示 / 过滤会把 App 吞掉」。
所以钉成门禁，新增 App 渠道时不会再漏。

判据（源码层，按用法而非字面）：
  1. `SRX_PLAT_ORDER.forEach(` / `.map(` / `.filter(` 一律禁止——
     这三种都是「按常量决定集合」；
  2. 允许的只有 `indexOf` 参与 `sort` 比较（排序），以及常量定义本身。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")

# 按常量决定「有哪些渠道」的用法：一律禁止
FORBIDDEN = re.compile(
    r"SRX_PLAT_ORDER\s*\.\s*(forEach|map|filter|reduce|slice|concat)\s*\(")


def _lines():
    return io.open(WEBUI, encoding="utf-8").read().splitlines()


def _strip_comment(line: str) -> str:
    """去掉行内注释后再判——注释里提到这种写法是允许的（本文件的
    历史说明里就引用了 `SRX_PLAT_ORDER.filter(...)`）。"""
    s = line
    for opener in ("/*", "//"):
        i = s.find(opener)
        if i >= 0:
            s = s[:i]
    return s


def _code_lines():
    """返回 [(行号, 去注释后的代码)]。

    块注释要跨行跟踪：本文件的历史说明里就成段引用了
    `SRX_PLAT_ORDER.filter(...)` 这类旧写法（解释为什么改掉），
    按单行剥注释会把这些**续行**误判成真代码。
    """
    out, in_block = [], False
    for i, ln in enumerate(_lines(), 1):
        s = ln
        buf = ""
        while s:
            if in_block:
                j = s.find("*/")
                if j < 0:
                    s = ""
                    break
                s = s[j + 2:]
                in_block = False
            else:
                j = s.find("/*")
                k = s.find("//")
                if j >= 0 and (k < 0 or j < k):
                    buf += s[:j]
                    s = s[j + 2:]
                    in_block = True
                elif k >= 0:
                    buf += s[:k]
                    s = ""
                else:
                    buf += s
                    s = ""
        out.append((i, buf))
    return out


def test_no_for_each_over_the_five_channel_order():
    bad = []
    for i, code in _code_lines():
        if FORBIDDEN.search(code):
            bad.append((i, code.strip()[:100]))
    assert not bad, (
        "用 SRX_PLAT_ORDER 决定渠道集合会把两款 App 漏掉"
        "（它只有 5 家浏览器渠道）；集合应以数据/声明为准，它只用于排序：%s"
        % bad[:5])


def test_order_is_still_used_for_sorting():
    """反向守：排序仍要靠它——否则上面那条会被「干脆不用」绕过，
    渠道顺序又回到各处各排一套。"""
    src = io.open(WEBUI, encoding="utf-8").read()
    assert src.count("SRX_PLAT_ORDER.indexOf(") >= 3, (
        "SRX_PLAT_ORDER 应继续用于排序（indexOf 参与 sort 比较）")


def test_channel_set_comes_from_data_or_declaration():
    """正面守：产物条这类「列出渠道」的地方，集合来自数据或探针 want。"""
    src = io.open(WEBUI, encoding="utf-8").read()
    assert "_capPlats" in src, (
        "产物条的渠道集合应显式从数据/请求派生（_capPlats），而不是常量")


@pytest.mark.parametrize("needle", [
    "SRX_PLAT_ORDER.forEach(", "SRX_PLAT_ORDER.filter(",
    "SRX_PLAT_ORDER.map(",
])
def test_forbidden_patterns_are_actually_detectable(needle):
    """负控：确认正则真的能抓到自己禁止的写法（否则门禁恒绿）。"""
    assert FORBIDDEN.search("  const a = " + needle + "x=>x);"), needle
