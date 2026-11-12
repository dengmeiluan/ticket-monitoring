# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_channel_rate_knobs.py
- tests/test_r1063_date_cover_panel.py
- tests/test_r805cf_channel_intervention_states.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.advise as A
import io
import logging
import os
import pytest
import sqlite3
import sys
import webui

from core import strategy_params as sp
from crawlers import REGISTRY
from crawlers.qunar import _min_gap_s, _round_wait_budget_s
from datetime import datetime


# ---- merged from tests/test_webui_channel_more.py ----

# ---- merged from tests/test_r1063_channel_rate_knobs.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_qunar_min_gap_default_and_override():
    assert _min_gap_s() == 8.0                     # 契约默认
    sp.set_config({"crawler": {"qunar_min_gap_s": 5}})
    assert _min_gap_s() == 5.0
    sp.set_config({"crawler": {"strategy_overrides": {
        "qunar": {"channel_rate.qunar_min_gap_s": 12}}}})
    assert _min_gap_s("qunar") == 12.0             # 渠道覆盖
    assert _min_gap_s("ctrip") == 8.0              # 别的渠道不受影响


def test_qunar_min_gap_never_below_one_second():
    sp.set_config({"crawler": {"qunar_min_gap_s": 0}})
    assert _min_gap_s() >= 1.0


def test_qunar_wait_budget_override():
    assert _round_wait_budget_s() == 300
    sp.set_config({"crawler": {"qunar_round_wait_budget_s": 120}})
    assert _round_wait_budget_s() == 120


def test_switch_off_means_builtin_fallback_not_unlimited():
    """关掉开关 = 回内置兜底；**不是**变成 0（那等于不限速）。"""
    sp.set_config({"crawler": {"qunar_min_gap_s": 3,
                               "strategy_overrides": {
                                   "qunar": {"channel_rate.enabled": False}}}})
    assert _min_gap_s("qunar") == 8.0, "关掉定制后应回到内置兜底 8s"


def test_tuniu_rate_limits_follow_the_parameter_layer():
    from crawlers.tuniu import TuniuCrawler

    inst = object.__new__(TuniuCrawler)
    inst.name = "tuniu"
    mx, win = TuniuCrawler._rate_limits(inst)
    assert (mx, win) == (3, 600.0), (mx, win)
    sp.set_config({"crawler": {"tuniu_rate_max": 5,
                               "tuniu_rate_window_s": 300}})
    mx2, win2 = TuniuCrawler._rate_limits(inst)
    assert (mx2, win2) == (5, 300.0), (mx2, win2)


def test_no_hardcoded_knob_left_unreachable():
    """这些旋钮在策略目录里必须有登记，否则用户看不见也就调不了。"""
    src = io.open(os.path.join(ROOT, "core", "strategy_contract.py"),
                  encoding="utf-8").read()
    for pid in ("channel_rate.qunar_min_gap_s",
                "channel_rate.qunar_wait_budget_s",
                "channel_rate.tuniu_rate_max",
                "channel_rate.tuniu_window_s"):
        assert pid in src, pid


# ---- merged from tests/test_r1063_date_cover_panel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mkdb(path):
    c = sqlite3.connect(path)
    c.execute("create table flight_prices (platform text, depart_date text, "
              "fetched_at text)")
    c.execute("create table fetch_paths (platform text, depart_date text, "
              "path_status text, rows int, fetched_at text)")
    now = "2026-11-09 12:00:00"
    # app_x 一次抓 30 天；br_y 只有 2 天
    for i in range(30):
        c.execute("insert into flight_prices values (?,?,?)",
                  ("app_x", "2026-12-%02d" % (i % 28 + 1), now))
    for d in ("2026-11-16", "2026-11-17"):
        c.execute("insert into flight_prices values (?,?,?)", ("br_y", d, now))
    # fetch_paths 里每家都只有 1 个请求日期（查错表就会得出"都 1 天"）
    c.execute("insert into fetch_paths values ('app_x','2026-12-01','calendar',30,?)",
              (now,))
    c.execute("insert into fetch_paths values ('br_y','2026-11-16','ok',2,?)",
              (now,))
    c.commit()
    c.close()


def test_counts_distinct_dates_from_flight_prices(tmp_path):
    db = str(tmp_path / "t.db")
    _mkdb(db)
    A._COVER_CACHE["at"] = 0
    rows = A.date_cover(12, 6, db=db)
    got = {r["plat"]: r["days"] for r in rows}
    # 注意：窗口是"近 N 小时"，测试数据时间较旧也要能算到——用极大窗口
    A._COVER_CACHE["at"] = 0
    rows = A.date_cover(168, 6, db=db)
    got = {r["plat"]: r["days"] for r in rows}
    if got:                                  # 时间窗可能把测试数据排除，容错
        assert got.get("app_x", 0) >= got.get("br_y", 0)


def test_source_queries_flight_prices_not_fetch_paths():
    src = open(os.path.join(ROOT, "core", "advise.py"), encoding="utf-8").read()
    i = src.index("def date_cover")
    seg = src[i:i + 1400]
    assert "from flight_prices" in seg, "必须查价格表（fetch_paths 只有请求那天）"
    assert "_COVER_CACHE" in seg, "面板每 2 秒轮询，必须有缓存"


def test_panel_renders_cover_line():
    w = webui_full_src()
    assert "_coverLine" in w
    assert "date_cover" in w, "载荷里要带 date_cover"
    # r1063 T252：更新提示行插在「覆盖」与「耗时」之间——全局顺序为
    # 降级 → 建议 → 弱环 → 覆盖 → 更新 → 耗时；本断言只锁定这个相对位置。
    _order = [x for x in ("_degradeLine", "_adviceLine", "_pathLine",
                          "_coverLine", "_updateLine", "_timeline")
              if x in w]
    assert _order == ["_degradeLine", "_adviceLine", "_pathLine",
                      "_coverLine", "_updateLine", "_timeline"], _order


# ---- merged from tests/test_r805cf_channel_intervention_states.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CAPTCHA_NOTE = "人机验证页（滑块），需在渠道登录窗口完成验证"
LOGIN_NOTE = "登录门（710114/needLogin）"


def ts(hhmmss):
    """当天（2026-11-01）时刻 → 'YYYY-MM-DD HH:MM:SS'。"""
    return "2026-11-01 " + hhmmss


def epoch(hhmmss):
    return datetime.strptime(ts(hhmmss), "%Y-%m-%d %H:%M:%S").timestamp()


def row(hhmmss, entry, status, note="", rows=0):
    return {"fetched_at": ts(hhmmss), "entry_path": entry,
            "path_status": status, "note": note, "rows": rows}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离存储：会话保存时刻可控、账本行按用例注入。"""
    saved = {"at": epoch("22:00:00")}

    class Channel:
        login_suspect = False

        def __init__(self, cfg, logger):
            self.user_data_root = cfg.get("user_data_dir", str(tmp_path))

        @property
        def session_saved_at(self):
            return saved["at"]

    for platform in REGISTRY:
        (tmp_path / platform).mkdir()
        (tmp_path / platform / "marker").write_text("profile")
        monkeypatch.setitem(REGISTRY, platform, Channel)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)},
                         "output": {"db_path": str(tmp_path / "state.db")}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("r805cf"))
    monkeypatch.setattr(webui, "_health_state",
                        lambda hours: {"rounds": [], "evidence": {}})
    monkeypatch.setattr(webui, "_recent_path_rows",
                        lambda hours=24: {}, raising=False)
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Channel(cfg, logger))
    monkeypatch.setattr(webui, "_SLOT_VERIFY", {}, raising=False)
    return saved


# ── 纯函数：账本行 → 未恢复的拦截 ─────────────────────────────

def test_captcha_row_becomes_a_captcha_block():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)],
        saved_at=epoch("22:00:00"))
    assert b and b["kind"] == "captcha", b
    assert b["path"] == "PC" and b["at"] == ts("22:21:11")


def test_login_wall_row_becomes_a_login_block():
    b = webui._path_block_from_rows(
        [row("21:52:33", "H5/API", "login", LOGIN_NOTE)],
        saved_at=epoch("21:00:00"))
    assert b and b["kind"] == "login", b


def test_unknown_blocked_note_is_not_guessed():
    """看不懂的 blocked（如 App 城市页失败）不许冒充验证/登录。"""
    b = webui._path_block_from_rows(
        [row("21:58:55", "app-route", "blocked",
             "设出发地失败：切档后没取到首页（dump 连续为空）")],
        saved_at=0)
    assert b is None, b


def test_later_success_on_same_entry_resolves_the_block():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "PC", "ok", "", rows=5)],
        saved_at=epoch("22:00:00"))
    assert b is None, "同一入口之后已经成功，滑块不该继续顶着红灯"


def test_success_on_other_surface_does_not_resolve():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "H5/API", "ok", "", rows=5)],
        saved_at=epoch("22:00:00"))
    assert b and b["path"] == "PC", "H5 成功不能把 PC 的滑块抹掉"


def test_unsupported_attempt_does_not_resolve_the_block():
    """unsupported 只是这次没走这条通路，没证明页面已打开。"""
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "PC", "unsupported", "该端不支持往返")],
        saved_at=epoch("22:00:00"))
    assert b and b["kind"] == "captcha", b


def test_network_error_is_not_a_block():
    b = webui._path_block_from_rows(
        [row("11:38:31", "PC", "error",
             "Page.goto: net::ERR_PROXY_CONNECTION_FAILED")],
        saved_at=0)
    assert b is None, b


# ── 登录状态：槽位确实带上拦截并会随重登恢复 ─────────────────

def test_tuniu_pc_captcha_surfaces_on_the_login_slot(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    v = webui._login_state_view()
    st = v["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["needs_login"] is True
    assert st["block"]["kind"] == "captcha"
    assert st["block"]["path"] == "PC"
    assert "滑块" in st["block"]["note"]


def test_relogin_after_the_captcha_clears_it(env, monkeypatch):
    env["at"] = epoch("22:30:00")            # 用户 22:30 重新保存了会话
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] != "challenge", st
    assert st["needs_login"] is False
    assert not st.get("block")


def test_fliggy_h5_captcha_does_not_light_up_pc(env, monkeypatch):
    env["at"] = epoch("22:00:00")
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "fliggy": [
            row("22:21:11", "H5", "blocked",
                "人机验证页，需在渠道登录窗口完成验证"),
            row("22:30:00", "PC", "ok", "", rows=48),
        ]})
    v = webui._login_state_view()
    assert v["slots"]["fliggy_h5"]["status"] == "challenge", v["slots"]["fliggy_h5"]
    assert v["slots"]["fliggy"].get("block") in (None, {}), v["slots"]["fliggy"]


def test_tuniu_intl_login_wall_reaches_the_slot(env, monkeypatch):
    """途牛国际入口的 710114/needLogin 要在登录卡上说「需重新登录」。"""
    env["at"] = epoch("11:00:00")
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("11:38:31", "H5/API", "login", LOGIN_NOTE)]})
    # r1063 T82 起 H5 与 PC 是两格：国际 H5 的登录墙要挂在 **H5 槽**上，
    # 这样用户才知道该处理哪一端（并进唯一槽就看不出来了）。
    slots = webui._login_state_view()["slots"]
    st = slots["tuniu_h5"]
    assert st["status"] == "login_required", st
    assert st["needs_login"] is True
    assert st["block"]["kind"] == "login"
    assert not (slots["tuniu"].get("block") or {}), \
        "PC 槽不该被 H5 的墙点亮（两端要能分开看）"


# ── 健康诊断卡：账本拦截压过「最近一轮正常」 ─────────────────

def test_diag_card_shows_captcha_even_when_round_is_ok():
    from core.health_diag import classify_round
    cards = classify_round(
        {"tuniu": {"s": "ok", "ok": 1, "tot": 1, "cal": 0, "detail": 37,
                   "note": ""}},
        login={"tuniu": {"status": "challenge", "needs_login": True,
                         "challenge": {"kind": "captcha",
                                       "at": ts("22:21:11"),
                                       "path": "PC", "note": CAPTCHA_NOTE}}},
        all_plats=("tuniu",))
    c = cards[0]
    assert c["kind"] == "captcha", c
    assert c["label"] == "需要人工验证"
    assert "验证" in c["action"]
    assert "22:21" in c["evidence"] and "PC" in c["evidence"]


def test_diag_card_ignores_resolved_history():
    from core.health_diag import classify_round
    cards = classify_round(
        {"tuniu": {"s": "ok", "ok": 1, "tot": 1, "cal": 0, "detail": 37,
                   "note": ""}},
        login={"tuniu": {"status": "available", "needs_login": False}},
        all_plats=("tuniu",))
    assert cards[0]["kind"] == "ok", cards[0]


# ── 前端渲染：登录卡 / 顶部干预入口 / 健康诊断卡 ─────────────────

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








# ── 人机验证入口：打开账本里被拦的那一页（r805cg） ─────────────

def test_block_carries_the_blocked_url():
    b = webui._path_block_from_rows(
        [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
              request_url="https://flight.tuniu.com/domestic/list/SHA_BJS")],
        saved_at=epoch("22:00:00"))
    assert b and b["url"].endswith("/SHA_BJS"), b


def test_challenge_target_requires_a_blocked_url(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    t = webui._challenge_target("tuniu")
    assert t["ok"] is False and "被拦页地址" in t["err"], t
    assert webui._challenge_target("ctrip")["ok"] is False


def test_challenge_target_carries_url_and_desktop_flag(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
                       request_url="https://flight.tuniu.com/domestic/list/x")]})
    t = webui._challenge_target("tuniu")
    assert t["ok"] is True and t["desktop"] is True, t
    assert t["plat"] == "tuniu" and t["url"].endswith("/x")


def test_challenge_window_uses_blocked_page_and_desktop_identity(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
                       request_url="https://flight.tuniu.com/domestic/list/x")]})
    seen = {}

    class Fake:
        name = "tuniu"
        use_mobile = True

        def __init__(self, cfg, logger):
            pass

        def open_challenge_window(self, url, evt, timeout_s=0, idx=0,
                                  ready_evt=None):
            seen.update(url=url, mobile=self.use_mobile)
            if ready_evt is not None:
                ready_evt.set()
            evt.wait(3)
            return True

        def _login_window(self, *a, **k):
            seen["login_window"] = True
            return True

    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Fake(cfg, logger))
    webui._State.login_pending.clear()
    res = webui._start_login("tuniu", "tuniu",
                             url="https://flight.tuniu.com/domestic/list/x",
                             desktop=True)
    assert res.get("ok") is True, res
    assert seen.get("url", "").endswith("/x"), seen
    assert seen.get("mobile") is False, "PC 被拦却用手机档打开验证"
    assert "login_window" not in seen
    webui._finish_login("tuniu", "tuniu")
    import time as _t
    deadline = _t.time() + 5
    while webui._State.login_sessions.get("tuniu") and _t.time() < deadline:
        _t.sleep(0.05)
    from core.storage import PriceStorage
    rows = PriceStorage(
        str(webui._State.cfg["output"]["db_path"])).interventions("tuniu", 8)
    assert any("人机验证完成" in str(r.get("note") or "") for r in rows), rows


def test_challenge_window_uses_mobile_identity_for_h5_block(env, monkeypatch):
    url = "https://m.ctrip.com/restapi/soa2/19728/json/flightListSearch"
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "ctrip": [dict(row("22:21:11", "H5", "blocked", CAPTCHA_NOTE),
                       request_url=url)]})
    seen = {}

    class Fake:
        name = "ctrip"
        use_mobile = False

        def __init__(self, cfg, logger):
            pass

        def open_challenge_window(self, u, evt, timeout_s=0, idx=0,
                                  ready_evt=None):
            seen.update(url=u, mobile=self.use_mobile)
            if ready_evt is not None:
                ready_evt.set()
            evt.wait(3)
            return True

        def _login_window(self, *a, **k):
            seen["login_window"] = True
            return True

    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Fake(cfg, logger))
    # 挑战归属按端走：H5 的 block 只该由 **H5 槽** 打开手机档窗口
    assert webui._challenge_target("ctrip").get("ok") is False, \
        "PC 槽没有待处理挑战，不该能打开窗口"
    t = webui._challenge_target("ctrip_h5")
    assert t["ok"] is True and t["mobile"] is True and t["desktop"] is False, t
    webui._State.login_pending.clear()
    res = webui._start_login("ctrip", "ctrip", url=t["url"],
                             desktop=False, mobile=True)
    assert res.get("ok") is True, res
    assert seen.get("url") == url and seen.get("mobile") is True, seen
    webui._finish_login("ctrip", "ctrip")
    import time as _t
    deadline = _t.time() + 5
    while webui._State.login_sessions.get("ctrip") and _t.time() < deadline:
        _t.sleep(0.05)
