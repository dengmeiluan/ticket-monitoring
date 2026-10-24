# -*- coding: utf-8 -*-
"""v1.5.284 飞猪国际列表：PC 明细优先、日历兜底、字段与去重。"""
import logging

from crawlers.fliggy import FliggyCrawler

_LOG = logging.getLogger("t_v284_fliggy")


def _item(**over):
    base = {
        "nameLine": "春秋航空 9C7293", "tips": "中型机321",
        "depTime": "22:25", "arrTime": "02:20", "cross": "+1天",
        "depAirport": "浦东国际机场T2", "arrAirport": "素万那普国际机场",
        "duration": "约4时55分", "priceText": "机票价格745元",
        "priceNum": "含税￥745", "taxText": "￥457", "quantity": "1张",
        "trans": "", "segs": 1,
    }
    base.update(over)
    return base


def test_parse_intl_items_maps_and_dedupes():
    items = [
        _item(),
        _item(),  # 同班同价重复渲染
        _item(nameLine="泰国越捷航空 VZ3525", priceText="机票价格803元",
              priceNum="含税￥803", taxText="￥500", depTime="02:30",
              arrTime="06:30", cross=""),
        _item(nameLine="坏行 123", depTime="", arrTime=""),
        _item(nameLine="坏价 XX123", priceText="机票价格0元"),
    ]
    rows = FliggyCrawler._parse_intl_items(items, "2026-11-16")
    assert len(rows) == 2
    first = [r for r in rows if r["code"] == "9C7293"][0]
    assert first["name"] == "春秋航空"
    assert first["depTime"] == "22:25" and first["arrTime"] == "02:20"
    assert first["price"] == 745 and first["tax"] == 457
    assert first["depAirport"] == "浦东国际机场T2"
    assert first["totalDuration"] == "4时55分"
    assert first["depDate"] == "2026-11-16" and first["intl"] == 1
    assert first["crossDayDesc"] == "+1天"


def test_intl_pc_first_then_calendar_for_missing_dates(monkeypatch):
    f = FliggyCrawler({}, _LOG)
    row = FliggyCrawler._parse_intl_items([_item()], "2026-11-16")[0]
    monkeypatch.setattr(f, "_fetch_intl_pc",
                        lambda fc, tc, dates: {"2026-11-16": [row],
                                               "2026-11-17": []})
    seen = {}

    def _cal(fc, tc, dates, fc0, tc0, ret=""):
        seen["dates"] = list(dates)
        return []

    monkeypatch.setattr(f, "_fetch_intl_calendar", _cal)
    out = f._fetch_intl("SHA", "BKK", ["2026-11-16", "2026-11-17"])
    assert len(out) == 1 and out[0].depart_date == "2026-11-16"
    assert out[0].price == 745 and out[0].flight_no == "9C7293"
    assert seen["dates"] == ["2026-11-17"]


def test_intl_pc_empty_uses_calendar(monkeypatch):
    f = FliggyCrawler({}, _LOG)
    from crawlers.base import FlightPrice
    monkeypatch.setattr(f, "_fetch_intl_pc",
                        lambda fc, tc, dates: {d: [] for d in dates})
    monkeypatch.setattr(f, "_fetch_intl_calendar",
                        lambda fc, tc, dates, fc0, tc0, ret="": [
                            FlightPrice(platform="fliggy", from_city="SHA",
                                        to_city="BKK", depart_date=dates[0],
                                        price=799.0, airline="", flight_no="",
                                        depart_time="", arrive_time="",
                                        extra="[]")])
    out = f._fetch_intl("SHA", "BKK", ["2026-11-16"])
    assert len(out) == 1 and out[0].price == 799.0


def test_login_card_bottom_alignment_and_capbar_sync_pins():
    import pathlib
    import webui
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert ".lgcard .btn2{margin:auto 0 0;width:100%;justify-content:center}" in src
    assert "function channelAuthView(p){" in src and "function loadChannelState(force){" in src
    assert "channelAuthView(p).needsLogin" in src and "本次无结果" in src
    assert "会话待重登" not in src


def test_tuniu_domestic_login_wall_and_session_injection_pins():
    import pathlib
    import webui
    from crawlers.tuniu import TuniuCrawler
    assert TuniuCrawler.login_suspect in (True, False)
    src = pathlib.Path(webui.__file__).parent.joinpath(
        "crawlers", "tuniu.py").read_text(encoding="utf-8")
    assert "login_suspect = False" in src
    assert "def _saved_session_cookies(self)" in src
    assert "710114" in src and "国内接口 710114 请登录" in src
    assert "self._install_tac_cookies(client)" in src
    ui = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "tuniu:'国内需'" in ui


def test_tongcheng_session_evidence_and_density_pins():
    import pathlib
    import webui
    from crawlers.tongcheng import TongchengCrawler
    assert TongchengCrawler.login_suspect in (True, False)
    tc = pathlib.Path(webui.__file__).parent.joinpath(
        "crawlers", "tongcheng.py").read_text(encoding="utf-8")
    assert "login_suspect = False" in tc
    assert "type(self).login_suspect = True" in tc
    assert "type(self).login_suspect = False" in tc
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "近 14 天出发日均未采" in src and "data-bandexpand" in src
    assert "@media(max-height:980px)" in src and "srx-probe-on .srx-audit" in src
