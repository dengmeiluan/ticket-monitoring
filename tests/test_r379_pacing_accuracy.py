# -*- coding: utf-8 -*-
"""r379: 节流准确率与幂等回归。

覆盖四类容易“看起来正常”的错误：
  1. 路径尝试率把“换路成功”误判成渠道失败；
  2. 最近一次尝试（失败）刷新了新鲜度，掩盖“一直没成功”；
  3. 重启后 TTL 归零，全部查询重新打站；
  4. 验证窗口/预热/采集使用不同指纹，或旧证据跨查询污染熔断。
"""
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import (  # noqa: E402
    Pacing, advise, parse_local_ts, should_watch_response,
)
from core.storage import PriceStorage  # noqa: E402
from crawlers.base import (  # noqa: E402
    BaseCrawler, channel_slot, platform_lock,
)


def _store(tmp_path):
    return PriceStorage(str(tmp_path / "prices.db"))


# ---------- 响应监听范围 ----------
def test_response_filter_ignores_assets_and_analytics():
    assert should_watch_response("document", "https://m.ctrip.com/x") is True
    assert should_watch_response("xhr", "https://m.ctrip.com/api") is True
    assert should_watch_response("fetch", "https://m.ctrip.com/api") is True
    assert should_watch_response("image", "https://m.ctrip.com/a.png") is False
    assert should_watch_response("script", "https://m.ctrip.com/a.js") is False
    assert should_watch_response(
        "document", "https://www.google-analytics.com/collect") is False
    assert should_watch_response(
        "fetch", "https://hm.baidu.com/hm.js") is False
    assert should_watch_response("document", "") is False


# ---------- 本地时间 ----------
def test_parse_local_ts_formats():
    assert parse_local_ts("2026-10-26 10:00:00") > 0
    assert parse_local_ts("2026-10-26T10:00:00") > 0
    assert parse_local_ts("2026-10-26 10:00") > 0
    assert parse_local_ts("2026-10-26") > 0
    assert parse_local_ts("") == 0
    assert parse_local_ts("not-a-time") == 0
    assert parse_local_ts(None) == 0


# ---------- 路径账：查询口径 + 国内/国际 + 明细/日历 ----------
def test_path_stats_query_level_scopes_and_last_success(tmp_path):
    st = _store(tmp_path)
    d = "2027-06-01"
    # 同一查询：H5 被拦，PC 兜底成功 -> 查询成功，不应把渠道判死
    st.save_fetch_path("ctrip", "SHA", "NRT", d, "H5", "blocked",
                       attempt_id="a1")
    st.save_fetch_path("ctrip", "SHA", "NRT", d, "PC", "ok", rows=5,
                       attempt_id="a1")
    # 只有日历价，没有明细
    st.save_fetch_path("ctrip", "SHA", "BKK", d, "H5", "calendar",
                       attempt_id="a2")
    # 国内航线
    st.save_fetch_path("ctrip", "SHA", "PEK", d, "PC", "ok", rows=3,
                       attempt_id="a3")

    node = st.path_stats(24)["ctrip"]
    assert node["query_attempts"] == 3
    assert node["query_ok"] == 3
    assert node["query_rate"] == 1.0
    assert node["query_detail_ok"] == 2
    assert node["query_calendar_only"] == 1
    assert node["paths"]["H5"]["blocked"] == 1
    assert node["paths"]["H5"]["calendar_ok"] == 1
    assert node["paths"]["PC"]["ok"] == 2
    assert node["last_ok_at"] != ""
    assert node["scopes"]["dom"]["query_attempts"] == 1
    assert node["scopes"]["intl"]["query_attempts"] == 2
    assert node["scopes"]["intl"]["paths"]["H5"]["calendar_ok"] == 1


def test_path_stats_last_ok_excludes_failed_attempts(tmp_path):
    st = _store(tmp_path)
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "blocked",
                       attempt_id="a1")
    node = st.path_stats(24)["qunar"]
    # 最近一次尝试是刚才，但从来没有成功；last_ok_at 必须为空
    assert node["last_at"] != ""
    assert node["last_ok_at"] == ""


# ---------- 重启续 TTL ----------
def test_seed_fetch_prevents_restart_burst():
    now = [1_700_000_000.0]
    p = Pacing({"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120}},
               clock=lambda: now[0])
    key = ("ctrip", "SHA", "NRT", "2027-06-01")
    assert p.seed_fetch("ctrip", key, 800, now[0] - 5 * 60) is True
    assert p.plan_query("ctrip", key, 0)[0] == "skip"
    # 重复/更旧的记录不得把时间往回拨
    assert p.seed_fetch("ctrip", key, 700, now[0] - 60 * 60) is False
    assert p.plan_query("ctrip", key, 0)[0] == "skip"
    # 超过 TTL 的记录仍会进入快层，不会被永久静默
    p2 = Pacing({"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120}},
                clock=lambda: now[0])
    p2.seed_fetch("ctrip", key, 800, now[0] - 40 * 60)
    assert p2.plan_query("ctrip", key, 0)[0] == "fast"


def test_latest_prices_detail_only_and_latest(tmp_path):
    st = _store(tmp_path)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 7200))
    mid = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3600))
    st.save_many([
        SimpleNamespace(platform="ctrip", from_city="SHA", to_city="NRT",
                        depart_date="2027-06-01", price=100.0,
                        airline="", flight_no="", depart_time="08:00",
                        arrive_time="12:00", fetched_at=old, extra="{}",
                        prov=""),
        # 更新的日历行（无时刻）不能覆盖明细基线
        SimpleNamespace(platform="ctrip", from_city="SHA", to_city="NRT",
                        depart_date="2027-06-01", price=90.0,
                        airline="", flight_no="", depart_time="",
                        arrive_time="", fetched_at=mid, extra="{}", prov=""),
        SimpleNamespace(platform="ctrip", from_city="SHA", to_city="PEK",
                        depart_date="2027-06-01", price=300.0,
                        airline="", flight_no="", depart_time="09:00",
                        arrive_time="11:00", fetched_at=old, extra="{}",
                        prov=""),
        SimpleNamespace(platform="ctrip", from_city="SHA", to_city="PEK",
                        depart_date="2027-06-01", price=280.0,
                        airline="", flight_no="", depart_time="10:00",
                        arrive_time="12:00", fetched_at=now, extra="{}",
                        prov=""),
    ])
    rows = {(r["from_city"], r["to_city"]): r for r in st.latest_prices(24)}
    assert rows[("SHA", "NRT")]["price"] == 100.0
    assert rows[("SHA", "PEK")]["price"] == 280.0


# ---------- 建议引擎 ----------
def test_advise_calendar_only_is_not_healthy():
    a = advise("ctrip", {"state": "ok"},
               {"H5": {"attempts": 8, "ok": 8, "rate": 1.0,
                       "detail_ok": 0, "calendar_ok": 8,
                       "last_ok_at": ""}})
    assert a["state"] == "calendar_only"
    assert a["action"] == "probe"


def test_advise_stale_uses_last_success_not_last_attempt():
    import datetime as _dt
    now = 1_700_000_000.0
    old_ok = _dt.datetime.fromtimestamp(now - 300 * 60).strftime(
        "%Y-%m-%d %H:%M:%S")
    recent_fail = _dt.datetime.fromtimestamp(now - 60).strftime(
        "%Y-%m-%d %H:%M:%S")
    a = advise("ctrip", {"state": "ok"},
               {"PC": {"attempts": 10, "ok": 9, "rate": 0.9,
                       "detail_ok": 9, "calendar_ok": 0,
                       "last_at": recent_fail, "last_ok_at": old_ok}},
               now=now)
    assert a["state"] == "stale"
    assert "300" in a["hint"]


def test_advise_uses_platform_query_rate_over_path_rate():
    import datetime as _dt
    now = 1_700_000_000.0
    fresh = _dt.datetime.fromtimestamp(now - 60).strftime(
        "%Y-%m-%d %H:%M:%S")
    node = {"attempts": 20, "ok": 20, "detail_ok": 10, "calendar_ok": 10,
            "query_attempts": 10, "query_ok": 2, "query_rate": 0.2,
            "query_detail_ok": 2, "query_calendar_only": 0,
            "last_at": fresh, "last_ok_at": fresh}
    a = advise("ctrip", {"state": "ok"},
               {"PC": {"attempts": 10, "ok": 10, "rate": 1.0,
                       "detail_ok": 10, "calendar_ok": 0},
                "H5": {"attempts": 10, "ok": 10, "rate": 1.0,
                       "detail_ok": 10, "calendar_ok": 0}},
               now=now, node=node)
    # 路径都 100%，但 10 次查询只有 2 次成功 -> 渠道整体仍是低成功率
    assert a["state"] == "degraded"
    assert a["action"] == "watch"


def test_advise_calendar_only_from_platform_node():
    import datetime as _dt
    now = 1_700_000_000.0
    fresh = _dt.datetime.fromtimestamp(now - 60).strftime(
        "%Y-%m-%d %H:%M:%S")
    node = {"attempts": 8, "ok": 8, "detail_ok": 0, "calendar_ok": 8,
            "query_attempts": 8, "query_ok": 8, "query_rate": 1.0,
            "query_detail_ok": 0, "query_calendar_only": 8,
            "last_at": fresh, "last_ok_at": fresh}
    a = advise("ctrip", {"state": "ok"},
               {"H5": {"attempts": 8, "ok": 8, "rate": 1.0,
                       "detail_ok": 0, "calendar_ok": 8}},
               now=now, node=node)
    assert a["state"] == "calendar_only"
    assert a["action"] == "probe"


# ---------- 干预接口：同源/JSON/体积 ----------
def test_post_json_guard_rejects_unsafe_requests():
    import io
    from webui import _Handler

    class Fake:
        command = "POST"

        def __init__(self, headers, body=b"{}"):
            self.headers = headers
            self.rfile = io.BytesIO(body)
            self.out = None

        def _json(self, obj, code=200):
            self.out = (obj, code)

    h = Fake({"Content-Type": "application/json",
              "Content-Length": "2"}, b"{}")
    assert _Handler._post_json(h, "测试") == {}
    h = Fake({"Content-Type": "text/plain", "Content-Length": "2"})
    assert _Handler._post_json(h, "测试") is None
    assert h.out[1] == 415
    h = Fake({"Content-Type": "application/json",
              "Content-Length": "2", "Host": "127.0.0.1:8765",
              "Origin": "https://evil.example"}, b"{}")
    assert _Handler._post_json(h, "测试") is None
    assert h.out[1] == 403
    h = Fake({"Content-Type": "application/json",
              "Content-Length": "100"}, b"{}")
    assert _Handler._post_json(h, "测试", max_len=10) is None
    assert h.out[1] == 413
    h = Fake({"Content-Type": "application/json",
              "Content-Length": "2"}, b"[]")
    assert _Handler._post_json(h, "测试") is None
    assert h.out[1] == 400


def test_intervention_endpoints_are_guarded_and_whitelisted():
    # 直接读文件而不是 inspect.getsource(模块)：
    # 全套运行时其它测试可能替换 webui._Handler，导致取到替换对象的源码。
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "webui.py"), encoding="utf-8").read()
    for path, label in (("/api/pacing/reset", "解除"),
                        ("/api/channel/probe", "自检"),
                        ("/api/channel/verify", "验证"),
                        ("/api/channel/warmup", "预热")):
        block = src.split('self.path == "%s"' % path, 1)[1][:700]
        assert '_post_json("%s")' % label in block
        assert "not in PLATFORMS" in block



# ---------- 采集前证据清零 ----------
class _BoomCrawler(BaseCrawler):
    name = "qunar"

    def fetch(self, from_city, to_city, dates, ret_date=""):
        raise RuntimeError("boom")


def test_safe_fetch_clears_stale_evidence(tmp_path):
    c = _BoomCrawler({"user_data_dir": str(tmp_path / "ud")},
                     logging.getLogger("r379-boom"))
    c.paths = [{"path": "H5", "status": "blocked", "rows": 0}]
    c.retry_after_s = 99
    c.last_block_url = "https://old.example/block"
    c.last_block_api = "https://old.example/api"
    c._scene_pending = "https://old.example/block"
    c.last_scene = {"png": "old"}
    c._last_page = object()
    assert c.safe_fetch("SHA", "PEK", ["2027-06-01"]) == []
    assert c.paths == []
    assert c.retry_after_s == 0
    assert c.last_block_url == ""
    assert c.last_block_api == ""
    assert c._scene_pending == ""
    assert c.last_scene == {}
    assert c._last_page is None


# ---------- 渠道锁：同渠道等待不得占满全局浏览器配额 ----------
def test_channel_slot_waits_platform_before_global_slot():
    held = platform_lock("qunar")
    held.acquire()
    release = threading.Event()
    entered_other = threading.Event()

    def waiter():
        with channel_slot("qunar"):
            release.wait(2.0)

    def other():
        with channel_slot("ctrip"):
            entered_other.set()

    ts = [threading.Thread(target=waiter, daemon=True) for _ in range(2)]
    for t in ts:
        t.start()
    time.sleep(0.15)
    t_other = threading.Thread(target=other, daemon=True)
    t_other.start()
    assert entered_other.wait(1.0), "两个同渠道等待者不应堵住其他渠道"
    release.set()
    held.release()
    for t in ts:
        t.join(2.0)
    t_other.join(2.0)


# ---------- 验证窗口：关窗=保存+返回，不改指纹 ----------
class _FakePage:
    url = "https://m.ctrip.com/challenge"

    def goto(self, *args, **kwargs):
        return None

    def is_closed(self):
        return True


class _FakeCtx:
    def storage_state(self):
        return {"cookies": [{"name": "cticket", "value": "x"}]}


@contextmanager
def _fake_browser(*args, **kwargs):
    yield _FakeCtx()


class _MobileCrawler(BaseCrawler):
    name = "ctrip"
    use_mobile = True


def test_verify_window_close_saves_and_keeps_fingerprint(tmp_path, monkeypatch):
    import crawlers.base as B
    monkeypatch.setattr(B, "kernel_major", lambda: 151)
    c = _MobileCrawler({"user_data_dir": str(tmp_path / "ud"),
                        "mobile_user_agent": "Mozilla/5.0 (iPhone) "
                                             "Chrome/126.0.0.0 Mobile"},
                       logging.getLogger("r379-verify"))
    snaps = []
    c._write_session_state = lambda state, ts: snaps.append((state, ts))
    c.browser = _fake_browser
    c.new_page = lambda ctx: _FakePage()
    fp_before = c.fingerprint()
    assert c.open_challenge_window("https://m.ctrip.com/challenge",
                                   threading.Event(), timeout_s=1) is True
    assert snaps and snaps[-1][0]["cookies"]
    assert c.use_mobile is True
    assert c.fingerprint() == fp_before
    assert fp_before["is_mobile"] is True
    assert fp_before["ua"].startswith("Mozilla/5.0 (iPhone)")


class _ClosePage:
    url = "https://passport.example/login"

    def goto(self, *args, **kwargs):
        return None

    def is_closed(self):
        return True


class _OpenPage(_ClosePage):
    def is_closed(self):
        return False


class _LoginCrawler(BaseCrawler):
    name = "qunar"

    def login_url(self):
        return "https://passport.example/login"


def test_login_window_close_saves_but_does_not_claim_success(tmp_path,
                                                              monkeypatch):
    import crawlers.base as B
    import pytest
    monkeypatch.setattr(B, "kernel_major", lambda: 151)
    c = _LoginCrawler({"user_data_dir": str(tmp_path / "ud")},
                      logging.getLogger("r379-login"))
    snaps = []
    c._write_session_state = lambda state, ts: snaps.append((state, ts))
    c.browser = _fake_browser
    c.new_page = lambda ctx: _ClosePage()
    with pytest.raises(RuntimeError, match="关闭"):
        c._login_window(threading.Event(), timeout_s=1)
    assert snaps and snaps[-1][0]["cookies"]
    # 未确认关窗只落 cookie 快照，不能把 saved_at 推到"现在"
    assert snaps[-1][1] == 0
    assert c.use_mobile is False  # 桌面渠道默认仍用桌面身份


def test_login_confirmed_returns_true(tmp_path, monkeypatch):
    import crawlers.base as B
    monkeypatch.setattr(B, "kernel_major", lambda: 151)
    c = _LoginCrawler({"user_data_dir": str(tmp_path / "ud")},
                      logging.getLogger("r379-login2"))
    c._write_session_state = lambda state, ts: None
    c.browser = _fake_browser
    c.new_page = lambda ctx: _OpenPage()
    evt = threading.Event()
    threading.Timer(0.1, evt.set).start()
    assert c._login_window(evt, timeout_s=2) is True


# ---------- UI：四象限/日历/自检范围必须可见 ----------
def test_ctrip_pc_path_uses_desktop_identity_and_restores(monkeypatch):
    from crawlers.ctrip import CtripCrawler

    c = CtripCrawler({"user_data_dir": "x"}, logging.getLogger("r379-ctrip"))
    seen = {}

    def _pc(*a, **k):
        seen["mobile"] = c.use_mobile
        c.path_note("PC", "empty")
        return []

    monkeypatch.setattr(c, "_fetch_intl_list_pc", _pc)
    assert c._fetch_intl_list("SHA", "PEK", "SHA", "PEK",
                              ["2026-11-16"]) == []
    assert seen["mobile"] is False          # PC 入口必须桌面身份
    assert c.paths[-1]["mobile"] is False   # 路径账据此复用验证身份
    assert c.use_mobile is True             # 返回后恢复 H5 主身份


def test_pacing_ui_exposes_scope_calendar_and_probe_scope():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "webui.py"), encoding="utf-8").read()
    for needle in (
            "scoped('dom','国内')",
            "scoped('intl','国际')",
            "query_detail_ok",
            "query_calendar_only",
            "仅有日历",
            "数据陈旧",
            "probeScopeSel",
            "scope:_probeScope",
    ):
        assert needle in src, needle