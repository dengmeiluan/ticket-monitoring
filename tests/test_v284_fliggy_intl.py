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
    # 2026-10-27 起废弃「建议/国内需/国际需」分档：全渠道必须登录，
    # 差异只在会话槽位。原来这条钉的是旧档位，已按新口径改写。
    assert "tuniu:'必须'" in ui
    assert "tuniu:'国内需'" not in ui


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


# ---- r386：飞猪中转卡片无航班号（实测行头「马来西亚亚航长途 等2家航司」）

def _transfer(**over):
    base = _item(nameLine="马来西亚亚航长途 等2家航司", tips="2程航班",
                 depTime="01:35", arrTime="10:20", cross="",
                 priceText="机票价格739元", priceNum="含税￥739",
                 taxText="", quantity="少量", trans="吉隆坡", segs=2)
    base.update(over)
    return base


def test_transfer_card_without_flight_no_is_kept():
    """r386：SHA→SIN 页面 82 张卡片里 68 张中转，旧解析全丢只存 14 条直飞。"""
    rows = FliggyCrawler._parse_intl_items([_transfer()], "2026-11-16")
    assert len(rows) == 1, "中转卡片不得因缺航班号被丢"
    r = rows[0]
    assert r["code"] == "", "渠道不给航班号就不编"
    assert r["name"] == "马来西亚亚航长途", "去掉「等2家航司」尾巴"
    assert r["transfer"] is True and r["transCity"] == "吉隆坡"
    assert r["price"] == 739 and r["depTime"] == "01:35"
    assert r["arrTime"] == "10:20"


def test_transfer_cards_same_dep_different_arr_not_deduped():
    """同一航司同一起飞时刻的不同中转方案必须都保留。"""
    rows = FliggyCrawler._parse_intl_items(
        [_transfer(arrTime="10:20"), _transfer(arrTime="11:35"),
         _transfer(arrTime="13:40")], "2026-11-16")
    assert len(rows) == 3, [r["arrTime"] for r in rows]
    assert sorted(r["arrTime"] for r in rows) == ["10:20", "11:35", "13:40"]


def test_transfer_without_price_or_times_still_dropped():
    """认不出/没时刻/没价的仍然丢——不当假行。"""
    rows = FliggyCrawler._parse_intl_items([
        _transfer(priceText="机票价格0元"),
        _transfer(depTime="", arrTime=""),
        _item(nameLine="", trans="", segs=1),   # 无行头也非中转
    ], "2026-11-16")
    assert rows == []


def test_direct_card_unchanged():
    rows = FliggyCrawler._parse_intl_items([_item()], "2026-11-16")
    assert len(rows) == 1 and rows[0]["code"] == "9C7293"
    assert rows[0]["transfer"] is False


# ---- r386：无航班号的中转行不得被下游当成"日历行/非真实班次"

def test_ui_and_backend_treat_timed_row_as_real_flight():
    """前端 srxIsCal 与后端 _real_offer 都只认时刻。

    曾额外要求 code：飞猪国际中转卡片不给航班号，会被标成日历行 /
    非真实班次，于是"页面有中转"变成"页面没中转"。
    """
    import inspect
    import webui
    src = inspect.getsource(webui)
    assert ("function srxIsCal(f){return !!f.isCal||!(f.depTime&&f.arrTime)}"
            in src), "前端日历判据必须只看时刻"
    assert "!(f.code&&f.depTime&&f.arrTime)" not in src, \
        "不得再以 code 缺失判为日历行"


def test_calendar_row_still_detected_by_missing_times():
    from core import alerter as A
    cal = {"price": 719, "name": "日历最低价", "depTime": "", "arrTime": ""}
    assert A._is_calendar_row(cal) is True
    transfer = {"price": 1992, "name": "海湾航空", "code": "",
                "depTime": "16:30", "arrTime": "06:35",
                "transCity": "巴林", "transfer": True}
    assert A._is_calendar_row(transfer) is False, \
        "有时刻的中转行是真实班次，不是日历行"


def test_transfer_segments_not_written_into_plane():
    """r386：tips 对中转是段数标记（「2程航班」），不能占机型字段。"""
    rows = FliggyCrawler._parse_intl_items(
        [_transfer(tips="2程航班")], "2026-11-16")
    r = rows[0]
    assert r["plane"] == "", "机型不得写成「2程航班」"
    assert r["segments"] == 2, "段数另立字段供展示"


def test_direct_plane_kept_and_segments_zero():
    rows = FliggyCrawler._parse_intl_items(
        [_item(tips="中型机321")], "2026-11-16")
    r = rows[0]
    assert r["plane"] == "中型机321"
    assert r["segments"] == 0


def test_segments_parsed_from_tips_not_from_time_blocks():
    """segs（.time-info 计数）对中转恒为 1；段数必须来自「N程航班」。"""
    two = FliggyCrawler._parse_intl_items([_transfer(tips="2程航班")],
                                          "2026-11-16")[0]
    four = FliggyCrawler._parse_intl_items([_transfer(tips="4程航班")],
                                           "2026-11-16")[0]
    assert two["segments"] == 2 and four["segments"] == 4
    assert FliggyCrawler._seg_n("2程航班") == 2
    assert FliggyCrawler._seg_n("") == 2   # 有转城市即至少两段
