# -*- coding: utf-8 -*-
"""r368: Tuniu page tokenKey extraction for the authenticated list API."""
import logging
import os
from urllib.parse import urlencode

from crawlers.tuniu import TuniuCrawler


def test_token_from_list_request_url():
    d = '{"systemId":53,"segmentList":[],"tokenKey":"abc123"}'
    url = "https://flight-api.tuniu.com/wzt/flight/v1/listFlight?" + urlencode({"d": d})
    assert TuniuCrawler._token_from_request(url) == "abc123"


def test_token_missing_or_bad_payload_is_empty():
    assert TuniuCrawler._token_from_request("https://x/listFlight?d=%7Bbad") == ""
    assert TuniuCrawler._token_from_request("https://x/listFlight") == ""


def test_crawler_uses_saved_h5_surface_profile(tmp_path):
    base = tmp_path / "tuniu"
    (base / "surfaces" / "h5" / "Default").mkdir(parents=True)
    (base / "surfaces" / "pc" / "Default").mkdir(parents=True)
    c = TuniuCrawler({"user_data_dir": str(tmp_path)},
                     logging.getLogger("test-tuniu-surface"))
    c.use_mobile = True
    assert c.user_data_dir.endswith(os.path.join("surfaces", "h5"))
    c.use_mobile = False
    assert c.user_data_dir.endswith(os.path.join("surfaces", "pc"))


def test_pc_runs_before_token_and_token_is_only_for_fallback():
    """r760：PC 列表先跑，token 只在 PC 没明细时用来打接口。

    旧契约（`if not ret_date and not h5_token:` 才跑 PC）已被推翻：国内
    listFlight 对**站点自己发的请求**也回 710114，拿得到 token 反而把唯一
    能出数的 PC 列表绕过去，把成功采集记成 login。
    """
    src = open(TuniuCrawler.__module__.replace(".", "/") + ".py",
               encoding="utf-8").read()
    assert "if not ret_date and not h5_token:" not in src, (
        "PC 仍被 token 挡住——会把有数据的通路跳过")
    # PC 在 token 之前：`_fetch_pc_dom` 的调用行要先于 `_saved_page_token`
    # 2026-11-02：PC 只查近 30 天（远日期走 H5/API），调用参数改为
    # `_pc_dates`，但顺序契约不变。
    i_pc = src.index("_fetch_pc_dom(fc, tc, _pc_dates)")
    i_tok = src.index("h5_token = self._saved_page_token(fc, tc, missing[0])")
    assert i_pc < i_tok, "取 token 的代码跑在 PC 之前，PC 又会被跳过"

