# -*- coding: utf-8 -*-
"""v1.5.289 同程国际 H5 真实明细（原站 book1 服务端直出卡片）。

2026-10-23 实测：m.ly.com/tiflight/book1 在已保存会话下直出航班卡片
（SHA→OSA 2026-10-25，34 条去重明细，最低 ¥1418 春秋 9C6575）。
离线钉：URL 契约、卡片解析/去重/跨天、可选探测门（探针可见窗口，
定时监控不弹窗）。DOM 选择器契约钉在 `.flight-list` 根节点——按
`.flight-main.mb-12` 取只能拿到时刻价格、航司/航班号恒空。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402


def _card(**kw):
    base = {
        "dep": "08:05", "arr": "11:20", "depAp": "浦东T2",
        "arrAp": "关西T2", "dur": "2时15分", "price": "1418",
        "tickets": "余3张", "airline": "春秋航空", "code": "9C6575",
        "aircraft": "空客A321(中)", "transfer": False, "via": "",
        "share": False,
    }
    base.update(kw)
    return base


def test_intl_h5_url_contract():
    url = TongchengCrawler._intl_h5_url(
        "SHA", "OSA", "2026-10-25", "上海", "大阪")
    assert url.startswith("https://m.ly.com/tiflight/book1.html?")
    for part in ("tt=0", "dc=SHA", "ac=OSA", "dt=2026-10-25",
                 "rt=1900-01-01", "cabin=Y|S|C|F"):
        assert part in url, part
    assert "%E4%B8%8A%E6%B5%B7" in url
    assert "%E5%A4%A7%E9%98%AA" in url


def test_cards_parse_real_fields():
    rows = TongchengCrawler._parse_intl_cards(
        [_card()], "2026-10-25")
    assert len(rows) == 1
    f = rows[0]
    assert f["code"] == "9C6575"
    assert f["name"] == "春秋航空"
    assert f["price"] == 1418.0
    assert f["depTime"] == "08:05" and f["arrTime"] == "11:20"
    assert f["depAirport"] == "浦东T2"
    assert f["arrAirport"] == "关西T2"
    assert f["duration"] == 135
    assert f["seats"] == "3"
    assert f["source"] == "ts_h5" and f["intl"] == 1
    # 无中转证据不得落 transfer=0 冒充直飞
    assert "transfer" not in f


def test_cards_overnight_and_transfer_evidence():
    rows = TongchengCrawler._parse_intl_cards(
        [_card(code="NX117", dep="16:50", arr="12:45",
               dur="18时55分", price="1887", transfer=True,
               via="澳门", airline="澳门航空")], "2026-10-25")
    f = rows[0]
    assert f["arrDate"] == "2026-10-26"
    assert f["transfer"] == 1
    assert f["transCity"] == "澳门"


def test_cards_dedup_keep_lowest_and_drop_invalid():
    rows = TongchengCrawler._parse_intl_cards([
        _card(price="1500"),
        _card(price="1418"),
        _card(code=""),                    # 缺航班号
        _card(dep=""),                     # 缺时刻
        _card(price=""),                   # 缺价
        _card(price="999999"),             # 越价格上界
    ], "2026-10-25")
    assert len(rows) == 1
    assert rows[0]["price"] == 1418.0


def test_probe_only_visible_window_and_dom_selector():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tongcheng.py"), encoding="utf-8").read()
    assert "headless=(False if self.probe_mode else None)" in src
    assert "#flightBoxId .flight-list'" in src
    assert ".flight-list .flight-main.mb-12" not in src
    assert ".airplane-box > span" in src
    assert "[class*=trans-style]" in src

    ts = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tuniu.py"), encoding="utf-8").read()
    assert 'if missing and getattr(self, "probe_mode", False):' in ts
    # 已保存会话读取不得引用未定义 headless（NameError 曾使 httpx
    # 匿名请求丢登录 cookie，接口恒 710114）
    _cookie_seg = ts.split("def _saved_session_cookies", 1)[1].split(
        "def ", 1)[0]
    assert "self.browser(headless=headless)" not in _cookie_seg
    assert "self.browser(headless=True)" in _cookie_seg
