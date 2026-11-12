# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r760_tuniu_pc_before_token.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import pytest
import sys

from crawlers.tuniu import TuniuCrawler
from unittest import mock


# ---- merged from tests/test_r760_tuniu_pc_before_token.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
