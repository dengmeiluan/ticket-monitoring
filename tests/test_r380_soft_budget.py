# -*- coding: utf-8 -*-
"""r380: 软拒分层 / HTTP 状态入账 / 请求预算。

三个"看起来正常、实际判错"的点：
  1. 202 空体 / 444 关连接被记成 empty 或 error，于是既不预热也不重试；
  2. 路径账丢了 HTTP 状态，事后无法区分"真无票"与"软拒"；
  3. 面板只有计划数，没有"实发/主动未发/每分钟用量"，被限流时无法自证。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing, advise, classify_failure  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def test_soft_reject_is_its_own_kind():
    assert classify_failure(["soft_reject"], "") == "soft"
    assert classify_failure([], "HTTP 202 空体") == "soft"
    assert classify_failure([], "连接被 444 关闭") == "soft"
    # 真无票/解析失败仍是"不算拒绝"
    assert classify_failure(["empty"], "") == ""
    assert classify_failure(["error"], "解析失败") == ""


def test_soft_reject_does_not_trip_breaker_but_requests_warmup():
    p = Pacing({})
    kind, cd = p.observe("qunar", ["soft_reject"], "", retry_after=0)
    assert kind == "soft" and cd == 0
    ch = p.snapshot()["channels"]["qunar"]
    assert ch["state"] == "ok"          # 不冷却
    assert ch["strikes"] == 0           # 不计熔断次数
    assert ch["needs_warmup"] is True   # 但下一轮先预热
    a = advise("qunar", ch, {})
    assert a["state"] == "soft_reject"
    # 预热真的拿到风控 cookie 后才清标记
    p.note_warmup_ok("qunar")
    ch2 = p.snapshot()["channels"]["qunar"]
    assert ch2["needs_warmup"] is False
    assert ch2["reason"] == ""


def test_soft_reject_does_not_reset_needs_warmup_on_error_observe():
    p = Pacing({})
    p.observe("ctrip", ["soft_reject"], "")
    p.observe("ctrip", ["timeout"], "超时")     # 非拒绝类不应清标记
    assert p.snapshot()["channels"]["ctrip"]["needs_warmup"] is True


def test_budget_counts_sent_and_paced_per_channel():
    p = Pacing({})
    p.begin_round("10:00:00")
    p.note_plan("qunar", ("SHA", "PEK", "2027-06-01"), "fast", "x")
    p.note_sent("qunar")
    p.note_sent("qunar")
    p.note_paced("ctrip", "budget")
    p.note_plan("ctrip", ("SHA", "PEK", "2027-06-01"), "skip", "TTL")
    rnd = p.snapshot()["last_round"]
    assert rnd["sent"] == 2 and rnd["paced"] == 1
    assert rnd["sent_by"] == {"qunar": 2}
    assert rnd["paced_by"] == {"ctrip": 1}
    assert rnd["fast"] == 1 and rnd["skip"] == 1


def test_http_status_persisted_and_soft_bucketed(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                       "soft_reject", rows=0, note="HTTP 202 空体",
                       attempt_id="a1", http_status=202)
    rows = st.recent_paths("qunar", 5)
    assert rows[0]["http_status"] == 202
    assert rows[0]["path_status"] == "soft_reject"
    node = st.path_stats(24)["qunar"]
    assert node["paths"]["H5"]["soft"] == 1
    assert node["paths"]["H5"]["empty"] == 0
    assert node["paths"]["H5"]["error"] == 0
    # 软拒不算成功，也不算硬失败
    assert node["query_attempts"] == 1 and node["query_ok"] == 0


def test_soft_reject_path_does_not_force_query_retry_flag():
    """软拒轮不应把查询塞进 failed 补采集合（下一轮靠预热自愈）。"""
    import inspect
    import main
    src = inspect.getsource(main.make_sweep_job)
    assert "_soft = any(x.get(\"status\") == \"soft_reject\" for x in paths)" in src
    assert "if pac is not None and not prices and not _soft:" in src


def test_panel_shows_budget_and_soft_reject_labels():
    import inspect
    import webui
    src = inspect.getsource(webui)
    for needle in ("软拒待预热", "实发 ", "主动未发", "近一分钟用量"):
        assert needle in src, needle


def test_soft_reject_forces_warmup_even_if_not_listed(tmp_path, monkeypatch):
    """软拒渠道即使不在 warmup_platforms 里，下一轮也必须先预热。"""
    import main as M

    warmed = []

    class C:
        name = "ctrip"
        use_mobile = True
        warmup_url = "https://example.invalid/"
        last_busy = False
        retry_after_s = 0
        last_block_url = ""
        last_block_api = ""
        last_scene = {}
        session_max_days = 0
        paths = []

        def __init__(self, cfg, logger):
            self.logger = logger

        def warmup(self, headless=True):
            warmed.append(self.name)
            self.warmup_cookie_ok = True
            return True

        def safe_fetch(self, *a, **k):
            self.paths = [{"path": "H5", "status": "ok", "rows": 1,
                           "mobile": True}]
            from core.models import FlightPrice
            return [FlightPrice(platform=self.name, from_city="SHA",
                                to_city="PEK", depart_date="2027-06-01",
                                price=900.0)]

    monkeypatch.setitem(M.REGISTRY, "ctrip", C)
    cfg = {"users": [{"name": "u", "platforms": ["ctrip"],
                      "notifier": {}, "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "PEK", "to_name": "北京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 900}]}],
           "schedule": {"scan_quiet_start": "", "scan_quiet_end": "",
                        "fast_ttl_min": 15, "slow_ttl_min": 120},
           "crawler": {"warmup": {"enabled": True,
                                  "platforms": ["qunar"]}},
           "output": {}, "web": {}}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    job = M.make_sweep_job(cfg, rt, logging.getLogger("r380-warm"),
                           _Store(str(tmp_path / "p.db")), lambda *a, **k: {})
    rt["pacing"].observe("ctrip", ["soft_reject"], "")
    job()
    assert warmed == ["ctrip"], "软拒后必须先预热再查"
    assert rt["pacing"].snapshot()["channels"]["ctrip"]["needs_warmup"] is False


class _Store:
    def __init__(self, path):
        self.db_path = path
        self.paths = []
        self.saved = []

    def latest_prices(self, *a, **k):
        return []

    def path_stats(self, *a, **k):
        return {}

    def save_fetch_path(self, *a, **k):
        self.paths.append(a)
        return 1

    def save_many(self, rows):
        self.saved.extend(list(rows))

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass

    def purge(self, *a, **k):
        return 0



def test_shadow_path_preference_ranks_and_avoids():
    from core.pacing import shadow_path_preference
    paths = {
        "H5": {"attempts": 27, "rate": 0.07},
        "PC": {"attempts": 12, "rate": 0.92},
        "API": {"attempts": 3, "rate": 0.0},     # 样本不足不参与
        "日历": {"attempts": 13, "rate": 0.0},   # 日历不参与
    }
    out = shadow_path_preference(paths)
    assert [x[0] for x in out["prefer"]] == ["PC", "H5"]
    assert [x[0] for x in out["avoid"]] == ["H5"]
    assert all(x[0] != "API" for x in out["prefer"] + out["avoid"])
    assert all(x[0] != "日历" for x in out["prefer"] + out["avoid"])


def test_urgency_ttl_near_date_is_shorter():
    now = [1_700_000_000.0]
    cfg = {"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                        "near_ratio": 0.15}}
    p = Pacing(cfg, clock=lambda: now[0])
    key = ("qunar", "SHA", "PEK", "2027-06-01")
    p.note_fetch("qunar", key, 900, True)          # 贴近阈值，快层
    now[0] += 16 * 60                              # 16 分钟
    # 远期：快层 30 分钟未到 -> skip；临期 3 天内：快层减半 15 -> fast
    assert p.plan_query("qunar", key, 900, days_ahead=40)[0] == "skip"
    assert p.plan_query("qunar", key, 900, days_ahead=2)[0] == "fast"


def test_urgency_ttl_far_date_slows_not_speeds():
    now = [1_700_000_000.0]
    cfg = {"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                        "near_ratio": 0.15}}
    p = Pacing(cfg, clock=lambda: now[0])
    key = ("qunar", "SHA", "PEK", "2027-06-01")
    p.note_fetch("qunar", key, 9000, True)         # 远离阈值，慢层
    now[0] += 130 * 60
    assert p.plan_query("qunar", key, 2500, days_ahead=20)[0] == "slow"
    # 40 天后：慢层翻倍到 240，130 分钟仍应跳过
    assert p.plan_query("qunar", key, 2500, days_ahead=40)[0] == "skip"


def test_rate_excl_empty_does_not_punish_sold_out(tmp_path):
    """5 次全空是售罄，不是路径劣化。"""
    st = PriceStorage(str(tmp_path / "prices.db"))
    for i in range(5):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                           "empty", attempt_id="e%d" % i)
    node = st.path_stats(24)["qunar"]
    assert node["paths"]["H5"]["rate"] == 0.0
    # 分母全是售罄空 -> 没有有效样本，返回 None（不是 0% 失败）
    assert node["paths"]["H5"]["rate_excl_empty"] is None
    a = advise("qunar", {"state": "ok"}, node["paths"], node=node)
    # 全空不应落"路径劣化"（它不是拦截/超时，是售罄）
    assert a["state"] != "path_degraded"


def test_rate_excl_empty_keeps_real_failure_visible(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "blocked",
                       attempt_id="b1")
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                           "empty", attempt_id="e%d" % i)
    node = st.path_stats(24)["qunar"]
    # 分母剔除 empty 后只剩 1 次 blocked -> 0%
    assert node["paths"]["H5"]["rate_excl_empty"] == 0.0
    a = advise("qunar", {"state": "ok"}, node["paths"], node=node)
    # 有效样本只有 1 次：不下"这条路径劣化"的结论（防 1 次抖动误杀），
    # 但渠道整体成功率仍低，必须如实报 degraded。
    assert a["state"] == "degraded"
    assert a["severity"] == "wait"


def test_probe_rows_are_persisted_with_evidence_level():
    import inspect
    import main
    src = inspect.getsource(main.make_sweep_job)
    assert 'evidence_level="probe"' in src
    assert 'attempt_id=_attempt' in src


def test_pacing_panel_refreshes_and_counts_down():
    import inspect
    import webui
    src = inspect.getsource(webui)
    assert "_paceStartAuto" in src and "setInterval" in src
    # 节流面板 2026-10-27 移入「监控 · 渠道健康」：轮询条件随之从
    # 「在配置页」改为「在监控页的健康 tab」，否则搬到新位置后不再刷新。
    assert "if(document.hidden||VIEW!=='mon'||MONTAB!=='health')" in src.replace("  if(document.hidden", "if(document.hidden")
    assert "已自动处理" in src          # 自动类建议不再被过滤
    assert "软拒" in src                # 路径提示可见软拒


def test_initial_round_snapshot_has_budget_fields():
    """进程刚起、还没跑第一轮时，前端读到的字段也必须齐。"""
    p = Pacing({})
    rnd = p.snapshot()["last_round"]
    for k in ("sent", "paced", "sent_by", "paced_by"):
        assert k in rnd, k
    assert rnd["sent"] == 0 and rnd["paced"] == 0
