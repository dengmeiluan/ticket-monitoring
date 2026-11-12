# -*- coding: utf-8 -*-
"""r1246：`cookies_or_empty()` —— 读 cookie 遇到同名跨域重复时降级，不许整轮归零。

背景（2026-11-10 15:40 实测）：`crawlers/tuniu.py` 两处 `for c in ctx.cookies():`
在 cookie jar 有同名跨域项（`.tuniu.com` 与 `flight.tuniu.com` 的 `mtoken`）时
直接抛 `Multiple cookies exist with name=mtoken`，把整条 PC 列表通路打成"请求异常"。
r1245 改为走 `cookies_or_empty()`：读不到就返回空 + 一条 warning。

契约：
1. 正常情况原样返回（**不改变正常路径**）；
2. 只有 `Multiple cookies exist` 这一类降级为空；**其它异常必须照常抛**（不许吞）；
3. 降级时若给了 logger，要留痕。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.base import cookies_or_empty  # noqa: E402


class Ctx:
    def __init__(self, behavior):
        self.behavior = behavior

    def cookies(self):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


class Log:
    def __init__(self):
        self.warns = []

    def warning(self, fmt, *a):
        self.warns.append(fmt % a if a else fmt)


def test_normal_passthrough():
    ck = [{"name": "a", "domain": "d", "path": "/"}]
    assert cookies_or_empty(Ctx(ck)) == ck


def test_multiple_cookies_degrades_to_empty():
    log = Log()
    got = cookies_or_empty(Ctx(Exception("Multiple cookies exist with name=mtoken")), log)
    assert got == []
    assert log.warns, "降级必须留痕"


def test_other_errors_still_raise():
    """负控：别的异常不许被吞——那会把真故障变成"没 cookie"。"""
    try:
        cookies_or_empty(Ctx(Exception("Target page, context or browser has been closed")))
    except Exception as e:
        assert "closed" in str(e)
    else:
        raise AssertionError("非目标异常被吞了")


def test_none_logger_is_safe():
    assert cookies_or_empty(Ctx(Exception("Multiple cookies exist with name=x"))) == []


def test_tuniu_uses_the_helper():
    import io
    s = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"), encoding="utf-8").read()
    assert "cookies_or_empty(ctx)" in s, "tuniu 仍在前台裸读 cookie"
    assert "ctx.cookies()" not in s, "仍有裸 ctx.cookies() 调用"
    # 导入可能是多行的：查 import 语句块，不查某一行
    i = s.find("from .base import (")
    assert i > 0, "找不到 .base 导入"
    j = s.find(")", i)
    assert "cookies_or_empty" in s[i:j], "import 块里没带 cookies_or_empty"
