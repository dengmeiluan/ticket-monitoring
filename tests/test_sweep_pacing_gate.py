# -*- coding: utf-8 -*-
"""主循环接线：静默窗必须在「写轮次标记 / 建注册表 / 发请求」之前短路。

这里只测可在无浏览器、无网络下稳定复现的两条：
  1. 静默窗内 force=False → 立即返回，且不落 last_scan.json
  2. 零用户 / 零查询的空轮 → 正常收尾（新加的节流账本不炸）
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402


class _Storage:
    """只提供 _sweep_inner 开头用到的 db_path（静默短路走不到写库）。"""

    def __init__(self, db_path):
        self.db_path = db_path


def _job(tmp_path, schedule):
    cfg = {"schedule": schedule, "crawler": {}, "output": {},
           "users": [], "web": {}}
    rt = {"users": [], "alerters": [], "cfg": cfg}
    st = _Storage(str(tmp_path / "prices.db"))
    job = M.make_sweep_job(cfg, rt, logging.getLogger("pacing-wire"),
                           st, lambda *a, **k: {})
    return job, rt, st


def test_quiet_window_short_circuits_before_marker(tmp_path, monkeypatch):
    """静默窗内 force=False 必须短路；force=True 必须绕过。

    注意：原实现把窗口设成 00:00–23:59 直接依赖**真实时钟**，而
    `in_window` 把 23:59–00:00 这一分钟视为窗外——每天午夜跑这套会
    假失败（实测 00:04 跑全量时红、隔离跑绿）。这里把 Pacing 的 clock
    钉到固定时刻，判据只看窗口逻辑本身。
    """
    import time as _t
    fixed = _t.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))
    job, rt, st = _job(tmp_path, {"scan_quiet_start": "00:00",
                                  "scan_quiet_end": "23:59"})
    # clock 是构造参数存成的实例属性，直接替换这一个实例的时钟
    rt["pacing"]._clock = lambda: fixed
    assert rt["pacing"].quiet_now() is True
    job()                                   # 定时触发：force=False
    marker = tmp_path / "last_scan.json"
    assert not marker.exists(), "静默轮不得写轮次标记（会被当成空轮）"

    job(force=True)                         # 人工「立即扫描」：强制放行
    assert marker.exists(), "force=True 必须绕过静默窗并留下轮次标记"


def test_empty_round_finishes_with_pacing_ledger(tmp_path):
    job, rt, _ = _job(tmp_path, {"scan_quiet_start": "", "scan_quiet_end": ""})
    assert rt["pacing"].quiet_now() is False
    job()                                   # 零用户 / 零查询：应正常收尾
    snap = rt["pacing"].snapshot()
    assert snap["last_round"]["fast"] == 0
    assert snap["last_round"]["skip"] == 0


# ---------- 整轮链路：TTL 真的把第二次请求挡在门外 ----------
class _FakeCrawler:
    name = "qunar"
    calls = 0

    def __init__(self, cfg, logger):
        self.logger = logger
        self.paths = []
        self.threshold_hints = {}
        self.last_busy = False

    def safe_fetch(self, fc, tc, dates, ret_date=""):
        type(self).calls += 1
        from core.models import FlightPrice
        self.paths = [{"path": "H5", "status": "ok", "rows": 1,
                       "date": dates[0], "detail": "1 条"}]
        return [FlightPrice(platform=self.name, from_city=fc, to_city=tc,
                            depart_date=dates[0], price=2000.0)]


class _Store:
    def __init__(self, db_path):
        self.db_path = db_path
        self.saved = []
        self.paths = []

    def save_fetch_path(self, *a, **k):
        self.paths.append(a)
        return 1

    def save_many(self, rows):
        self.saved.extend(list(rows))

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass


class _Alerter:
    round_charts = {}
    notifier = None

    def check_multi(self, pairs):
        self.pairs = pairs


def test_second_round_is_skipped_by_ttl(tmp_path, monkeypatch):
    _FakeCrawler.calls = 0
    monkeypatch.setitem(M.REGISTRY, "qunar", _FakeCrawler)
    cfg = {
        "users": [{
            "name": "u", "platforms": ["qunar"], "notifier": {},
            "schedule": {},
            "routes": [{"from": "SHA", "from_name": "上海", "to": "NRT",
                        "to_name": "东京", "dates": ["2027-06-01"],
                        "alert_direct": 2500}],
        }],
        "schedule": {"scan_quiet_start": "", "scan_quiet_end": "",
                     "fast_ttl_min": 15, "slow_ttl_min": 120,
                     "near_ratio": 0.15},
        "crawler": {"user_data_dir": str(tmp_path / "ud")},
        "output": {}, "web": {},
    }
    store = _Store(str(tmp_path / "prices.db"))
    rt = {"users": M.build_users(cfg), "alerters": [_Alerter()], "cfg": cfg}
    job = M.make_sweep_job(cfg, rt, logging.getLogger("pacing-wire"),
                           store, lambda *a, **k: {})
    job()
    assert _FakeCrawler.calls == 1, "首轮无基线必须真抓"
    assert len(store.saved) == 1
    job()                                   # 紧接着第二轮
    assert _FakeCrawler.calls == 1, "TTL 内不得再打站"
    assert rt["pacing"].snapshot()["last_round"]["skip"] == 1


# ---------- 渠道告警端到端：三轮零数据必须真推一条 ----------
class _EmptyCrawler:
    """只返回空：用来喂出「连续零数据」。"""
    name = "qunar"
    paths = []
    last_busy = False
    retry_after_s = 0
    warmup_url = ""
    last_block_url = ""
    last_query = ()
    last_scene = {}

    def __init__(self, cfg, logger):
        self.logger = logger

    def safe_fetch(self, fc, tc, dates, ret_date=""):
        return []


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp):
        self.sent.append((title, desp))


class _AlerterAlert:
    round_charts = {}
    notifier = None

    def check_multi(self, pairs):
        pass

    def _in_quiet(self):
        return False


class _Store2(_Storage):
    def path_stats(self, hours=24):
        return {}

    def save_many(self, rows):
        self.saved = list(rows)

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass


def test_channel_alert_fires_after_three_zero_rounds(tmp_path, monkeypatch):
    monkeypatch.setitem(M.REGISTRY, "qunar", _EmptyCrawler)
    notifier = _Notifier()
    alerter = _AlerterAlert()
    alerter.notifier = notifier
    cfg = {"schedule": {"scan_quiet_start": "", "scan_quiet_end": "",
                        "fast_ttl_min": 15, "slow_ttl_min": 120},
           "crawler": {}, "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["qunar"], "notifier": {},
                      "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "NRT", "to_name": "东京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 2500}]}]}
    rt = {"users": M.build_users(cfg), "alerters": [alerter], "cfg": cfg}
    st = _Store2(str(tmp_path / "prices.db"))
    job = M.make_sweep_job(cfg, rt, logging.getLogger("alert-wire"),
                           st, lambda *a, **k: {})
    job()
    assert rt["zero_streak"]["qunar"]["n"] == 1
    assert not notifier.sent, "第一轮零数据不该发（还没到阈值）"
    job()
    job()                                   # 连续三轮零数据
    assert rt["zero_streak"]["qunar"]["n"] == 3
    assert notifier.sent, "三轮零数据必须推送"
    title, desp = notifier.sent[-1]
    assert "去哪儿" in title and "3" in title
    assert "去验证" in desp                 # 文案带下一步
    job()                                   # 第四轮：仍在冷却窗口内
    assert len(notifier.sent) == 1, "6 小时冷却内不得重复推"


# ---------- 渠道自检：单查询跑完整链路并回报 ----------
class _ProbeCrawler:
    name = "qunar"
    paths = []
    warmup_url = "https://touch.qunar.com/h5/flight/"
    warmup_cookies = ["QN1"]
    last_block_url = ""
    last_scene = {}
    retry_after_s = 0
    last_query = ()

    def __init__(self, cfg, logger):
        self.logger = logger

    def warmup(self, headless=True):
        return True

    def safe_fetch(self, fc, tc, dates, ret_date=""):
        self.paths = [{"path": "H5", "status": "ok", "rows": 60,
                       "detail": "国际列表"}]
        return [object()]


def test_probe_channel_reports_rows_path_and_cookies(tmp_path, monkeypatch):
    # 整表替换：否则未注册渠道会真的去建 CtripCrawler 并联网
    monkeypatch.setattr(M, "REGISTRY", {"qunar": _ProbeCrawler})
    cfg = {"schedule": {}, "crawler": {}, "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["qunar"], "notifier": {},
                      "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "NRT", "to_name": "东京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 2500}]}]}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    st = _Store2(str(tmp_path / "prices.db"))
    M.make_sweep_job(cfg, rt, logging.getLogger("probe-wire"), st,
                     lambda *a, **k: {})
    out = rt["probe_channel"]("qunar")
    assert out["ok"] is True
    assert out["rows"] == 1
    assert out["paths"][0]["status"] == "ok" and out["paths"][0]["rows"] == 60
    assert out["cookies"] == ["QN1"]          # 预热 cookie 一起回报
    assert out["warmup"] is True
    assert out["query"] == ["SHA", "NRT", "2027-06-01"]
    assert out["scope"] == "intl"
    assert out["ms"] >= 0
    assert rt["probe_channel"]("ctrip")["ok"] is False   # 未注册渠道


def test_probe_channel_scope_selects_domestic_route(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "REGISTRY", {"qunar": _ProbeCrawler})
    cfg = {"schedule": {}, "crawler": {}, "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["qunar"], "notifier": {},
                      "schedule": {},
                      "routes": [
                          {"from": "SHA", "from_name": "上海",
                           "to": "NRT", "to_name": "东京",
                           "dates": ["2027-06-01"], "alert_direct": 2500},
                          {"from": "SHA", "from_name": "上海",
                           "to": "PEK", "to_name": "北京",
                           "dates": ["2027-06-02"], "alert_direct": 900},
                      ]}]}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    M.make_sweep_job(cfg, rt, logging.getLogger("probe-scope"),
                     _Store2(str(tmp_path / "p.db")), lambda *a, **k: {})
    out = rt["probe_channel"]("qunar", scope="dom")
    assert out["ok"] is True and out["scope"] == "dom"
    assert out["query"][:2] == ["SHA", "PEK"]
    # 没有国际航线时明确拒绝，而不是偷偷拿国内航线冒充
    cfg2 = dict(cfg)
    cfg2["users"] = [dict(cfg["users"][0], routes=[
        {"from": "SHA", "from_name": "上海", "to": "PEK",
         "to_name": "北京", "dates": ["2027-06-02"], "alert_direct": 900}])]
    rt2 = {"users": M.build_users(cfg2), "alerters": [], "cfg": cfg2}
    M.make_sweep_job(cfg2, rt2, logging.getLogger("probe-scope2"),
                     _Store2(str(tmp_path / "p2.db")), lambda *a, **k: {})
    bad = rt2["probe_channel"]("qunar", scope="intl")
    assert bad["ok"] is False and "没有国际航线" in bad["err"]



def test_probe_channel_rejects_concurrent(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "REGISTRY", {"qunar": _ProbeCrawler})
    cfg = {"schedule": {}, "crawler": {}, "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["qunar"], "notifier": {},
                      "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "NRT", "to_name": "东京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 2500}]}]}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    M.make_sweep_job(cfg, rt, logging.getLogger("probe-wire2"),
                     _Store2(str(tmp_path / "p.db")), lambda *a, **k: {})
    assert rt["probe_channel"]("qunar")["ok"] is True     # 第一次成功
    assert rt["probe_channel"]("qunar")["ok"] is True     # 串行，不互斥


def test_old_round_worker_does_not_mutate_new_round_state(tmp_path,
                                                          monkeypatch):
    """跨轮 worker：抓取过程中轮次翻页，旧结果不得 reset/记 TTL。"""
    calls = []

    class _LateCrawler:
        name = "qunar"
        paths = []
        last_busy = False
        retry_after_s = 0
        last_block_url = ""
        last_block_api = ""
        last_scene = {}

        def __init__(self, cfg, logger):
            self.logger = logger

        def safe_fetch(self, fc, tc, dates, ret_date=""):
            # 模拟：这条查询还在跑时，上一轮已结束、下一轮已开始
            rt["_round_gen"] = int(rt.get("_round_gen") or 0) + 1
            self.paths = [{"path": "H5", "status": "ok", "rows": 1,
                           "mobile": True}]
            from core.models import FlightPrice
            return [FlightPrice(platform=self.name, from_city=fc,
                                to_city=tc, depart_date=dates[0],
                                price=900.0)]

    monkeypatch.setitem(M.REGISTRY, "qunar", _LateCrawler)
    cfg = {"users": [{"name": "u", "platforms": ["qunar"],
                      "notifier": {}, "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "PEK", "to_name": "北京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 900}]}],
           "schedule": {"scan_quiet_start": "", "scan_quiet_end": "",
                        "fast_ttl_min": 15, "slow_ttl_min": 120},
           "crawler": {}, "output": {}, "web": {}}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    job = M.make_sweep_job(cfg, rt, logging.getLogger("gen-wire"),
                           _Store2(str(tmp_path / "p.db")),
                           lambda *a, **k: {})
    pac = rt["pacing"]
    pac.reset = lambda p: calls.append(("reset", p))
    pac.note_fetch = lambda *a, **k: calls.append(("note", a))
    job()
    assert calls == [], "旧轮 worker 不得 reset 或刷新新轮 TTL"


