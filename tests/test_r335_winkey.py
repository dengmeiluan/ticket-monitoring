# -*- coding: utf-8 -*-
"""字段/行型哨窗键控去重（r335）：告警去重与连击键从跨窗共享的
(plat,fld) 平键升到与供给基线同粒度的 (plat,fld,fc,tc,date) 窗键。

共享平键的同日「今日已报」短路曾吞掉次窗断供首鸣（同渠道多窗断供
只有首窗鸣实录：02-14 晨间零供被 02-13 火点遮蔽），连日升级计数亦被
跨窗共享摊薄。窗键控后：多窗各自首鸣、词面自带窗辨识、连日按窗独立
累计；行为型哨（rowfall/median/noDet/rowlow，跨窗聚合量）与 iata
分歧保持平键。never-supplied 静默在窗键下结构性自守：本窗键的留痕
只能在供给后产生（供给门在留痕写点之前），无源窗键永无留痕可摘——
旧共享键时代的摘除机械随之退役。
"""

import json
import os
import sys
from types import SimpleNamespace as _NS

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

import main as _m  # noqa: E402
import core.health as _health  # noqa: E402


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _iso(monkeypatch, tmp_path):
    # r320 写入面生产资格门双锚：helper 读 SENTINEL_STATE_FILE 环境变量
    # 优先，仅 patch 模块属性会被绕过（读写劈叉）
    monkeypatch.setenv("SENTINEL_STATE_FILE",
                       str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    return _L()


def _rows(n, share_rows=0):
    """单窗直飞行群：n 行裸价行，前 share_rows 行带 shareCarrier。"""
    rows = []
    for i in range(n):
        f = {"price": 1000 + i}
        if i < share_rows:
            f["shareCarrier"] = "X%d" % i
        rows.append(f)
    return rows


def _rec(plat, fc, tc, dd, rows):
    return [_NS(platform=plat, from_city=fc, to_city=tc,
                depart_date=dd, extra=json.dumps(rows))]


SHARE_HIT = "shareCarrier 命中 0"


def test_multi_window_same_day_each_fires_once(monkeypatch, tmp_path):
    """同字段多窗同日断供各自首鸣：窗 B 不得被窗 A 的「今日已报」
    短路吞掉（共享平键的遮蔽缺陷窗键版根治钉）。"""
    lg = _iso(monkeypatch, tmp_path)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 20)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-17", _rows(20, 20)), lg)
    assert lg.seen == []
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 0)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-17", _rows(20, 0)), lg)
    hits = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert len(hits) == 2, lg.seen
    assert ("tuniu", "share", "SHA", "SGN", "2026-11-16") in _m._SENT_LAST
    assert ("tuniu", "share", "SHA", "SGN", "2026-11-17") in _m._SENT_LAST
    assert ("tuniu", "share") not in _m._SENT_LAST, \
        "字段哨留痕不得再落跨窗平键"


def test_never_supplied_interference_and_single_fire(monkeypatch, tmp_path):
    """窗 A 在燃 + 无源窗 B 穿插 + 窗 A 复扫：A 恰 1 鸣、B 零鸣、
    A 的窗键留痕原样（无源窗穿插互扰的窗键终态验收钉）。"""
    lg = _iso(monkeypatch, tmp_path)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 20)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 0)), lg)
    assert len([1 for lv, m in lg.seen if SHARE_HIT in m]) == 1
    akey = ("tuniu", "share", "SHA", "SGN", "2026-11-16")
    assert akey in _m._SENT_LAST
    _m._field_sentinel(
        _rec("tuniu", "SHA", "CNX", "2026-11-16", _rows(20, 0)), lg)
    assert akey in _m._SENT_LAST, "无源窗不得波及他窗留痕"
    assert not [m for lv, m in lg.seen if "CNX" in m], lg.seen
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 0)), lg)
    assert len([1 for lv, m in lg.seen if SHARE_HIT in m]) == 1, \
        "窗 A 复扫不得重鸣"


def test_streak_per_window(monkeypatch, tmp_path):
    """连日升级按窗独立累计：窗 A 已连续 2 日在燃第 3 日升 INFO，
    同字段窗 B 首鸣保持 WARNING（共享平键下两窗共用一个计数）。"""
    lg = _iso(monkeypatch, tmp_path)
    import datetime as _dt
    yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    akey = ("tuniu", "share", "SHA", "SGN", "2026-11-16")
    bkey = ("tuniu", "share", "SHA", "SGN", "2026-11-17")
    _m._SENT_LAST[akey] = yest
    _m._SENT_CNT[akey] = 2
    _m._SENT_SUPPLIED[akey] = yest
    _m._SENT_SUPPLIED[bkey] = yest
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 0)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-17", _rows(20, 0)), lg)
    kinds = {k for k, _ in lg.seen}
    assert "I" in kinds and "W" in kinds, lg.seen
    a_msgs = [m for lv, m in lg.seen if "连续3日" in m]
    assert a_msgs and "2026-11-16" in a_msgs[0], lg.seen
    assert _m._SENT_CNT[akey] == 3 and _m._SENT_CNT[bkey] == 1


def test_message_carries_window_identity_and_health_parses(
        monkeypatch, tmp_path):
    """告警词面自带窗辨识（读者不复算即知哪窗断供），且 health 时间线
    正则对新词面照常收录（日志面消费端同轮协议）。"""
    lg = _iso(monkeypatch, tmp_path)
    akey = ("tuniu", "share", "SHA", "SGN", "2026-11-16")
    _m._SENT_SUPPLIED[akey] = "2026-10-01"
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", "2026-11-16", _rows(20, 0)), lg)
    hits = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert hits and "窗 SHA→SGN 2026-11-16" in hits[0], lg.seen
    # _L 捕获的模板串已含「[解析哨兵] 」前缀，health 正则按生产日志
    # 行形态直接匹配
    mm = _health._SENT.match(hits[0])
    assert mm and mm.group(1) == "tuniu", hits[0]


def test_state_roundtrip_mixed_key_shapes(monkeypatch, tmp_path):
    """状态文件混形往返：5 元窗键留痕[日期,连击]、平键行为哨留痕、
    supplied 族、domzero 族同文件互不串形。"""
    _iso(monkeypatch, tmp_path)
    akey = ("tuniu", "share", "SHA", "SGN", "2026-11-16")
    _m._SENT_LAST[akey] = "2026-10-18"
    _m._SENT_CNT[akey] = 4
    _m._SENT_LAST[("tuniu", "noDet")] = "2026-10-18"
    _m._SENT_CNT[("tuniu", "noDet")] = 2
    _m._SENT_SUPPLIED[("qunar", "meal", "HAK", "SHA", "2027-02-13")] = \
        "2026-10-18"
    _m._DOMZERO_SEEN[("tuniu", "dom")] = True
    _m._sent_save()
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    _m._DOMZERO_SEEN.clear()
    _m._sent_load()
    assert _m._SENT_LAST[akey] == "2026-10-18"
    assert _m._SENT_CNT[akey] == 4
    assert _m._SENT_LAST[("tuniu", "noDet")] == "2026-10-18"
    assert _m._SENT_CNT[("tuniu", "noDet")] == 2
    assert _m._SENT_SUPPLIED[
        ("qunar", "meal", "HAK", "SHA", "2027-02-13")] == "2026-10-18"
    assert _m._DOMZERO_SEEN[("tuniu", "dom")] is True


def test_trans_rowtype_sentinel_window_keyed(monkeypatch, tmp_path):
    """行型断供哨（trans）同族窗键控：两窗各有直飞满量+中转零行、
    各有历史供给 → 各自首鸣，词面各带本窗辨识。"""
    lg = _iso(monkeypatch, tmp_path)
    direct = [{"price": 1000 + i} for i in range(22)]
    for dd in ("2026-11-16", "2026-11-17"):
        t = dict(direct[0])
        t["transCity"] = "西安"
        t["layover"] = 90
        _m._field_sentinel(
            _rec("tongcheng", "URC", "SHA", dd, direct + [t]), lg)
    assert lg.seen == []
    for dd in ("2026-11-16", "2026-11-17"):
        _m._field_sentinel(
            _rec("tongcheng", "URC", "SHA", dd, direct), lg)
    hits = [m for lv, m in lg.seen if "中转零行" in m]
    assert len(hits) == 2, lg.seen
    assert any("2026-11-16" in m for m in hits)
    assert any("2026-11-17" in m for m in hits)


def test_behavior_sentinels_keep_flat_keys(monkeypatch, tmp_path):
    """行为型哨（跨窗聚合量）保持平键：noDet 的留痕/连击仍落
    (plat,fld)，不得被窗键控波及。"""
    lg = _iso(monkeypatch, tmp_path)
    recs = [_NS(platform="tuniu", from_city="SHA", to_city="HAK",
                depart_date="2027-01-29", extra=""),
            _NS(platform="tuniu", from_city="SHA", to_city="HAK",
                depart_date="2027-01-30", extra="")]
    _m._field_sentinel(recs, lg)
    assert any("明细 0 行" in m for lv, m in lg.seen), lg.seen
    assert ("tuniu", "noDet") in _m._SENT_LAST
    assert ("tuniu", "noDet", "SHA", "HAK", "2027-01-29") \
        not in _m._SENT_LAST


def test_retire_pops_window_key_family(monkeypatch, tmp_path):
    """死键退役摘除窗键族留痕：5 元窗键与旧平键一并清（观测面豁免键
    的留痕悬挂防复发）。"""
    _iso(monkeypatch, tmp_path)
    _m._SENT_LAST[("ctrip", "page", "URC", "SHA", "2027-01-29")] = \
        "2026-10-18"
    _m._SENT_CNT[("ctrip", "page", "URC", "SHA", "2027-01-29")] = 2
    rows = [{"price": 1000 + i, "plane": "空客A320", "cabin": "经济舱",
             "meal": "有餐食", "prate": 90, "discount": "4.5折",
             "depTerminal": "T2", "arrTerminal": "T1",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(12)]
    _m._field_sentinel(
        [_NS(platform="ctrip", from_city="URC", to_city="SHA",
             depart_date="2027-01-29", extra=json.dumps(rows))], _L())
    assert ("ctrip", "page", "URC", "SHA", "2027-01-29") \
        not in _m._SENT_LAST, _m._SENT_LAST


def test_stale_window_marks_swept(monkeypatch, tmp_path):
    """过期窗键留痕 sweep（r336 Soldier m3 卫生债随迁）：键内嵌出发
    日期早于今天的 _SENT_LAST/_SENT_CNT 留痕永不再命中（窗已过期
    跳采），长跑月级缓慢泄漏——每轮 _field_sentinel 尾部清理；平键
    （行为型哨/zrow/qsup）与当期窗键不在清理域；_SENT_SUPPLIED 是
    r334 案③持久化供给基线（化石窗由「未过期窗」枚举语义处置，
    LESSONS 卅二§1），不在清理域。"""
    lg = _iso(monkeypatch, tmp_path)
    stale = ("ctrip", "page", "URC", "SHA", "2020-01-01")
    live = ("qunar", "page", "XXX", "YYY", "2099-01-01")   # 本轮不扫的航线（防 never-supplied 摘除分支干扰断言）
    _m._SENT_LAST[stale] = "2026-10-18"
    _m._SENT_CNT[stale] = 3
    _m._SENT_LAST[live] = "2026-10-19"
    _m._SENT_CNT[live] = 1
    _m._SENT_LAST[("ctrip", "rowfall")] = "2026-10-19"   # 平键
    _m._SENT_SUPPLIED[("ctrip", "page", "URC", "SHA", "2020-01-01")] = 1
    rows = [{"price": 1000 + i, "plane": "空客A320", "cabin": "经济舱",
             "meal": "有餐食", "prate": 90, "discount": "4.5折",
             "depTerminal": "T2", "arrTerminal": "T1",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(12)]
    _m._field_sentinel(
        [_NS(platform="ctrip", from_city="URC", to_city="SHA",
             depart_date="2099-01-01", extra=json.dumps(rows))], _L())
    assert stale not in _m._SENT_LAST, "过期窗留痕未清"
    assert stale not in _m._SENT_CNT
    assert live in _m._SENT_LAST, "当期窗留痕误清"
    assert ("ctrip", "rowfall") in _m._SENT_LAST, "平键误清"
    assert _m._SENT_SUPPLIED[("ctrip", "page", "URC", "SHA",
                              "2020-01-01")] == 1, "供给基线误清"
