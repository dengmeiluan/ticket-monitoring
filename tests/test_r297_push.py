# -*- coding: utf-8 -*-
"""r297 推送层 R1 案（TDD 先行；自然轮实录 10-13 09:01 日报）：

- R1 日报「走势图上传失败→整节蒸发」与「明细表上传失败→小节
  保留+富文本兜底」能力不对称（三十§3 同族）：小节循环只遍历
  charts（走势上传成功者），走势图床瞬时断连时整节 KPI/明细/
  比价全失，只剩尾部一行对账——而表挂失败路径有 KPI+TOP+比价+
  渠道最低+对账注全族兜底。实录：SHA→HAK 01/29（唯一带时段窗
  的航线）首传撞 proxy disconnect，数据全在（窗内直飞 ￥2110）
  读者却零可得。
- 修复语义：小节入选=「走势图在场 ∪ 有扫描数据」；走势缺席的
  小节照常出标题（含时段窗词面，案1 三链路同源）+「走势图缺失，
  本节无走势图」留痕+表图/文本兜底（复用既有机械零新造）；
  「全窗零数据」仍走尾部单行对账（词面不变）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r297_push.py -q
"""
import logging as _lg
import sys
from datetime import datetime

import pytest

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"


def _route(fc, tc, fcn, tcn, **extra):
    r = {"from": fc, "to": tc, "from_name": fcn, "to_name": tcn,
         "dates": [_DATE], "alert_direct": 2000, "alert_transfer": 1800,
         "transfer_arrival_max": "02:00"}
    r.update(extra)
    return r


_ROUTES = [
    _route("SHA", "URC", "上海", "乌鲁木齐"),
    _route("SHA", "SYN", "上海", "三亚"),
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


@pytest.fixture()
def env(monkeypatch):
    """离线夹具：数据两航线俱全；走势图上传按航线分派——
    URC 成功、SYN 失败（charts 缺 SYN 键=今晨实录形态）。"""
    import report as rep
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, d, am, **kw: [
            (datetime(2026, 9, 20, 8, 0), 2110.0, None)])
    monkeypatch.setattr(
        rep, "prepare_round_charts",
        lambda c, lg, *a, **k: {("SHA", "URC", _DATE): "http://x/t.png"})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    return {"rep": rep}


def test_daily_trend_upload_fail_keeps_section(env, monkeypatch):
    """R1 主案：走势图上传失败但数据在场——小节必须保留：标题、
    走势缺失留痕、明细表图（兜底机械承载）全部在场，不再整节蒸发。"""
    rep = env["rep"]
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: [
            {"price": 2110, "transCity": "", "_platform": "qunar",
             "name": "南航CZ6766", "code": "CZ6766",
             "depTime": "20:35", "arrTime": "23:55"}])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert "#### 上海→三亚" in d, "走势图缺席的小节整节蒸发：" + d
    assert "走势图缺失" in d, "走势缺席须留痕：" + d
    assert "![明细总表]" in d, "表图兜底未承载：" + d
    # 正常小节（URC）不回归：走势图仍在
    assert "![走势](http://x/t.png)" in d, d


def test_daily_all_trends_fail_report_still_sent(env, monkeypatch):
    """全走势上传失败但有数据：日报照发（各小节表图/文本兜底），
    不再「无可用通路本报告未发」整篇蒸发。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {})
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: [
            {"price": 2110, "transCity": "", "_platform": "qunar",
             "name": "南航CZ6766", "code": "CZ6766",
             "depTime": "20:35", "arrTime": "23:55"}])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"], "全走势失败曾整篇未发"
    d = n.sent["desp"]
    assert "#### 上海→乌鲁木齐" in d and "#### 上海→三亚" in d, d
    assert d.count("走势图缺失") == 2, d


def test_daily_trendless_section_carries_dep_win(env, monkeypatch):
    """走势缺席小节的标题同样挂时段窗词面（案1 三链路同源：
    告警小节/推送标题/日报小节——文字兜底形态不得掉链）。"""
    rep = env["rep"]
    routes = [_route("SHA", "URC", "上海", "乌鲁木齐"),
              _route("SHA", "SYN", "上海", "三亚", dep_time_min="19:00")]
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: [
            {"price": 2110, "transCity": "", "_platform": "qunar",
             "name": "南航CZ6766", "code": "CZ6766",
             "depTime": "20:35", "arrTime": "23:55"}])
    n = FakeN()
    ok = rep.build_and_push(_cfg(routes), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert "（19:00后出发）" in d, "窗词面未随文字兜底形态：" + d


def test_daily_zero_data_route_still_single_line(env, monkeypatch):
    """全窗零数据航线维持尾部单行对账（词面不变），不升级为小节
    （零数据无 KPI/明细可兜底，单行语义正确）。"""
    rep = env["rep"]
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, d, am, **kw: (
            [] if (fc, tc) == ("SHA", "SYN")
            else [(datetime(2026, 9, 20, 8, 0), 2110.0, None)]))
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: (
            [{"price": 2110, "transCity": "", "_platform": "qunar"}]
            if (fc, tc) == ("SHA", "URC") else []))
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert "近48时无数据" in d and "上海→三亚" in d, d
    assert "#### 上海→三亚" not in d, "零数据航线不应出小节：" + d


def test_daily_duplicate_config_key_renders_once(env, monkeypatch):
    """病理重复配置（同键两条 route）只渲染一个小节：charts 侧本就
    dict 去重，走势缺席侧（_trendless）来自配置直迭代，不去重会让
    同一小节出两次（Soldier r297 Minor-1）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {})
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: [
            {"price": 2110, "transCity": "", "_platform": "qunar",
             "name": "南航CZ6766", "code": "CZ6766",
             "depTime": "20:35", "arrTime": "23:55"}])
    n = FakeN()
    ok = rep.build_and_push(_cfg([_ROUTES[1], _ROUTES[1]]),
                            _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert d.count("#### 上海→三亚") == 1, \
        "重复配置键双渲染：" + str(d.count("#### 上海→三亚"))
