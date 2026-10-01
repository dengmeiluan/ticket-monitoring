# -*- coding: utf-8 -*-
"""r252 D-1：单件行属性四键（avgDelay/cancelRate/bridgeRate/planeAge）
恒 0 检查分母改直飞行群。

背景（2026-10-06 20:52 实录）：这四字段只挂直飞行——中转行是两段
拼接的组合体，单件行属性无单一真值可填（结构性无源）。直飞行群
7 天出勤 ~100%、中转行群恒 0%；当日 19:33 直飞售罄清空后行全变
中转（20 条），恒 0 检查的全行分母（n≥20）撞上分子恒 0 即鸣
「键名失效」假火——解析链健康（dump 与 DB 双证）却被错误归因。

修法：分子分母同口径切到直飞行群（LESSONS 二十五§7），分母
direct_n、门槛 10（同 cabin/meal/prate 直飞行群比率观测族先例）；
直飞行群在场时键死照报（守卫能力不丢）。"""
import json

from types import SimpleNamespace as _NS

import main as _m


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, *a, **k):
        self.seen.append(a)

    def info(self, *a, **k):
        self.seen.append(a)


def _setup(monkeypatch, tmp_path):
    """哨兵状态隔离三件套（照抄 test_field_sentinel_warns_on_dead_field
    并补 _SENT_CNT——连续命中计数不清会让跨用例首日判定漂移）。"""
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()


def _run(logger, plat, rows):
    _m._field_sentinel([_NS(platform=plat, extra=json.dumps(rows))], logger)


def _direct_rows(n, with_vals):
    """直飞行群夹具：with_vals=True 带四键真值（健康形态）；
    其余观测键（直飞行群比率族/机场码/航站楼）带值防旁哨噪音，
    让目标四键是行间唯一差异。"""
    rows = []
    for _ in range(n):
        r = {"price": 1000, "cabin": "经济舱", "meal": "无餐食",
             "prate": "97", "plane": "空客321(中)", "planeSize": "中型机",
             "discount": "4.5折", "depTerminal": "T2",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
        if with_vals:
            r.update({"avgDelay": 21, "planeAge": "6.3",
                      "cancelRate": 10, "bridgeRate": 80})
        rows.append(r)
    return rows


def _trans_rows(n):
    """中转行群夹具：结构性无四键（生产真实形态）；全行观测键
    （机场码/航站楼）与中转观测键（svc/tterm/layover）带值防旁哨。"""
    return [{"price": 1000, "transCity": "西安", "layover": 90,
             "depTerminal": "T2", "transferService": "免费改签",
             "transTerminal": "咸阳T3",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for _ in range(n)]


def test_trans_only_round_no_false_alarm(monkeypatch, tmp_path):
    """全中转轮（直飞售罄夜形态）不鸣：分母=direct_n=0<10 不观测。
    旧代码全行分母 n=20≥20 撞分子恒 0 → 四键齐鸣「键名失效」假火。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _trans_rows(20))
    assert lg.seen == [], lg.seen


def test_direct_round_dead_keys_still_warn(monkeypatch, tmp_path):
    """直飞行群在场且四键全灭照报：键名失效检测能力不丢
    （旧代码 n=10<20 不报——新门槛 direct_n≥10 与比率观测族对齐）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(10, with_vals=False))
    warned = {a[2] for a in lg.seen}   # (plat, k, msg) 形态的第 3 段
    assert len(lg.seen) == 4, lg.seen
    for kw in ("avgDelay", "cancelRate", "bridgeRate", "planeAge"):
        assert any(kw in m for m in warned), (kw, lg.seen)


def test_mixed_round_direct_ok_no_alarm(monkeypatch, tmp_path):
    """混合轮（直飞满勤 + 中转在场）不鸣：中转行群结构性恒 0
    不再稀释判定，直飞行群健康即哨静默。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(10, with_vals=True) + _trans_rows(20))
    assert lg.seen == [], lg.seen


def test_below_floor_round_not_observed(monkeypatch, tmp_path):
    """直飞行群 <10 样本不足整轮不观测（行群观测的样本就是行群自身）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(9, with_vals=False))
    assert lg.seen == [], lg.seen


def test_digest_pool_isolated_from_prod_db(monkeypatch):
    """合成池与生产 DB 隔离（conftest autouse _isolate_recent_flights
    在位验证）：storage=None 时补位链读默认 data/prices.db 近 6h
    真实行——v15133 tie 组钉曾随生产数据面漂移（夜间 tongcheng
    高价中转行抬锚，合成 1600 tie 组被孤低价守卫双杀）白天绿入夜红。
    根治后池=夹具行：无 _stale_h 补位行混入。"""
    import core.alerter as am
    import datetime as _dt
    _today = _dt.date.today().isoformat()   # 动态日期：补位按 (航线,depart_date) 查近 6h——硬编码日期过午夜后钉变零回归钉
    rows = [dict({"price": 1600, "name": "东航MU5700", "code": "MU5700",
                  "depTime": "10:00", "arrTime": "15:00",
                  "depDate": _today, "arrDate": _today,
                  "transCity": "兰州", "totalDuration": "9时30分",
                  "layoverM": 120}, _platform=p)
            for p in ("fliggy", "ctrip")]

    class _NS:
        pass

    rec = _NS()
    rec.platform, rec.extra, rec.depart_date = "fliggy", json.dumps(
        [rows[0]], ensure_ascii=False), _today
    rec2 = _NS()
    rec2.platform, rec2.extra, rec2.depart_date = "ctrip", json.dumps(
        [rows[1]], ensure_ascii=False), _today
    rec.from_city = rec2.from_city = "URC"
    rec.to_city = rec2.to_city = "SHA"
    rec.price = rec2.price = 1600

    a = am.Alerter(_L(), notifier=None, storage=None, digest=True, user="t")
    route = am.Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                     to_name="上海", dates=[_today],
                     alert_direct=0, alert_transfer=1700,
                     transfer_arrival_max="23:59",
                     transfer_baggage="direct")
    secs = a._build_sections(route, [rec, rec2])
    pool = [f for s in secs for f in (s.get("top_direct") or [])
            + (s.get("top_transfer") or [])]
    assert all(not f.get("_stale_h") for f in pool), pool
    assert all(f.get("price") == 1600 for f in pool), pool
