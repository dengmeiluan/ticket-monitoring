# -*- coding: utf-8 -*-
"""r760：途牛国内不能因为「拿得到 token」就跳过 PC 列表。

来由（2026-10-31 实测）：
  * m 站列表页自己发出的那条 `listFlight` 请求**也**返回
    `{"errorCode":710114,"msg":"请登录"}`——在真浏览器、三个登录 cookie
    （isLogined/ssoUser/PASSPORTSESSID）都在的情况下。所以那条接口当前
    对本环境恒失败，跟用户有没有登录无关。
  * 而同一份登录态下，PC 列表页（`flight.tuniu.com/domestic/list/
    {fc}_{tc}_ST_1_0_0`）**能**出真实航班（东航 MU5186 ￥410 等）。
  * 旧逻辑是 `h5_token = _saved_page_token(...)`，然后
    `if not h5_token: 去跑 PC`。于是只要页面能拿到 token，唯一的出数
    通路就被绕过去了，最后把「PC 本来能拿到数据」记成 `login`，用户
    重新登录也修不好。

判据（行为层，不靠读源码猜）：
  * 构造一个「token 拿得到、PC 出数」的场景，`fetch` 必须返回 PC 行，
    且 PC 路径被记账；
  * 负控：把 token 置空也必须走 PC —— 说明 PC 不是被 token 顺带放行的。
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from crawlers.tuniu import TuniuCrawler


class _Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def _crawler():
    c = TuniuCrawler(_Cfg(), mock.MagicMock())
    c.config = _Cfg()
    return c


@pytest.fixture
def crawler():
    c = _crawler()
    c._sleep = lambda: None
    return c


def _pc_rows(date="2026-11-20"):
    return {date: [{"price": 410.0, "code": "MU5186", "name": "东航",
                    "depTime": "07:30", "arrTime": "09:45"}]}


def test_pc_runs_even_when_page_token_is_available(crawler):
    """token 拿得到时，PC 依然要跑——这是 r760 的核心回归点。"""
    crawler._saved_page_token = lambda *a, **k: "tok-30-chars"
    crawler._fetch_pc_dom = lambda *a, **k: _pc_rows()
    crawler._hoop = mock.MagicMock(return_value=None)

    rows = crawler.fetch("上海", "北京", ["2026-11-20"])

    assert rows, "token 可用时 PC 被跳过，导致有数据的通路没跑"
    assert rows[0].price == 410.0
    assert crawler._hoop.call_count == 0, "PC 出了数还去打必失败的接口"


def test_pc_runs_when_token_is_empty(crawler):
    """负控：没有 token 时同样走 PC（证明 PC 不是被 token 顺带放行的）。"""
    crawler._saved_page_token = lambda *a, **k: ""
    crawler._fetch_pc_dom = lambda *a, **k: _pc_rows()

    rows = crawler.fetch("上海", "北京", ["2026-11-20"])

    assert rows and rows[0].price == 410.0


def test_token_is_only_used_after_pc_has_no_rows(crawler):
    """接口兜底仍要保留：PC 空时才去拿 token 打接口。"""
    calls = {"token": 0}

    def _token(*a, **k):
        calls["token"] += 1
        return "tok"

    crawler._fetch_pc_dom = lambda *a, **k: {"2026-11-20": []}
    crawler._saved_page_token = _token
    crawler._hoop = mock.MagicMock(return_value=None)

    crawler.fetch("上海", "北京", ["2026-11-20"])

    assert calls["token"] == 1, "PC 空的时候应该去取 token 走接口兜底"
    assert crawler._hoop.call_count >= 1


def test_710114_from_page_itself_is_not_our_missing_header():
    """回归钉子：710114 是站点自身请求也拿到的结果，注释里必须留住这一点。

    删掉这段说明的人，很可能下一次又把它当成「我们缺登录态」重复排查。
    """
    import io
    src = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tuniu.py"), encoding="utf-8").read()
    assert "站点自身的" in src or "页面自己" in src, (
        "tuniu.py 里丢了「710114 是站点自身请求也返回」这条实测记录")
