# -*- coding: utf-8 -*-
"""PR #21 的同源补漏：App 日期视野（能力边界）还有几条路会漏网。

PR #21 把「日期超视野的 App 不派发」补到了反补/换道，并让能力边界轮
不再计入断供。这里钉住同一类缺陷的其余入口：

  1. 往返只看出程日：返程日在视野外时 App 照样被派发，滚日历滚不到
     → `app-date unsupported`，白烧一次设备；
  2. 自检取「该航线第一个日期」：它超视野时自检必然 0 条，看起来像
     渠道坏了（能力边界冒充故障）；
  3. 补采：`rt["failed"]` 里的远期查询照样派 App；
  4. 特价核实：用户平台集里的 App 不分日期一律参与核实；
  5. 爬虫层守卫只看出程日（`reject_far_dates(dates)`），自检/补采等
     直调入口绕不过去；
  6. 视野配置夹取口径：爬虫要求 7–400，越界回落 62；主扫描原来只要求
     >0，配了 5 天会把所有 App 渠道全滤掉（与爬虫口径漂移）。
"""
import io
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402

TODAY = date.today()
FAR = (TODAY + timedelta(days=200)).isoformat()
NEAR = (TODAY + timedelta(days=10)).isoformat()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 1. 返程日也要过视野 ----------
def test_return_date_outside_horizon_drops_app():
    plats = {"app_ctrip", "ctrip"}
    kept, dropped = M._drop_far_app_channels(plats, NEAR, {},
                                             ret_dates=[FAR])
    assert kept == {"ctrip"}, "返程日在视野外，App 不该被派发"
    assert {p for p, _ in dropped} == {"app_ctrip"}

    kept2, dropped2 = M._drop_far_app_channels({"app_ctrip"}, NEAR, {},
                                               ret_dates=[NEAR])
    assert kept2 == {"app_ctrip"} and dropped2 == []


def test_bad_main_date_stays_noop_with_ret_dates():
    """主日期解析不了就不动（原有契约）；返程日不能把它变成另一次过滤。"""
    kept, dropped = M._drop_far_app_channels({"app_ctrip"}, "not-a-date", {},
                                             ret_dates=[FAR])
    assert kept == {"app_ctrip"} and dropped == []


# ---------- 6. 视野夹取与爬虫同口径 ----------
def test_horizon_clamp_matches_crawler():
    def hz(v):
        return M._app_horizon_days(
            {"crawler": {"app_date_horizon_days": v}}, "app_x")

    assert hz(5) == 62, "低于 7 天是无效配置，爬虫会回落 62，主扫描必须一致"
    assert hz(500) == 62, "高于 400 天同理"
    assert hz(7) == 7 and hz(400) == 400


# ---------- 5. 爬虫层守卫包含返程日 ----------
def test_app_fetch_guard_includes_return_date():
    from crawlers.app_ctrip import AppCtripCrawler
    from crawlers.app_fliggy import AppFliggyCrawler
    from crawlers.app_qunar import AppQunarCrawler
    from crawlers.app_tongcheng import AppTongchengCrawler
    from crawlers.app_zhixing import AppZhixingCrawler

    for cls in (AppCtripCrawler, AppFliggyCrawler, AppQunarCrawler,
                AppTongchengCrawler, AppZhixingCrawler):
        seen = []

        class _Probe(cls):
            def early_skip(self, dates, path="app-login"):
                return False

            def reject_far_dates(self, dates):
                seen.append(list(dates))
                return True

        c = _Probe({}, logging.getLogger("horizon-guard"))
        assert c.fetch("SHA", "PEK", [NEAR], ret_date=FAR) == []
        assert seen and FAR in seen[0], (
            "%s 的视野守卫没看返程日 %s：%s" % (cls.__name__, FAR, seen))


# ---------- 2/3. 自检与补采 ----------
class _Store:
    def __init__(self, path):
        self.db_path = path

    def latest_prices(self, *a, **k):
        return []

    def path_stats(self, *a, **k):
        return {}

    def save_fetch_path(self, *a, **k):
        return 1

    def save_intervention(self, *a, **k):
        return 1

    def save_many(self, rows):
        pass

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass


class _AppCrawlerStub:
    name = "app_zhixing"
    paths = []
    warmup_url = ""
    warmup_cookies = []
    last_block_url = ""
    last_scene = {}
    retry_after_s = 0
    calls = []

    def __init__(self, cfg, logger):
        self.logger = logger

    def warmup(self, headless=True):
        return True

    def safe_fetch(self, fc, tc, dates, ret_date=""):
        _AppCrawlerStub.calls.append([str(x) for x in dates])
        self.paths = [{"path": "app-date", "status": "ok", "rows": 3,
                       "detail": "stub"}]
        return [object()]


def _job(tmp_path, monkeypatch, route_dates):
    _AppCrawlerStub.calls = []
    monkeypatch.setattr(M, "REGISTRY", {"app_zhixing": _AppCrawlerStub})
    cfg = {"schedule": {}, "crawler": {}, "output": {}, "web": {},
           "users": [{"name": "u", "platforms": ["app_zhixing"],
                      "notifier": {}, "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "PEK", "to_name": "北京",
                                  "dates": list(route_dates),
                                  "alert_direct": 900}]}]}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    M.make_sweep_job(cfg, rt, logging.getLogger("horizon-more"),
                     _Store(str(tmp_path / "p.db")), lambda *a, **k: {})
    return rt


def test_probe_app_channel_picks_date_within_horizon(tmp_path, monkeypatch):
    """自检不能拿超视野的日期去问 App：那必然 0 条，会把能力边界
    误报成渠道故障。同一航线里有视野内日期时取它。"""
    rt = _job(tmp_path, monkeypatch, [FAR, NEAR])
    out = rt["probe_channel"]("app_zhixing")
    assert out["ok"] is True, out
    assert out["query"][2] == NEAR, out
    assert _AppCrawlerStub.calls == [[NEAR]], _AppCrawlerStub.calls


def test_probe_app_channel_refuses_far_only_dates(tmp_path, monkeypatch):
    """所有配置日期都超视野：明确说「能力边界」，且根本不启动设备。"""
    rt = _job(tmp_path, monkeypatch, [FAR])
    out = rt["probe_channel"]("app_zhixing")
    assert out["ok"] is False
    assert "视野" in out["err"], out
    assert _AppCrawlerStub.calls == [], "超视野不该发请求"


def test_refetch_skips_far_app_queries(tmp_path, monkeypatch):
    """补采只补真失败；超视野的键派出去也只会再记一条 unsupported。"""
    rt = _job(tmp_path, monkeypatch, [FAR])
    rt["failed"] = {"app_zhixing": {("SHA", "PEK", FAR)}}
    out = rt["refetch_failed"]("app_zhixing")
    assert out["n"] == 0 and out["rows"] == 0, out
    assert _AppCrawlerStub.calls == [], "超视野不该补采"

    rt["failed"] = {"app_zhixing": {("SHA", "PEK", NEAR)}}
    out2 = rt["refetch_failed"]("app_zhixing")
    assert out2["n"] == 1, out2
    assert _AppCrawlerStub.calls == [[NEAR]], _AppCrawlerStub.calls


# ---------- 4. 特价核实 ----------
def test_special_verify_drops_far_app_crawlers():
    class _C:
        def __init__(self, name):
            self.name = name

    crawlers = [_C("app_ctrip"), _C("ctrip")]
    kept, dropped = M._drop_far_app_crawlers(crawlers, FAR, {})
    assert [c.name for c in kept] == ["ctrip"]
    assert {p for p, _ in dropped} == {"app_ctrip"}

    kept2, dropped2 = M._drop_far_app_crawlers(crawlers, NEAR, {})
    assert [c.name for c in kept2] == ["app_ctrip", "ctrip"]
    assert dropped2 == []


def test_special_verify_filters_before_safe_fetch():
    """接线：核实循环里必须先过滤再 safe_fetch（否则设备照起）。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    i_f = src.index("_cs, _far_s = _drop_far_app_crawlers(")
    assert "d.date" in src[i_f:i_f + 120], "核实过滤必须带入候选日期"
    i_fetch = src.index("rows = c.safe_fetch(d.from_code, d.to_code", i_f)
    assert i_f < i_fetch, (i_f, i_fetch)


# ---------- 7. 策略闸门 = 我方不打，不是断供 ----------
def test_policy_gate_records_paced_not_failure():
    """`_policy_gate` 关闸是**我方主动不发**（crawlers/base 的注释也这么写），
    但旧实现直接 return [] 且不留任何路径证据——主扫描把它当零行失败：
    yield_stats 记一次失败、渠道零数据哨累计、失败换道还会换出去。

    PR #21 的口径（能力边界/让位轮不算断供）同样适用，所以关闸轮必须
    留一条 `paced` 证据；浏览器与 App 两侧都是同一个入口。"""
    from core.yield_stats import is_non_attempt
    from crawlers.app_base import AppCrawler
    from crawlers.base import BaseCrawler

    class _Browser(BaseCrawler):
        name = "ctrip"

        def _policy_gate(self, dim=""):
            return False

    class _App(AppCrawler):
        name = "app_ctrip"

        def _policy_gate(self, dim=""):
            return False

    for c in (_Browser({}, logging.getLogger("policy-gate")),
              _App({}, logging.getLogger("policy-gate"))):
        assert c.safe_fetch("SHA", "PEK", [NEAR]) == []
        assert c.paths, "%s 关闸轮没留路径证据" % type(c).__name__
        assert all(p.get("status") == "paced" for p in c.paths), c.paths
        assert is_non_attempt(c.paths) is True, c.paths
        assert M._fail_evidence(c.paths) == []


def test_planning_and_switch_pass_return_dates():
    """接线：规划复滤与第二波换道都必须把返程日带进视野判断。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert src.count("ret_dates=_rd_q") >= 2, "规划两处复滤都要带返程日"
    i_sw = src.index("_kept3, _far3 = _drop_far_app_channels(")
    i_crawl = src.index("_apps = get_crawlers([_app])", i_sw)
    seg = src[i_sw:i_crawl]
    assert "ret_dates=" in seg, "换道视野守卫也要看返程日"
