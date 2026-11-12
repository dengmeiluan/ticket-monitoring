# -*- coding: utf-8 -*-
"""r381: 干预后一致性（intervention consistency）。

核心命题：**干预成功 ≠ 状态已恢复**。如果自检/补采成功了却不清熔断、
不刷 TTL、不落账，用户会看到"自检 ✓N 条"和"仍在冷却/劣化"同时出现，
并且重启后完全无法追溯。这组测试钉住这条链。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


class _Store:
    def __init__(self, path):
        self.db_path = path
        self.paths = []
        self.saved = []
        self.ivs = []

    def latest_prices(self, *a, **k):
        return []

    def path_stats(self, *a, **k):
        return {}

    def save_fetch_path(self, *a, **k):
        self.paths.append(k)
        return 1

    def save_many(self, rows):
        self.saved.extend(list(rows))

    def save_intervention(self, *a, **k):
        self.ivs.append((a, k))

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass

    def purge(self, *a, **k):
        return 0


class _Crawler:
    name = "qunar"
    use_mobile = True
    warmup_url = "https://touch.qunar.com/h5/flight/"
    warmup_cookie_ok = True
    warmup_cookies = ["QN1"]
    RISK_COOKIES = ("QN1",)
    last_busy = False
    retry_after_s = 0
    last_block_url = ""
    last_block_api = ""
    last_scene = {}
    last_query = ("SHA", "PEK", "2027-06-01")
    paths = []
    rows = 2

    def __init__(self, cfg, logger):
        self.logger = logger

    def warmup(self, headless=True):
        return True

    def safe_fetch(self, fc, tc, dates, ret_date=""):
        from core.models import FlightPrice
        self.paths = [{"path": "H5", "status": "ok", "rows": self.rows,
                       "mobile": True}]
        return [FlightPrice(platform=self.name, from_city=fc, to_city=tc,
                            depart_date=dates[0], price=900.0)] if self.rows \
            else []


def _job(tmp_path, monkeypatch, crawler=None):
    monkeypatch.setattr(M, "REGISTRY",
                        {"qunar": crawler or _Crawler})
    cfg = {"schedule": {"scan_quiet_start": "", "scan_quiet_end": ""},
           "crawler": {"warmup": {"enabled": True,
                                  "platforms": ["qunar"]}},
           "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["qunar"], "notifier": {},
                      "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "PEK", "to_name": "北京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 900}]}]}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    st = _Store(str(tmp_path / "p.db"))
    M.make_sweep_job(cfg, rt, logging.getLogger("r381"),
                     st, lambda *a, **k: {})
    return rt, st


def test_successful_probe_clears_cooldown_and_refreshes_ttl(tmp_path,
                                                            monkeypatch):
    rt, st = _job(tmp_path, monkeypatch)
    pac = rt["pacing"]
    # 先制造"冷却中"的现场
    pac.trip("qunar", "ip")
    assert pac.snapshot()["channels"]["qunar"]["state"] == "cooldown"
    out = rt["probe_channel"]("qunar", scope="dom")
    assert out["ok"] is True and out["rows"] >= 1
    ch = pac.snapshot()["channels"]["qunar"]
    assert ch["state"] == "ok", "自检成功后必须解除冷却"
    assert ch["strikes"] == 0
    # TTL 应被刷新：同一 key 立刻 plan 应落在 skip（刚采过）
    tier, _why = pac.plan_query("qunar",
                                ("SHA", "PEK", out["query"][2]), 900)
    assert tier == "skip", "自检出数必须刷新该键 TTL"
    # 干预账必须落一条
    assert any(a and a[1] == "probe" for a, _k in st.ivs)


def test_failed_probe_keeps_cooldown_visible(tmp_path, monkeypatch):
    class _Fail(_Crawler):
        rows = 0

        def safe_fetch(self, fc, tc, dates, ret_date=""):
            self.paths = [{"path": "H5", "status": "blocked", "rows": 0,
                           "mobile": True, "detail": "验证页"}]
            return []

    rt, st = _job(tmp_path, monkeypatch, crawler=_Fail)
    pac = rt["pacing"]
    pac.trip("qunar", "ip")
    out = rt["probe_channel"]("qunar", scope="dom")
    assert out["ok"] is True and out["rows"] == 0
    # 没出数不得解除冷却（否则会把"还没修好"显示成"已恢复"）
    assert pac.snapshot()["channels"]["qunar"]["state"] == "cooldown"


def test_refill_success_clears_breaker_and_ttl(tmp_path, monkeypatch):
    """补采出数也必须复位熔断并刷新 TTL（否则补采成功仍显示冷却）。"""
    rt, st = _job(tmp_path, monkeypatch)
    pac = rt["pacing"]
    pac.trip("qunar", "ip")
    rt["failed"] = {"qunar": {("SHA", "PEK", "2027-06-01")}}
    out = rt["refetch_failed"]("qunar")
    assert out["rows"] >= 1, out
    assert pac.snapshot()["channels"]["qunar"]["state"] == "ok"
    assert pac.plan_query("qunar", ("SHA", "PEK", "2027-06-01"),
                          900)[0] == "skip"


def test_intervention_ledger_roundtrip(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_intervention("qunar", "probe", ok=True, rows=65, scope="dom",
                         note="H5 ok×65", ms=7700)
    st.save_intervention("qunar", "verify", ok=False, rows=0,
                         note="验证未通过", ms=12000)
    st.save_intervention("ctrip", "warmup", ok=True, note="cookies=cticket")
    rows = st.interventions("qunar", 10)
    assert [r["action"] for r in rows] == ["verify", "probe"]   # 倒序
    assert rows[1]["rows"] == 65 and rows[1]["ok"] == 1
    assert rows[0]["ok"] == 0
    allrows = st.interventions("", 10)
    assert len(allrows) == 3
    # 重启等价：新连接仍可读（持久化而非内存）
    st2 = PriceStorage(str(tmp_path / "prices.db"))
    assert len(st2.interventions("", 10)) == 3


def test_probe_persists_attempt_id_and_evidence(tmp_path, monkeypatch):
    rt, st = _job(tmp_path, monkeypatch)
    rt["probe_channel"]("qunar", scope="dom")
    assert st.paths, "自检路径必须写账"
    assert any(k.get("evidence_level") == "probe" for k in st.paths)
    assert any(str(k.get("attempt_id", "")).startswith("probe-")
               for k in st.paths)


def test_trace_api_exposes_interventions():
    import inspect
    import webui
    src = inspect.getsource(webui)
    assert "interventions" in src
    assert "干预记录" in src


def test_hysteresis_requires_consecutive_success():
    """一次成功不清 strikes；连续两次才复位（避免冷却/恢复横跳）。"""
    from core.pacing import Pacing
    p = Pacing({})
    p.trip("qunar", "ip")
    assert p.snapshot()["channels"]["qunar"]["strikes"] == 1
    p.note_ok("qunar")
    ch = p.snapshot()["channels"]["qunar"]
    assert ch["strikes"] == 1, "单次成功不得清零"
    assert ch["ok_streak"] == 1
    p.note_ok("qunar")
    ch2 = p.snapshot()["channels"]["qunar"]
    assert ch2["strikes"] == 0 and ch2["state"] == "ok"
    assert ch2["ok_streak"] == 2


def test_success_clears_soft_warmup_flag_immediately():
    from core.pacing import Pacing
    p = Pacing({})
    p.observe("qunar", ["soft_reject"], "")
    assert p.snapshot()["channels"]["qunar"]["needs_warmup"] is True
    p.note_ok("qunar", need=2)
    ch = p.snapshot()["channels"]["qunar"]
    assert ch["needs_warmup"] is False
    assert ch["reason"] == ""


def test_degradation_needs_valid_samples():
    """4 次售罄 + 1 次拦截：有效样本不足，不判路径劣化。"""
    from core.pacing import advise
    paths = {"H5": {"attempts": 5, "ok": 0, "empty": 4, "blocked": 1,
                    "rate": 0.0, "rate_excl_empty": 0.0}}
    a = advise("qunar", {"state": "ok"}, paths)
    assert a["state"] != "path_degraded"
    # 有效样本够时仍要判
    paths2 = {"H5": {"attempts": 8, "ok": 0, "empty": 1, "blocked": 7,
                     "rate": 0.0, "rate_excl_empty": 0.0}}
    b = advise("qunar", {"state": "ok"}, paths2)
    assert b["state"] == "path_degraded"


def test_manual_reset_verifies_and_reports_truth():
    """解除熔断不能直接记成功：必须带真实单查结果。

    读文件而不是 inspect.getsource(webui._Handler._do_POST)：全套运行时
    其它测试会替换/包装 `_Handler`，取到的源码里可能没有 reset 分支，
    `split(...)[1]` 直接 IndexError（r379 已记录同一坑）。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "webui.py"), encoding="utf-8").read()
    # 切片要盖住整个分支（r480 加了并发守卫后 3000 字符不够，会把
    # 写账那段挤出窗口造成假红）。用下一个 elif 作终止符。
    block = src.split('self.path == "/api/pacing/reset"', 1)[1]
    block = block.split('elif self.path ==', 1)[0]
    assert "probe_cb" in block, "解除后必须触发单查"
    assert 'save_intervention(' in block
    assert '"reset", ok=_ok' in block, "干预账的 ok 必须来自探测结果"
    assert '"probe": _probe' in block, "响应里要带回探测结果"


def test_round_coverage_counts_channel_level_success():
    """一轮成功率 = 有数渠道 / 实发渠道，与路径行数无关。"""
    from core.pacing import Pacing
    p = Pacing({})
    p.begin_round("19:00:00")
    for c in ("ctrip", "qunar", "tunghu"):
        p.note_sent(c)
    p.note_result("ctrip", ok=True)
    p.note_result("qunar", ok=False, soft=True)
    cov = p.snapshot()["coverage"]
    assert cov["ok"] == ["ctrip"]
    assert cov["soft"] == ["qunar"]
    assert cov["sent"] == ["ctrip", "qunar", "tunghu"]
    assert cov["ratio"] == round(1 / 3, 3)


def test_panel_shows_coverage_row():
    import inspect
    import webui
    src = inspect.getsource(webui)
    assert "本轮覆盖率" in src


def test_intervention_effect_before_after(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "blocked",
                       attempt_id="a1")
    st.save_intervention("qunar", "verify", ok=True, rows=10)
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "ok",
                       attempt_id="a2")
    eff = st.intervention_effect("qunar")
    assert eff["has"] is True and eff["action"] == "verify"
    assert eff["after"] is not None and eff["after_n"] >= 1
    # 无干预渠道如实返回 has=False
    assert st.intervention_effect("ctrip")["has"] is False


def test_effect_sql_bindings_are_consistent(tmp_path):
    """回归：曾因占位符数量不符抛 ProgrammingError。"""
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_intervention("qunar", "reset", ok=False)
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "ok",
                       attempt_id="z1")
    eff = st.intervention_effect("qunar")
    assert eff["ok"] is True and "before" in eff and "after" in eff


def test_queries_are_date_first():
    """临期日期必须先采：排序键第一维是出发日。"""
    import inspect
    import main
    src = inspect.getsource(main.make_sweep_job)
    assert 'sorted(registry, key=lambda k: (str(k[2])' in src


def test_concurrency_cap_is_configurable():
    from core.pacing import parse_pacing
    assert parse_pacing({"crawler": {"max_concurrency": 2}})[
        "max_concurrency"] == 2
    assert parse_pacing({"crawler": {"max_concurrency": 99}})[
        "max_concurrency"] == 5
    assert parse_pacing({})["max_concurrency"] == 0


def test_near_days_configurable():
    from core.pacing import Pacing
    now = [1_700_000_000.0]
    p = Pacing({"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                            "near_days": 7}}, clock=lambda: now[0])
    key = ("qunar", "SHA", "PEK", "2027-06-01")
    p.note_fetch("qunar", key, 900, True)
    now[0] += 16 * 60
    assert p.plan_query("qunar", key, 900, days_ahead=6)[0] == "fast"


def test_effect_needs_three_samples_to_claim_recovery():
    from core.pacing import effect_verdict
    # 1 个样本：只能说"待复验"，不能说"已恢复"
    s, hint, sev = effect_verdict({"has": True, "action": "probe",
                                   "before": 0.09, "after": 1.0,
                                   "after_n": 1})
    assert s == "provisional" and sev == "wait"
    # 3 个样本且 >=70%：可以判有效
    s2, _h, sev2 = effect_verdict({"has": True, "action": "probe",
                                   "before": 0.09, "after": 0.8,
                                   "after_n": 3})
    assert s2 in ("improved", "recovered")


def test_effect_pending_when_no_after_samples():
    from core.pacing import effect_verdict
    s, _h, sev = effect_verdict({"has": True, "action": "verify",
                                 "before": 0.2, "after": None,
                                 "after_n": 0})
    assert s == "pending" and sev == "wait"


def test_advice_no_longer_contradicts_effect():
    """干预已见效时，advice 不得仍报 path_degraded。"""
    import inspect
    import webui
    src = inspect.getsource(webui)
    assert '"recovering"' in src
    assert "旧 24h 样本仍含" in src


def test_effect_trend_and_regression(tmp_path):
    """干预后先好后坏 = 一致性不成立，必须判 regressed。"""
    import sqlite3
    from core.pacing import effect_verdict
    st = PriceStorage(str(tmp_path / "p.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "blocked",
                       attempt_id="old1")
    st.save_intervention("qunar", "verify", ok=True, rows=3)
    iv_at = st.interventions("qunar", 1)[0]["at"]
    # 干预后：一个 30min 窗口全 ok，另一个窗口全 blocked
    with st._conn() as c:
        for i in range(3):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status,rows,attempt_id) "
                "VALUES (datetime(?, '+5 minutes'),'qunar','SHA','PEK',"
                "'2027-06-01','H5','ok',1,?)", (iv_at, "t%d" % i))
        for i in range(3):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status,rows,attempt_id) "
                "VALUES (datetime(?, '+65 minutes'),'qunar','SHA','PEK',"
                "'2027-06-01','H5','blocked',0,?)", (iv_at, "r%d" % i))
    eff = st.intervention_effect("qunar")
    assert len(eff["trend"]) >= 2
    assert eff["regressed"] is True
    assert effect_verdict(eff)[0] == "regressed"


def test_degradation_is_reported_per_scope():
    """国内正常、国际被登录墙拦住时，提示必须点名"国际"，不能笼统判整家。"""
    from core.pacing import advise
    node = {
        "attempts": 20, "ok": 10, "empty": 0,
        "paths": {"H5": {"attempts": 20, "ok": 10, "empty": 0,
                         "rate": 0.5, "rate_excl_empty": 0.5}},
        "query_attempts": 20, "query_ok": 10, "query_rate": 0.5,
        "scopes": {
            "dom": {"paths": {"H5": {"attempts": 10, "ok": 10, "empty": 0,
                                     "rate": 1.0,
                                     "rate_excl_empty": 1.0}}},
            "intl": {"paths": {"H5": {"attempts": 10, "ok": 0, "empty": 0,
                                      "rate": 0.0,
                                      "rate_excl_empty": 0.0}}},
        },
    }
    a = advise("qunar", {"state": "ok"}, node["paths"], node=node)
    assert a["state"] == "path_degraded"
    assert "国际" in a["hint"] and "国内" not in a["hint"]
